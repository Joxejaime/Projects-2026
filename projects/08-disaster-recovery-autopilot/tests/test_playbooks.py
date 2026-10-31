import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import pytest

from drpilot import playbooks as pb

from .helpers import FAIL_BOOK, OK_BOOK, write_playbook

BOOK = "name: x\nmatch: {{alertname: A}}\nsteps:\n  - name: s\n    run: [a]\n{extra}"


@pytest.mark.parametrize(
    "text",
    [
        "name: x\nmatch: {alertname: A}\nsteps: []\n",
        "name: x\nmatch: {alertname: A}\nsteps:\n  - name: s\n    run: 'rm -rf /'\n",
        "name: x\nmatch: {alertname: A}\nsteps:\n  - name: s\n    run: [a]\n    http: {url: http://x}\n",
        "name: x\nmatch: {service: a}\nsteps:\n  - name: s\n    run: [a]\n",
        "name: x\nmatch: {alertname: A}\nobjectives: {mttr: 1}\nsteps:\n  - name: s\n    run: [a]\n",
        "name: x\nmatch: {alertname: A}\nmax_attempts: 50\nsteps:\n  - name: s\n    run: [a]\n",
        BOOK.format(extra="verify: {successes: 3}\n"),
        BOOK.format(extra="verify:\n  checks:\n    - name: c\n      run: 'not a list'\n"),
        BOOK.format(extra="verify: {url: http://x, bogus: 1}\n"),
    ],
    ids=[
        "no steps",
        "shell string",
        "both kinds",
        "no alertname",
        "bad objective",
        "too many attempts",
        "verify without url or checks",
        "check as string",
        "unknown verify key",
    ],
)
def test_rejects_invalid_playbooks(tmp_path, text):
    with pytest.raises(pb.PlaybookError):
        pb.load(write_playbook(tmp_path, "bad", text))


def test_shipped_playbooks_are_valid(project_root):
    names = {b.name for b in pb.load_dir(project_root / "playbooks")}
    assert {"orders-restore-from-snapshot", "backup-refresh", "infra-reapply-dev", "k8s-rollback-crashloop"} <= names


def test_most_specific_playbook_wins(tmp_path):
    generic = pb.load(write_playbook(tmp_path, "g", BOOK.format(extra="").replace("name: x", "name: g")))
    specific = pb.load(
        write_playbook(tmp_path, "s", BOOK.format(extra="").replace("name: x", "name: s").replace("{alertname: A}", "{alertname: A, service: db}"))
    )
    assert pb.select([generic, specific], {"alertname": "A", "service": "db"}).name == "s"
    assert pb.select([generic, specific], {"alertname": "A", "service": "web"}).name == "g"
    assert pb.select([generic, specific], {"alertname": "B"}) is None


def test_label_placeholders_refuse_unsafe_values(tmp_path):
    book = pb.load(write_playbook(tmp_path, "l", 'name: l\nmatch: {alertname: A}\nsteps:\n  - name: s\n    run: ["echo", "{label.pod}"]\n'))
    assert pb.render("{label.pod}", book, {"pod": "api-7d9f/x"}) == "api-7d9f/x"
    for evil in ["a; rm -rf /", "$(id)", "--config=/etc/passwd x", "", "-v", "--help", "-rf"]:
        with pytest.raises(pb.PlaybookError):
            pb.render("{label.pod}", book, {"pod": evil})
    with pytest.raises(pb.PlaybookError):
        pb.render("{secret}", book, {})


def test_command_step_reports_facts_and_failures(tmp_path):
    book = pb.load(write_playbook(tmp_path, "ok", OK_BOOK))
    result, facts = pb.run_step(book.steps[0], book, {})
    assert result.ok and facts == {"freed_mb": 512}
    bad = pb.load(write_playbook(tmp_path, "bad", FAIL_BOOK))
    result, _ = pb.run_step(bad.steps[0], bad, {})
    assert not result.ok and result.detail == "exit 3"


