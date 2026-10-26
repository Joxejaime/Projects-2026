"""The infrastructure and Kubernetes playbooks, with stub `terraform` and `kubectl` binaries.

This checks what drpilot would run (argument order, the reuse of project 02's directory, which environments are
matched, the escalation for prod). It does NOT prove that anything works against AWS or a cluster.
"""

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from drpilot import playbooks as pb
from drpilot.engine import Responder
from drpilot.model import IncidentStore

from .helpers import T0, payload

ROOT = Path(__file__).resolve().parent.parent

STUB = """#!/usr/bin/env python3
import os, sys
with open(os.environ["STUB_LOG"], "a") as log:
    log.write(os.path.basename(sys.argv[0]) + " " + " ".join(sys.argv[1:]) + "\\n")
"""


@pytest.fixture
def stubs(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("terraform", "kubectl"):
        (bin_dir / name).write_text(STUB)
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "calls.log"
    monkeypatch.setenv("STUB_LOG", str(log))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


@pytest.fixture
def healthy_service():
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.end_headers()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def responder(tmp_path, clock):
    return Responder(IncidentStore(tmp_path / "state"), pb.load_dir(ROOT / "playbooks"), tmp_path / "pm", clock=clock, run_async=False, sleep=lambda _s: None)


def target_down(environment):
    return payload("firing", alertname="TargetDown", service="release-tracker", environment=environment)


def test_dev_target_down_reapplies_project_02_with_remote_state(responder, stubs, healthy_service, monkeypatch):
    monkeypatch.setenv("TF_STATE_BUCKET", "my-state")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("SERVICE_URL", healthy_service)
    [iid] = responder.handle_payload(target_down("dev"))
    incident = responder.store.get(iid)
    assert incident.recovery_state == "succeeded" and incident.playbook == "infra-reapply-dev"
    init, apply = stubs.read_text().splitlines()
    chdir = next(a for a in init.split() if a.startswith("-chdir="))
    assert Path(chdir.removeprefix("-chdir=")).resolve() == (ROOT.parent / "02-aws-terraform-platform" / "envs" / "dev").resolve()
    assert (Path(chdir.removeprefix("-chdir=")) / "main.tf").is_file(), "the playbook must point at project 02's real dev environment"
    assert "init" in init and "-backend-config=bucket=my-state" in init and "-backend-config=use_lockfile=true" in init
    assert "-backend-config=key=release-tracker/dev/terraform.tfstate" in init
    assert "apply" in apply and "-auto-approve" in apply and "-lock-timeout=5m" in apply


def test_prod_is_never_applied_by_automation(responder, stubs):
    [iid] = responder.handle_payload(target_down("prod"))
    incident = responder.store.get(iid)
    assert incident.recovery_state == "no_playbook" and incident.status == "escalated"
    assert not stubs.exists(), "terraform must not have been invoked for prod"


def test_missing_environment_variable_fails_the_step_instead_of_guessing(responder, stubs, monkeypatch):
    monkeypatch.delenv("TF_STATE_BUCKET", raising=False)
    [iid] = responder.handle_payload(target_down("dev"))
    incident = responder.store.get(iid)
    assert incident.recovery_state == "failed"
    assert "TF_STATE_BUCKET is not set" in incident.attempts[0].steps[0].detail
    assert not stubs.exists()


def test_crashloop_rolls_back_the_deployment_from_project_03(responder, stubs, monkeypatch):
    monkeypatch.setenv("K8S_NAMESPACE", "release-tracker-dev")
    [iid] = responder.handle_payload(payload("firing", alertname="CrashLooping", service="release-tracker", environment="dev"))
    assert responder.store.get(iid).recovery_state == "succeeded"
    undo, status = stubs.read_text().splitlines()
    assert undo == "kubectl --namespace release-tracker-dev rollout undo deployment/release-tracker"
    assert status.startswith("kubectl --namespace release-tracker-dev rollout status deployment/release-tracker")
    deployment = (ROOT.parent / "03-k8s-gitops" / "k8s" / "base" / "deployment.yaml").read_text()
    assert "name: release-tracker" in deployment, "the rolled-back Deployment must exist in project 03"
    assert T0  # payload helper start time is irrelevant here
