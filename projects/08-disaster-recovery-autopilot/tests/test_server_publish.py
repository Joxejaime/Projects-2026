import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from drpilot.publish import GitHubIssuePublisher
from drpilot.server import create_server

from .helpers import OK_BOOK, T0, payload


@pytest.fixture
def webhook(make_responder):
    httpd = create_server("127.0.0.1", 0, make_responder(OK_BOOK), "hook-token")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def call(url, body=None, token=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def test_webhook_requires_token_and_accepts_alerts(webhook):
    assert call(webhook + "/alerts", payload("firing"))[0] == 401
    assert call(webhook + "/alerts", payload("firing"), token="wrong")[0] == 401
    status, body = call(webhook + "/alerts", payload("firing"), token="hook-token")
    assert status == 202 and len(body["incidents"]) == 1
    assert call(webhook + "/incidents", token="hook-token")[1]["incidents"][0]["status"] == "mitigated"


def test_bad_input_is_a_400_and_healthz_is_open(webhook):
    assert call(webhook + "/alerts", raw=b"{not json", token="hook-token")[0] == 400
    assert call(webhook + "/alerts", {"alerts": [{}]}, token="hook-token")[0] == 400
    assert call(webhook + "/healthz")[0] == 200


@pytest.fixture
def fake_github():
    received = {}

    class FakeGitHub(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):  # noqa: N802
            received.update(path=self.path, auth=self.headers.get("Authorization"), body=json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            out = json.dumps({"html_url": "https://github.example/issues/7"}).encode()
            self.send_response(201)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", received
    httpd.shutdown()
    httpd.server_close()


def test_publishes_the_draft_as_a_github_issue(make_responder, fake_github):
    url, received = fake_github
    r = make_responder(OK_BOOK, publisher=GitHubIssuePublisher("me/repo", "tok", api_url=url))
    [iid] = r.handle_payload(payload("firing"))
    r.handle_payload(payload("resolved", ends=T0))
    incident = r.store.get(iid)
    assert incident.published_url == "https://github.example/issues/7"
    assert (received["path"], received["auth"]) == ("/repos/me/repo/issues", "Bearer tok")
    assert "postmortem" in received["body"]["labels"]
    assert "Review thread: https://github.example/issues/7" in Path(incident.postmortem_path).read_text()


def test_publish_failure_never_loses_the_postmortem(make_responder):
    r = make_responder(OK_BOOK, publisher=GitHubIssuePublisher("me/repo", "tok", api_url="http://127.0.0.1:9"))
    [iid] = r.handle_payload(payload("firing"))
    r.handle_payload(payload("resolved", ends=T0))
    incident = r.store.get(iid)
    assert Path(incident.postmortem_path).exists()
    assert any("Publishing the draft failed" in e.message for e in incident.events)


def test_refuses_plain_http_to_remote_hosts():
    with pytest.raises(ValueError):
        GitHubIssuePublisher("me/repo", "tok", api_url="http://evil.example")


# --- the listener refuses to come up unauthenticated on a routable address -------------------


@pytest.mark.parametrize("host", ["0.0.0.0", "10.0.0.5", "example.internal"])
def test_create_server_refuses_tokenless_non_loopback(make_responder, host):
    """Without a token the endpoint would let anyone who can reach it run recovery playbooks."""
    with pytest.raises(ValueError, match="without a token"):
        create_server(host, 0, make_responder(OK_BOOK), None)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_create_server_allows_tokenless_loopback(make_responder, host):
    try:
        httpd = create_server(host, 0, make_responder(OK_BOOK), None)
    except OSError:
        pytest.skip(f"{host} is not bindable in this environment")
    httpd.server_close()


def test_create_server_allows_non_loopback_with_token(make_responder):
    httpd = create_server("0.0.0.0", 0, make_responder(OK_BOOK), "hook-token")  # noqa: S104 - the point of the test
    httpd.server_close()
