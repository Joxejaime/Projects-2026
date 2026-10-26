"""drpilot command line.

python -m drpilot check     [--playbooks DIR]                    validate playbooks
python -m drpilot serve     [--port 9095] [--state DIR] ...       Alertmanager webhook receiver
python -m drpilot watch     URL --alertname NAME --responder URL  probe a health endpoint, send alerts
python -m drpilot replay    PAYLOAD.json [...]                    feed recorded webhook payloads, offline
python -m drpilot render    INCIDENT.json                         re-render a postmortem from stored state
python -m drpilot drill     [--scenario S] [--out DIR]            break the demo service and recover it
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC
from pathlib import Path

from . import playbooks as pb
from .alertmanager import parse_payload
from .engine import Responder
from .model import Incident, IncidentStore, utcnow
from .render import render_postmortem

PROJECT = Path(__file__).resolve().parent.parent


def _labels(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise SystemExit(f"--label expects key=value, got {pair!r}")
        out[key] = value
    return out


def _publisher():
    repo, token = os.environ.get("DRPILOT_GITHUB_REPO"), os.environ.get("DRPILOT_GITHUB_TOKEN")
    if repo and token:
        from .publish import GitHubIssuePublisher

        return GitHubIssuePublisher(repo, token)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="drpilot", description="Automated recovery and postmortem drafts from alerts")
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="validate playbooks")
    c.add_argument("--playbooks", type=Path, default=PROJECT / "playbooks")

    s = sub.add_parser("serve", help="receive Alertmanager webhooks on POST /alerts")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=9095)
    s.add_argument("--playbooks", type=Path, default=PROJECT / "playbooks")
    s.add_argument("--state", type=Path, default=Path("state/incidents"))
    s.add_argument("--postmortems", type=Path, default=Path("postmortems"))

    w = sub.add_parser("watch", help="probe a health URL and send firing/resolved alerts to a responder")
    w.add_argument("url")
    w.add_argument("--alertname", required=True)
    w.add_argument("--responder", required=True, help="the responder's /alerts URL")
    w.add_argument("--label", action="append", default=[], help="extra alert label key=value (repeatable)")
    w.add_argument("--failures", type=int, default=3)
    w.add_argument("--successes", type=int, default=2)
    w.add_argument("--interval", type=float, default=5.0)

    r = sub.add_parser("replay", help="feed recorded Alertmanager payloads through the responder, offline")
    r.add_argument("payloads", nargs="+", type=Path)
    r.add_argument("--playbooks", type=Path, default=PROJECT / "playbooks")
    r.add_argument("--state", type=Path, default=Path("state/incidents"))
    r.add_argument("--postmortems", type=Path, default=Path("postmortems"))

    rr = sub.add_parser("render", help="re-render a postmortem from a stored incident (after editing facts)")
    rr.add_argument("incident", type=Path)

    d = sub.add_parser("drill", help="disaster-recovery drill against the demo notes service")
    d.add_argument("--out", type=Path, default=PROJECT / "postmortems" / "drills")
    d.add_argument("--scenario", choices=["corrupt-data", "corrupt-backups"], default="corrupt-data")
    d.add_argument("--timeout", type=float, default=60.0)

    args = parser.parse_args(argv)

    if args.cmd == "check":
        books = pb.load_dir(args.playbooks)
        for b in books:
            print(f"ok  {b.name}: matches {b.match}, {len(b.steps)} step(s), verify={'yes' if b.verify else 'no'}, objectives={b.objectives or '-'}")
        return 0

    if args.cmd == "serve":
        from .server import create_server

        token = os.environ.get("DRPILOT_TOKEN")
        if not token and args.host not in ("127.0.0.1", "localhost"):
            print("refusing to listen beyond localhost without DRPILOT_TOKEN set", file=sys.stderr)
            return 2
        responder = Responder(IncidentStore(args.state), pb.load_dir(args.playbooks), args.postmortems, publisher=_publisher())
        httpd = create_server(args.host, args.port, responder, token)
        print(f"drpilot listening on http://{args.host}:{httpd.server_address[1]}/alerts")
        httpd.serve_forever()
        return 0

    if args.cmd == "watch":
        from .watch import Watcher, post_to

        labels = _labels(args.label)
        sink = post_to(args.responder, os.environ.get("DRPILOT_TOKEN"))
        Watcher(args.url, args.alertname, sink, labels, failures=args.failures, successes=args.successes, interval=args.interval).run()
        return 0

    if args.cmd == "replay":
        # Replayed incidents happened in the past, so the payload's own timestamps are the clock.
        # Alertmanager does not record delivery time, so time to detect here is measured from when
        # the alert became active (it includes the rule's `for:` duration only in live mode).
        now = [utcnow()]
        responder = Responder(IncidentStore(args.state), pb.load_dir(args.playbooks), args.postmortems, clock=lambda: now[0], run_async=False)
        for path in args.payloads:
            payload = json.loads(path.read_text())
            times = [t for a in parse_payload(payload) for t in (a.starts_at, a.ends_at) if t]
            now[0] = max(times, default=utcnow())
            for incident_id in responder.handle_payload(payload):
                i = responder.store.get(incident_id)
                print(f"{path.name}: {i.id} {i.status}" + (f" -> {i.postmortem_path}" if i.postmortem_path else ""))
        return 0

    if args.cmd == "render":
        incident = Incident.from_dict(json.loads(args.incident.read_text()))
        sys.stdout.write(render_postmortem(incident, generated_at=utcnow().astimezone(UTC)))
        return 0

    if args.cmd == "drill":
        from .drill import run_drill

        result = run_drill(args.out, scenario=args.scenario, timeout=args.timeout)
        print("\n".join(result.summary))
        return 0 if result.passed else 1
    return 2
