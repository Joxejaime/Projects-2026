from drpilot.model import Incident
from drpilot.render import data_loss_window, duration, objective_checks, render_postmortem, suggested_actions

from .helpers import T0


def make(**kwargs) -> Incident:
    base = dict(
        id="i1",
        key="A|svc",
        title="A on svc",
        service="svc",
        severity="page",
        labels={"alertname": "A"},
        annotations={"runbook": "docs/r.md"},
        impact_started_at="2026-10-26T10:00:00.000Z",
        detected_at="2026-10-26T10:00:30.000Z",
        resolved_at="2026-10-26T10:05:00.000Z",
        mitigated_at="2026-10-26T10:04:00.000Z",
        recovery_state="succeeded",
        playbook="p",
        objectives={"rto_seconds": 300, "rpo_seconds": 900},
    )
    return Incident(**{**base, **kwargs})


def test_duration_formatting():
    assert duration(1.24) == "1.2s"
    assert duration(125) == "2m 05s"
    assert duration(3725) == "1h 02m 05s"
    assert duration(None) == "n/a"


def test_rpo_is_measured_from_snapshot_time_to_impact_start_not_to_restore_time():
    i = make(facts={"snapshot_created_at": "2026-10-26T09:50:00Z", "snapshot_age_seconds": 840.0})
    assert data_loss_window(i) == 600  # the 4 minutes the recovery took are not data loss
    assert dict((n.split()[0], v) for n, _, _, v in objective_checks(i)) == {"RTO": "met", "RPO": "met"}


def test_rpo_falls_back_to_snapshot_age_and_is_unknown_without_either():
    assert data_loss_window(make(facts={"snapshot_age_seconds": 30.0})) == 30.0
    assert data_loss_window(make()) is None
    rows = {n.split()[0]: (o, v) for n, _, o, v in objective_checks(make())}
    assert rows["RPO"][1] == "MISSED" and rows["RPO"][0].startswith("unknown")


def test_missed_objectives_and_skipped_snapshots_become_follow_ups():
    i = make(
        mitigated_at="2026-10-26T10:20:00.000Z",
        facts={"snapshot_created_at": "2026-10-26T08:00:00Z", "snapshots_skipped": 2, "skipped_reasons": "x: checksum mismatch"},
    )
    actions = [a for a, _ in suggested_actions(i)]
    assert any(a.startswith("RTO missed") for a in actions)
    assert any(a.startswith("RPO missed") and "take snapshots more often" in a for a in actions)
    assert any("2 newer snapshot(s) failed verification" in a and "checksum mismatch" in a for a in actions)


def test_runbook_annotation_is_accepted_under_either_key():
    assert "Runbook: docs/r.md" in render_postmortem(make(), T0)
    assert "Runbook: http://x" in render_postmortem(make(annotations={"runbook_url": "http://x"}), T0)
    assert any("Link a runbook" in a for a, _ in suggested_actions(make(annotations={})))
