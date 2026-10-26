import json
import threading
from pathlib import Path
from unittest import mock

from drpilot import playbooks as pb
from drpilot.engine import Responder
from drpilot.model import Incident, IncidentStore
from drpilot.render import render_postmortem, suggested_actions

from .helpers import FAIL_BOOK, OK_BOOK, T0, payload


def test_full_lifecycle_recovers_and_writes_postmortem(make_responder, clock):
    r = make_responder(OK_BOOK)
    clock.advance(90)  # the alert arrives 90 s after the condition started
    [iid] = r.handle_payload(payload("firing"))
    incident = r.store.get(iid)
    assert (incident.recovery_state, incident.status, incident.facts) == ("succeeded", "mitigated", {"freed_mb": 512})
    assert not incident.finalized

    clock.advance(60)
    r.handle_payload(payload("resolved", ends=clock.now))
    incident = r.store.get(iid)
    assert incident.finalized
    text = Path(incident.postmortem_path).read_text()
    assert "Status: DRAFT, generated automatically" in text
    assert "| Time to detect (impact start to alert) | 1m 30s |" in text
    assert "| Total impact (impact start to alert resolved) | 2m 30s |" in text
    assert "**met**" in text
    assert "`freed_mb` | 512" in text
    assert "**TODO (human):** the automation knows the symptom" in text


def test_repeat_notifications_do_not_rerun_recovery(make_responder):
    r = make_responder(OK_BOOK)
    [a] = r.handle_payload(payload("firing"))
    [b] = r.handle_payload(payload("firing"))
    assert a == b
    assert len(r.store.get(a).attempts) == 1
    assert len(r.store.all()) == 1


def test_no_playbook_escalates_and_suggests_writing_one(make_responder):
    r = make_responder(OK_BOOK)
    [iid] = r.handle_payload(payload("firing", alertname="CertExpiring"))
    assert r.store.get(iid).status == "escalated"
    r.handle_payload(payload("resolved", alertname="CertExpiring", ends=T0))
    text = Path(r.store.get(iid).postmortem_path).read_text()
    assert "no recovery playbook matched" in text
    assert "Write and drill a recovery playbook for `CertExpiring`" in text


def test_failing_playbook_retries_then_escalates(make_responder):
    r = make_responder(FAIL_BOOK)
    [iid] = r.handle_payload(payload("firing"))
    incident = r.store.get(iid)
    assert incident.recovery_state == "failed" and len(incident.attempts) == 2
    assert any("gave up after 2 attempt(s)" in e.message for e in incident.events)
    actions = [a for a, _ in suggested_actions(incident)]
    assert any("Automation 'always-fails' failed" in a and "exit 3" in a for a in actions)


def test_incident_stays_open_until_every_alert_in_it_resolves(make_responder):
    r = make_responder(OK_BOOK)
    [iid] = r.handle_payload(payload("firing", fingerprint="a"))
    r.handle_payload(payload("firing", fingerprint="b"))
    r.handle_payload(payload("resolved", fingerprint="a", ends=T0))
    assert not r.store.get(iid).finalized
    r.handle_payload(payload("resolved", fingerprint="b", ends=T0))
    assert r.store.get(iid).finalized


def test_resolution_for_unknown_alert_is_ignored(make_responder):
    assert make_responder(OK_BOOK).handle_payload(payload("resolved", ends=T0)) == []


def test_open_incidents_survive_a_restart(make_responder, tmp_path, clock):
    r = make_responder(FAIL_BOOK)
    [iid] = r.handle_payload(payload("firing"))
    restarted = Responder(IncidentStore(tmp_path / "state"), r.books, tmp_path / "pm", clock=clock, run_async=False)
    assert restarted.handle_payload(payload("resolved", ends=T0)) == [iid]
    assert restarted.store.get(iid).finalized


def test_postmortem_waits_for_running_recovery(make_responder):
    gate = threading.Event()
    r = make_responder(OK_BOOK)
    r.run_async = True
    original = pb.run_step

    def slow_step(*args, **kwargs):
        gate.wait(5)
        return original(*args, **kwargs)

    with mock.patch.object(pb, "run_step", slow_step):
        [iid] = r.handle_payload(payload("firing"))
        r.handle_payload(payload("resolved", ends=T0))
        assert not r.store.get(iid).finalized  # recovery still running: no postmortem yet
        gate.set()
        incident = r.wait_closed(iid, timeout=10)
    assert incident.finalized and incident.recovery_state == "succeeded"


def test_data_check_failure_after_a_good_restore_means_not_recovered(make_responder):
    book = """
name: checked
match: {alertname: DiskFull}
max_attempts: 1
steps:
  - name: restore
    run: ["{python}", "-c", "pass"]
verify:
  checks:
    - name: Validate data
      run: ["{python}", "-c", "import sys; print('totals differ'); sys.exit(1)"]
"""
    r = make_responder(book)
    [iid] = r.handle_payload(payload("firing"))
    incident = r.store.get(iid)
    assert incident.recovery_state == "failed"
    assert [(s.name, s.ok) for s in incident.attempts[0].steps] == [("restore", True), ("Validate data", False)]
    assert not incident.attempts[0].verified


def test_incident_round_trips_through_json(make_responder):
    r = make_responder(OK_BOOK)
    [iid] = r.handle_payload(payload("firing"))
    incident = r.store.get(iid)
    assert Incident.from_dict(json.loads(json.dumps(incident.to_dict()))) == incident


def test_rendered_tables_escape_pipes(make_responder):
    r = make_responder(OK_BOOK)
    [iid] = r.handle_payload(payload("firing", note="a|b"))
    assert "a\\|b" in render_postmortem(r.store.get(iid), T0)
