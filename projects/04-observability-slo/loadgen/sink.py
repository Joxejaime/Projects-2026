#!/usr/bin/env python3
"""Tiny Alertmanager webhook receiver: prints each alert as one JSON log line (stdlib only)."""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer


class Sink(BaseHTTPRequestHandler):
    def do_POST(self):
        length = min(int(self.headers.get("Content-Length", "0")), 1_000_000)
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return
        for alert in payload.get("alerts", []):
            print(
                json.dumps(
                    {
                        "receiver": self.path.strip("/") or "default",
                        "status": alert.get("status"),
                        "alertname": alert.get("labels", {}).get("alertname"),
                        "severity": alert.get("labels", {}).get("severity"),
                        "summary": alert.get("annotations", {}).get("summary"),
                        "runbook": alert.get("annotations", {}).get("runbook"),
                    }
                ),
                flush=True,
            )
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        return


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    print(f"webhook sink listening on {port}", flush=True)
    HTTPServer(("0.0.0.0", port), Sink).serve_forever()  # noqa: S104
