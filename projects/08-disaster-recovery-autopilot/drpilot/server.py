"""HTTP front end: Alertmanager posts to /alerts; /incidents lists what the responder knows."""

from __future__ import annotations

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .alertmanager import PayloadError
from .engine import Responder

MAX_BODY = 1_000_000


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def create_server(host: str, port: int, responder: Responder, token: str | None) -> ThreadingHTTPServer:
    """Build the webhook server.

    Listening beyond loopback without a token is refused here rather than only in the CLI: this
    endpoint runs recovery playbooks, so an unauthenticated listener on a routable address would
    let anyone who can reach it trigger them.
    """
    if not token and host not in LOOPBACK:
        raise ValueError(f"refusing to listen on {host!r} without a token; bind to localhost or pass one")

    class Handler(BaseHTTPRequestHandler):
        server_version = "drpilot"

        def log_message(self, fmt, *args):  # quiet by default; the incident timeline is the log that matters
            pass

        def reply(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            if self.path == "/healthz":
                return self.reply(200, {"status": "ok"})
            if self.path == "/incidents":
                if not self.authorized():
                    return self.reply(401, {"error": "unauthorized"})
                incidents = [
                    {"id": i.id, "status": i.status, "title": i.title, "detected_at": i.detected_at, "postmortem": i.postmortem_path}
                    for i in responder.store.all()
                ]
                return self.reply(200, {"incidents": incidents})
            return self.reply(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path != "/alerts":
                return self.reply(404, {"error": "not found"})
            if not self.authorized():
                return self.reply(401, {"error": "unauthorized"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self.reply(400, {"error": "bad Content-Length"})
            if length <= 0 or length > MAX_BODY:
                return self.reply(413 if length > MAX_BODY else 400, {"error": "body missing or too large"})
            try:
                payload = json.loads(self.rfile.read(length))
                touched = responder.handle_payload(payload)
            except (ValueError, PayloadError) as err:
                return self.reply(400, {"error": str(err)})
            return self.reply(202, {"incidents": touched})

        def authorized(self) -> bool:
            if not token:
                return True
            supplied = self.headers.get("Authorization", "")
            return hmac.compare_digest(supplied.encode(), f"Bearer {token}".encode())

    return ThreadingHTTPServer((host, port), Handler)
