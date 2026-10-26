import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "demo"))
import backup  # noqa: E402
import notes  # noqa: E402

from drpilot import playbooks as pb  # noqa: E402
from drpilot.alertmanager import PayloadError, parse_payload  # noqa: E402
from drpilot.engine import Responder, synthetic_alert  # noqa: E402
from drpilot.model import Incident, IncidentStore, parse_time  # noqa: E402
from drpilot.publish import GitHubIssuePublisher  # noqa: E402
from drpilot.render import duration, render_postmortem, suggested_actions  # noqa: E402
from drpilot.server import create_server  # noqa: E402
from drpilot.watch import Watcher  # noqa: E402

T0 = datetime(2026, 10, 26, 10, 0, tzinfo=UTC)


class Clock:
    def __init__(self, start=T0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def payload(status, alertname="DiskFull", fingerprint="fp1", starts=T0, ends=None, **labels):
    labels = {"alertname": alertname, "service": "api", "severity": "page", **labels}
    return {
        "version": "4",
        "status": status,
        "alerts": [
            {
                "status": status,
                "labels": labels,
                "annotations": {"summary": f"{alertname} on api"},
                "startsAt": starts.isoformat().replace("+00:00", "Z"),
                "endsAt": ends.isoformat().replace("+00:00", "Z") if ends else "0001-01-01T00:00:00Z",
                "fingerprint": fingerprint,
            }
        ],
    }


def write_playbook(directory, name, text):
    path = Path(directory) / f"{name}.yaml"
    path.write_text(text)
    return path


OK_BOOK = """
name: disk-cleanup
match: {alertname: DiskFull}
max_attempts: 2
objectives: {rto_seconds: 300}
steps:
  - name: Clean temp
    run: ["{python}", "-c", "import json; print('cleaned'); print(json.dumps({'facts': {'freed_mb': 512}}))"]
"""

FAIL_BOOK = """
name: always-fails
match: {alertname: DiskFull}
max_attempts: 2
steps:
  - name: Broken step
    run: ["{python}", "-c", "import sys; sys.exit(3)"]
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.clock = Clock()

    def responder(self, *books):
        paths = [write_playbook(self.tmp, f"book{i}", text) for i, text in enumerate(books)]
        loaded = [pb.load(p) for p in paths]
        return Responder(IncidentStore(self.tmp / "state"), loaded, self.tmp / "pm", clock=self.clock, run_async=False)


class TimeAndPayloadTests(unittest.TestCase):
    def test_parses_alertmanager_nanosecond_timestamps_and_zero_time(self):
        self.assertEqual(parse_time("2026-10-26T10:00:00.123456789Z"), datetime(2026, 10, 26, 10, 0, 0, 123456, tzinfo=UTC))
        self.assertIsNone(parse_time("0001-01-01T00:00:00Z"))
        self.assertIsNone(parse_time(None))

    def test_parse_payload(self):
        alerts = parse_payload(payload("firing"))
        self.assertEqual(alerts[0].incident_key, "DiskFull|api")
        self.assertIsNone(alerts[0].ends_at)

    def test_rejects_malformed_payloads(self):
        for bad in [[], {"alerts": "x"}, {"alerts": [{"status": "weird", "labels": {"alertname": "a"}}]}, {"alerts": [{"status": "firing", "labels": {}}]}]:
            with self.assertRaises(PayloadError):
                parse_payload(bad)

    def test_duration_formatting(self):
        self.assertEqual(duration(1.24), "1.2s")
        self.assertEqual(duration(125), "2m 05s")
        self.assertEqual(duration(3725), "1h 02m 05s")
        self.assertEqual(duration(None), "n/a")


class PlaybookTests(Fixture):
    def test_rejects_invalid_playbooks(self):
        cases = {
            "no steps": "name: x\nmatch: {alertname: A}\nsteps: []\n",
            "shell string": "name: x\nmatch: {alertname: A}\nsteps:\n  - name: s\n    run: 'rm -rf /'\n",
            "both kinds": "name: x\nmatch: {alertname: A}\nsteps:\n  - name: s\n    run: [a]\n    http: {url: http://x}\n",
            "no alertname": "name: x\nmatch: {service: a}\nsteps:\n  - name: s\n    run: [a]\n",
            "bad objective": "name: x\nmatch: {alertname: A}\nobjectives: {mttr: 1}\nsteps:\n  - name: s\n    run: [a]\n",
            "too many attempts": "name: x\nmatch: {alertname: A}\nmax_attempts: 50\nsteps:\n  - name: s\n    run: [a]\n",
        }
        for label, text in cases.items():
            with self.subTest(label), self.assertRaises(pb.PlaybookError):
                pb.load(write_playbook(self.tmp, "bad", text))

    def test_shipped_playbooks_are_valid(self):
        books = pb.load_dir(ROOT / "playbooks")
        self.assertIn("notes-restore-from-snapshot", [b.name for b in books])

    def test_most_specific_playbook_wins(self):
        generic = pb.load(write_playbook(self.tmp, "g", "name: g\nmatch: {alertname: A}\nsteps:\n  - name: s\n    run: [a]\n"))
        specific = pb.load(write_playbook(self.tmp, "s", "name: s\nmatch: {alertname: A, service: db}\nsteps:\n  - name: s\n    run: [a]\n"))
        self.assertEqual(pb.select([generic, specific], {"alertname": "A", "service": "db"}).name, "s")
        self.assertEqual(pb.select([generic, specific], {"alertname": "A", "service": "web"}).name, "g")
        self.assertIsNone(pb.select([generic, specific], {"alertname": "B"}))

    def test_label_placeholders_refuse_unsafe_values(self):
        book = pb.load(write_playbook(self.tmp, "l", 'name: l\nmatch: {alertname: A}\nsteps:\n  - name: s\n    run: ["echo", "{label.pod}"]\n'))
        self.assertEqual(pb.render("{label.pod}", book, {"pod": "api-7d9f/x"}), "api-7d9f/x")
        for evil in ["a; rm -rf /", "$(id)", "--config=/etc/passwd x", ""]:
            with self.subTest(evil), self.assertRaises(pb.PlaybookError):
                pb.render("{label.pod}", book, {"pod": evil})
        with self.assertRaises(pb.PlaybookError):
            pb.render("{secret}", book, {})

    def test_command_step_reports_facts_and_failures(self):
        book = pb.load(write_playbook(self.tmp, "ok", OK_BOOK))
        result, facts = pb.run_step(book.steps[0], book, {})
        self.assertTrue(result.ok)
        self.assertEqual(facts, {"freed_mb": 512})
        bad = pb.load(write_playbook(self.tmp, "bad", FAIL_BOOK))
        result, _ = pb.run_step(bad.steps[0], bad, {})
        self.assertFalse(result.ok)
        self.assertEqual(result.detail, "exit 3")

    def test_step_timeout_is_a_failure_not_a_hang(self):
        book = pb.load(
            write_playbook(
                self.tmp,
                "slow",
                'name: s\nmatch: {alertname: A}\nsteps:\n  - name: slow\n    timeout: 0.5\n    run: ["{python}", "-c", "import time; time.sleep(5)"]\n',
            )
        )
        result, _ = pb.run_step(book.steps[0], book, {})
        self.assertFalse(result.ok)
        self.assertIn("timed out", result.detail)

    def test_http_step_sends_bearer_token_from_environment(self):
        seen = {}

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):  # noqa: N802
                seen["auth"] = self.headers.get("Authorization")
                self.send_response(200)
                self.end_headers()

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        url = f"http://127.0.0.1:{httpd.server_address[1]}/reload"
        text = f"name: h\nmatch: {{alertname: A}}\nsteps:\n  - name: call\n    http: {{method: POST, url: '{url}', bearer_token_env: DRPILOT_TEST_TOKEN}}\n"
        book = pb.load(write_playbook(self.tmp, "h", text))
        with mock.patch.dict(os.environ, {"DRPILOT_TEST_TOKEN": "s3cret"}):
            result, _ = pb.run_step(book.steps[0], book, {})
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(seen["auth"], "Bearer s3cret")
        with mock.patch.dict(os.environ, {}, clear=True):
            result, _ = pb.run_step(book.steps[0], book, {})
        self.assertFalse(result.ok)


class ResponderTests(Fixture):
    def test_full_lifecycle_recovers_and_writes_postmortem(self):
        r = self.responder(OK_BOOK)
        self.clock.advance(90)  # alert arrives 90 s after the condition started
        [iid] = r.handle_payload(payload("firing"))
        incident = r.store.get(iid)
        self.assertEqual(incident.recovery_state, "succeeded")
        self.assertEqual(incident.status, "mitigated")
        self.assertEqual(incident.facts, {"freed_mb": 512})
        self.assertFalse(incident.finalized)

        self.clock.advance(60)
        r.handle_payload(payload("resolved", ends=self.clock.now))
        incident = r.store.get(iid)
        self.assertTrue(incident.finalized)
        text = Path(incident.postmortem_path).read_text()
        self.assertIn("Status: DRAFT, generated automatically", text)
        self.assertIn("| Time to detect (impact start to alert) | 1m 30s |", text)
        self.assertIn("| Total impact (impact start to alert resolved) | 2m 30s |", text)
        self.assertIn("**met**", text)
        self.assertIn("`freed_mb` | 512", text)
        self.assertIn("**TODO (human):** the automation knows the symptom", text)

    def test_repeat_notifications_do_not_rerun_recovery(self):
        r = self.responder(OK_BOOK)
        [a] = r.handle_payload(payload("firing"))
        [b] = r.handle_payload(payload("firing"))
        self.assertEqual(a, b)
        self.assertEqual(len(r.store.get(a).attempts), 1)
        self.assertEqual(len(r.store.all()), 1)

    def test_no_playbook_escalates_and_suggests_writing_one(self):
        r = self.responder(OK_BOOK)
        [iid] = r.handle_payload(payload("firing", alertname="CertExpiring"))
        self.assertEqual(r.store.get(iid).status, "escalated")
        r.handle_payload(payload("resolved", alertname="CertExpiring", ends=T0))
        text = Path(r.store.get(iid).postmortem_path).read_text()
        self.assertIn("no recovery playbook matched", text)
        self.assertIn("Write and drill a recovery playbook for `CertExpiring`", text)

    def test_failing_playbook_retries_then_escalates(self):
        r = self.responder(FAIL_BOOK)
        [iid] = r.handle_payload(payload("firing"))
        incident = r.store.get(iid)
        self.assertEqual(incident.recovery_state, "failed")
        self.assertEqual(len(incident.attempts), 2)
        self.assertTrue(any("gave up after 2 attempt(s)" in e.message for e in incident.events))
        actions = [a for a, _ in suggested_actions(incident)]
        self.assertTrue(any("Automation 'always-fails' failed" in a and "exit 3" in a for a in actions))

    def test_incident_stays_open_until_every_alert_in_it_resolves(self):
        r = self.responder(OK_BOOK)
        [iid] = r.handle_payload(payload("firing", fingerprint="a"))
        r.handle_payload(payload("firing", fingerprint="b"))
        r.handle_payload(payload("resolved", fingerprint="a", ends=T0))
        self.assertFalse(r.store.get(iid).finalized)
        r.handle_payload(payload("resolved", fingerprint="b", ends=T0))
        self.assertTrue(r.store.get(iid).finalized)

    def test_resolution_for_unknown_alert_is_ignored(self):
        r = self.responder(OK_BOOK)
        self.assertEqual(r.handle_payload(payload("resolved", ends=T0)), [])

    def test_open_incidents_survive_a_restart(self):
        r = self.responder(FAIL_BOOK)
        [iid] = r.handle_payload(payload("firing"))
        restarted = Responder(IncidentStore(self.tmp / "state"), r.books, self.tmp / "pm", clock=self.clock, run_async=False)
        self.assertEqual(restarted.handle_payload(payload("resolved", ends=T0)), [iid])
        self.assertTrue(restarted.store.get(iid).finalized)

    def test_postmortem_waits_for_running_recovery(self):
        gate = threading.Event()
        r = self.responder(OK_BOOK)
        r.run_async = True
        original = pb.run_step

        def slow_step(*args, **kwargs):
            gate.wait(5)
            return original(*args, **kwargs)

        with mock.patch.object(pb, "run_step", slow_step):
            [iid] = r.handle_payload(payload("firing"))
            r.handle_payload(payload("resolved", ends=T0))
            self.assertFalse(r.store.get(iid).finalized)  # recovery still running: no postmortem yet
            gate.set()
            incident = r.wait_closed(iid, timeout=10)
        self.assertTrue(incident.finalized)
        self.assertEqual(incident.recovery_state, "succeeded")

    def test_incident_round_trips_through_json(self):
        r = self.responder(OK_BOOK)
        [iid] = r.handle_payload(payload("firing"))
        incident = r.store.get(iid)
        self.assertEqual(Incident.from_dict(json.loads(json.dumps(incident.to_dict()))), incident)

    def test_rendered_tables_escape_pipes(self):
        r = self.responder(OK_BOOK)
        [iid] = r.handle_payload(payload("firing", note="a|b"))
        text = render_postmortem(r.store.get(iid), T0)
        self.assertIn("a\\|b", text)


class PublisherTests(Fixture):
    def test_publishes_the_draft_as_a_github_issue(self):
        received = {}

        class FakeGitHub(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):  # noqa: N802
                received["path"] = self.path
                received["auth"] = self.headers.get("Authorization")
                received["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                out = json.dumps({"html_url": "https://github.example/issues/7"}).encode()
                self.send_response(201)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        r = self.responder(OK_BOOK)
        r.publisher = GitHubIssuePublisher("me/repo", "tok", api_url=f"http://127.0.0.1:{httpd.server_address[1]}")
        [iid] = r.handle_payload(payload("firing"))
        r.handle_payload(payload("resolved", ends=T0))
        incident = r.store.get(iid)
        self.assertEqual(incident.published_url, "https://github.example/issues/7")
        self.assertEqual(received["path"], "/repos/me/repo/issues")
        self.assertEqual(received["auth"], "Bearer tok")
        self.assertIn("postmortem", received["body"]["labels"])
        self.assertIn("Review thread: https://github.example/issues/7", Path(incident.postmortem_path).read_text())

    def test_publish_failure_never_loses_the_postmortem(self):
        r = self.responder(OK_BOOK)
        r.publisher = GitHubIssuePublisher("me/repo", "tok", api_url="http://127.0.0.1:9")
        [iid] = r.handle_payload(payload("firing"))
        r.handle_payload(payload("resolved", ends=T0))
        incident = r.store.get(iid)
        self.assertTrue(Path(incident.postmortem_path).exists())
        self.assertTrue(any("Publishing the draft failed" in e.message for e in incident.events))

    def test_refuses_plain_http_to_remote_hosts(self):
        with self.assertRaises(ValueError):
            GitHubIssuePublisher("me/repo", "tok", api_url="http://evil.example")


class ServerTests(Fixture):
    def start(self, token="hook-token"):
        httpd = create_server("127.0.0.1", 0, self.responder(OK_BOOK), token)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(self, url, body=None, token=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def test_webhook_requires_token_and_accepts_alerts(self):
        base = self.start()
        self.assertEqual(self.call(base + "/alerts", payload("firing"))[0], 401)
        self.assertEqual(self.call(base + "/alerts", payload("firing"), token="wrong")[0], 401)
        status, body = self.call(base + "/alerts", payload("firing"), token="hook-token")
        self.assertEqual(status, 202)
        self.assertEqual(len(body["incidents"]), 1)
        status, body = self.call(base + "/incidents", token="hook-token")
        self.assertEqual(body["incidents"][0]["status"], "mitigated")

    def test_bad_input_is_a_400(self):
        base = self.start()
        self.assertEqual(self.call(base + "/alerts", raw=b"{not json", token="hook-token")[0], 400)
        self.assertEqual(self.call(base + "/alerts", {"alerts": [{}]}, token="hook-token")[0], 400)
        self.assertEqual(self.call(base + "/healthz")[0], 200)


class WatcherTests(unittest.TestCase):
    def test_fires_after_n_failures_dated_from_the_first_and_resolves_after_m_successes(self):
        clock, sent, health = Clock(), [], iter([True, False, False, False, False, True, True, True])
        w = Watcher("http://x/healthz", "Down", sent.append, {"service": "api"}, failures=3, successes=2, clock=clock, check=lambda _u: next(health))
        for _ in range(8):
            w.tick()
            clock.advance(10)
        self.assertEqual([p["status"] for p in sent], ["firing", "resolved"])
        self.assertEqual(sent[0]["alerts"][0]["startsAt"], "2026-10-26T10:00:10.000Z")  # first failed probe
        self.assertEqual(sent[1]["alerts"][0]["endsAt"], "2026-10-26T10:00:50.000Z")  # first healthy probe
        self.assertEqual(parse_payload(sent[0])[0].incident_key, "Down|api")

    def test_rejects_non_http_urls(self):
        with self.assertRaises(ValueError):
            Watcher("file:///etc/passwd", "X", print)

    def test_synthetic_alert_round_trips(self):
        alert = parse_payload(synthetic_alert("A", "firing", {"service": "s"}, {}, T0))[0]
        self.assertEqual((alert.name, alert.service, alert.starts_at), ("A", "s", T0))


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data, self.dir = self.tmp / "notes.json", self.tmp / "backups"

    def test_snapshot_and_restore(self):
        notes.write_store(self.data, ["a", "b"])
        backup.snapshot(self.data, self.dir)
        self.data.write_text("garbage")
        facts = backup.restore(self.data, self.dir)
        self.assertEqual(notes.read_store(self.data), ["a", "b"])
        self.assertEqual(facts["notes_restored"], 2)
        self.assertGreaterEqual(facts["snapshot_age_seconds"], 0)

    def test_restore_skips_corrupt_snapshots(self):
        notes.write_store(self.data, ["good"])
        backup.snapshot(self.data, self.dir)
        notes.write_store(self.data, ["newer"])
        newest = backup.snapshot(self.data, self.dir)
        newest.write_text("bit rot")
        facts = backup.restore(self.data, self.dir)
        self.assertEqual(notes.read_store(self.data), ["good"])
        self.assertEqual(facts["corrupt_snapshots_skipped"], 1)

    def test_refuses_to_snapshot_a_broken_file_or_restore_nothing(self):
        self.data.write_text("garbage")
        with self.assertRaises(ValueError):
            backup.snapshot(self.data, self.dir)
        self.dir.mkdir()
        with self.assertRaises(ValueError):
            backup.restore(self.data, self.dir)

    def test_health_detects_corruption(self):
        httpd, _ = notes.create_server("127.0.0.1", 0, self.data, "t")
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        url = f"http://127.0.0.1:{httpd.server_address[1]}/healthz"
        with urllib.request.urlopen(url, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
        self.data.write_text("{}")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url, timeout=5)
        self.assertEqual(ctx.exception.code, 503)


class DrillTests(unittest.TestCase):
    def test_end_to_end_disaster_recovery_drill(self):
        from drpilot.drill import run_drill

        out = Path(tempfile.mkdtemp())
        result = run_drill(out, timeout=30, interval=0.1)
        self.assertTrue(result.passed, "\n".join(result.summary))
        text = result.postmortem.read_text()
        self.assertIn("RTO (impact start to service restored)", text)
        self.assertIn("`snapshot_age_seconds`", text)
        self.assertIn("Verification passed", text)

    def test_drill_with_corrupt_backups_escalates_instead_of_restoring_garbage(self):
        from drpilot.drill import run_drill

        result = run_drill(Path(tempfile.mkdtemp()), scenario="corrupt-backups", timeout=30, interval=0.1)
        self.assertTrue(result.passed, "\n".join(result.summary))
        text = result.postmortem.read_text()
        self.assertIn("could not recover the service, so a human was paged", text)
        self.assertIn("no snapshot verified", text)
        self.assertIn("Automation gave up after 2 attempt(s)", text)
        self.assertIn("test that backups restore on a schedule", text)


if __name__ == "__main__":
    unittest.main()