def test_step_timeout_is_a_failure_not_a_hang(tmp_path):
    text = 'name: s\nmatch: {alertname: A}\nsteps:\n  - name: slow\n    timeout: 0.5\n    run: ["{python}", "-c", "import time; time.sleep(5)"]\n'
    book = pb.load(write_playbook(tmp_path, "slow", text))
    result, _ = pb.run_step(book.steps[0], book, {})
    assert not result.ok and "timed out" in result.detail


def test_http_step_sends_bearer_token_from_environment(tmp_path):
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
    url = f"http://127.0.0.1:{httpd.server_address[1]}/reload"
    text = f"name: h\nmatch: {{alertname: A}}\nsteps:\n  - name: call\n    http: {{method: POST, url: '{url}', bearer_token_env: DRPILOT_TEST_TOKEN}}\n"
    book = pb.load(write_playbook(tmp_path, "h", text))
    try:
        with mock.patch.dict(os.environ, {"DRPILOT_TEST_TOKEN": "s3cret"}):
            result, _ = pb.run_step(book.steps[0], book, {})
        assert result.ok, result.detail
        assert seen["auth"] == "Bearer s3cret"
        with mock.patch.dict(os.environ, {}, clear=True):
            result, _ = pb.run_step(book.steps[0], book, {})
        assert not result.ok
    finally:
        httpd.shutdown()
        httpd.server_close()


VERIFY_BOOK = """
name: v
match: {{alertname: A}}
steps:
  - name: noop
    run: ["{{python}}", "-c", "pass"]
verify:
  checks:
    - name: first
      run: ["{{python}}", "-c", "import json; print(json.dumps({{'facts': {{'rows': 7}}}}))"]
    - name: second
      run: ["{{python}}", "-c", "import sys; sys.exit({code})"]
    - name: never reached
      run: ["{{python}}", "-c", "pass"]
"""


def test_verify_runs_data_checks_in_order_and_stops_at_the_first_failure(tmp_path):
    book = pb.load(write_playbook(tmp_path, "v", VERIFY_BOOK.format(code=4)))
    results, facts = pb.verify(book, {})
    assert [(r.name, r.ok) for r in results] == [("first", True), ("second", False)]
    assert facts == {"rows": 7}
    book = pb.load(write_playbook(tmp_path, "v2", VERIFY_BOOK.format(code=0).replace("name: v\n", "name: v2\n")))
    results, _ = pb.verify(book, {})
    assert all(r.ok for r in results) and len(results) == 3


def test_verify_needs_consecutive_healthy_probes_before_checks_run(tmp_path):
    answers = iter([200, 500, 200, 200, 200])
    text = "name: p\nmatch: {alertname: A}\nsteps:\n  - name: s\n    run: [a]\nverify:\n  url: http://127.0.0.1:9/healthz\n  successes: 3\n  interval_seconds: 0\n  timeout_seconds: 5\n  checks:\n    - name: after\n      run: ['{python}', '-c', 'pass']\n"
    book = pb.load(write_playbook(tmp_path, "p", text))
    with mock.patch.object(pb, "_fetch", lambda req, timeout: (next(answers), "")):
        results, _ = pb.verify(book, {}, sleep=lambda _s: None)
    assert [r.name for r in results] == ["Health probes", "after"]
    assert results[0].detail == "3 consecutive healthy probes (5 total)"


def test_failed_probes_skip_the_data_checks(tmp_path):
    text = "name: p\nmatch: {alertname: A}\nsteps:\n  - name: s\n    run: [a]\nverify:\n  url: http://127.0.0.1:9/healthz\n  interval_seconds: 0\n  timeout_seconds: 0.2\n  checks:\n    - name: after\n      run: ['{python}', '-c', 'pass']\n"
    book = pb.load(write_playbook(tmp_path, "p", text))
    with mock.patch.object(pb, "_fetch", lambda req, timeout: (503, "")):
        results, _ = pb.verify(book, {}, sleep=lambda _s: None)
    assert [(r.name, r.ok) for r in results] == [("Health probes", False)]
