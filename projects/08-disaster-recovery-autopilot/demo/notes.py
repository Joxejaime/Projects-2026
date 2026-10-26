#!/usr/bin/env python3
"""A tiny stateful service to break: notes kept in memory and persisted to a JSON data file.

The data file carries a SHA-256 checksum of its contents. /healthz checks the file on disk, so a
corrupted or deleted data file (the "disaster") turns the service unhealthy. POST /admin/reload loads
the file from disk again, which is how a restore takes effect.

    GET  /healthz         200 {"status":"ok","notes":N} | 503 {"status":"unhealthy","reason":...}
    GET  /notes           the notes
    POST /notes           {"text": "..."} appends a note and persists it
    POST /admin/reload    reload from disk (admin token)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def checksum(notes: list) -> str:
    return hashlib.sha256(json.dumps(notes, sort_keys=True).encode()).hexdigest()


def read_store(path: Path) -> list:
    """Notes from a data file, or ValueError saying why the file cannot be trusted."""
    try:
        raw = json.loads(Path(path).read_text())
    except FileNotFoundError as err:
        raise ValueError("data file missing") from err
    except (OSError, json.JSONDecodeError) as err:
        raise ValueError(f"data file unreadable: {err.__class__.__name__}") from err
    if not isinstance(raw, dict) or not isinstance(raw.get("notes"), list):
        raise ValueError("data file has the wrong shape")
    if raw.get("checksum") != checksum(raw["notes"]):
        raise ValueError("data file checksum mismatch")
    return raw["notes"]


def write_store(path: Path, notes: list) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"notes": notes, "checksum": checksum(notes)}))
    os.replace(tmp, path)


class State:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()
        if not self.path.exists():
            write_store(self.path, [])
        self.notes = read_store(self.path)


def create_server(host: str, port: int, data: Path, admin_token: str) -> tuple[ThreadingHTTPServer, State]:
    state = State(data)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def reply(self, status: int, body: dict) -> None:
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):  # noqa: N802
            if self.path == "/healthz":
                try:
                    on_disk = read_store(state.path)
                except ValueError as err:
                    return self.reply(503, {"status": "unhealthy", "reason": str(err)})
                with state.lock:
                    if on_disk != state.notes:
                        return self.reply(503, {"status": "unhealthy", "reason": "memory and disk disagree; reload needed"})
                    return self.reply(200, {"status": "ok", "notes": len(state.notes)})
            if self.path == "/notes":
                with state.lock:
                    return self.reply(200, {"notes": list(state.notes)})
            return self.reply(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}") if 0 < length < 65536 else {}
            if self.path == "/notes":
                text = body.get("text") if isinstance(body, dict) else None
                if not isinstance(text, str) or not text:
                    return self.reply(400, {"error": "text required"})
                with state.lock:
                    state.notes.append(text)
                    write_store(state.path, state.notes)
                    return self.reply(201, {"notes": len(state.notes)})
            if self.path == "/admin/reload":
                if self.headers.get("Authorization") != f"Bearer {admin_token}":
                    return self.reply(401, {"error": "unauthorized"})
                try:
                    notes = read_store(state.path)
                except ValueError as err:
                    return self.reply(409, {"error": f"cannot reload: {err}"})
                with state.lock:
                    state.notes = notes
                return self.reply(200, {"reloaded": len(notes)})
            return self.reply(404, {"error": "not found"})

    return ThreadingHTTPServer((host, port), Handler), state


def main() -> int:
    data = Path(os.environ.get("NOTES_DATA", "notes-data.json"))
    token = os.environ.get("NOTES_ADMIN_TOKEN")
    if not token:
        print("NOTES_ADMIN_TOKEN must be set", file=sys.stderr)
        return 2
    httpd, _ = create_server(os.environ.get("NOTES_HOST", "127.0.0.1"), int(os.environ.get("PORT", "8090")), data, token)
    print(f"notes service on {httpd.server_address}, data file {data}")
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
