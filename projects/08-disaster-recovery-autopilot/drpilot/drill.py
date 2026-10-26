"""Disaster-recovery drill: break a real service on purpose and check the whole loop end to end.

    1. start the notes service with a data file, write notes, take a snapshot, write more notes
    2. start the responder and a probe watcher on /healthz
    3. corrupt the data file (the disaster)
    4. the watcher fires, the playbook restores the snapshot and reloads, health probes verify
    5. the watcher resolves the alert and the responder writes the postmortem draft

Scenario "corrupt-data" passes only if recovery was automated and verified, the declared RTO/RPO were
met, and the notes written before the snapshot came back. Notes written after the snapshot are lost by
design; the drill counts them, because that loss is the recovery point made visible.

Scenario "corrupt-backups" also corrupts every snapshot, so the playbook cannot succeed. It passes only
if the automation gives up and escalates instead of restoring garbage, the drill then plays the human
who rebuilds the data by hand, and the postmortem records the failed automation with a follow-up.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import playbooks as pb
from .engine import Responder
from .model import IncidentStore
from .render import objective_checks, suggested_actions
from .watch import Watcher

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "demo"))
import backup  # noqa: E402
import notes  # noqa: E402


@dataclass
class DrillResult:
    passed: bool
    incident_id: str
    postmortem: Path
    summary: list[str]


def _post(url: str, body: dict) -> None:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=5):  # noqa: S310  (local drill service)
        pass


SCENARIOS = ("corrupt-data", "corrupt-backups")


def run_drill(
    out_dir: Path, scenario: str = "corrupt-data", kept_notes: int = 5, lost_notes: int = 2, timeout: float = 60.0, interval: float = 0.2
) -> DrillResult:
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}")
    work = Path(tempfile.mkdtemp(prefix="drpilot-drill-"))
    data, backups = work / "notes.json", work / "backups"
    token = os.urandom(16).hex()
    httpd, state = notes.create_server("127.0.0.1", 0, data, token)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    env_before = {k: os.environ.get(k) for k in ("NOTES_URL", "NOTES_DATA", "NOTES_BACKUPS", "NOTES_ADMIN_TOKEN")}
    os.environ.update(NOTES_URL=url, NOTES_DATA=str(data), NOTES_BACKUPS=str(backups), NOTES_ADMIN_TOKEN=token)
    watcher = None
    try:
        for i in range(kept_notes):
            _post(url + "/notes", {"text": f"before snapshot {i}"})
        snap = backup.snapshot(data, backups)
        for i in range(lost_notes):
            _post(url + "/notes", {"text": f"after snapshot {i}"})

        responder = Responder(IncidentStore(work / "incidents"), pb.load_dir(PROJECT / "playbooks"), out_dir)
        incidents: list[str] = []
        watcher = Watcher(
            url + "/healthz",
            "NotesUnhealthy",
            lambda payload: incidents.extend(responder.handle_payload(payload)),
            labels={"service": "notes", "severity": "page"},
            annotations={
                "summary": f"Notes service data file corrupted (drill: {scenario})",
                "description": "Disaster-recovery drill: the data file was deliberately overwritten with garbage.",
                "runbook_url": "docs/runbooks/notes-unhealthy.md",
            },
            failures=3,
            successes=2,
            interval=interval,
        )
        watcher.start()
        time.sleep(interval * 3)  # healthy baseline first
        if scenario == "corrupt-backups":
            snap.write_text("bit rot")  # the backups went bad too, and nobody noticed
        data.write_text("this is not json: the disaster")  # the disaster
        deadline = time.monotonic() + timeout
        while not incidents and time.monotonic() < deadline:
            time.sleep(interval)
        if not incidents:
            raise RuntimeError("the watcher never fired; detection is broken")
        if scenario == "corrupt-backups":
            while responder.store.get(incidents[0]).recovery_state == "running" and time.monotonic() < deadline:
                time.sleep(interval)
            # The paged human rebuilds what they can and reloads; the alert then resolves on its own.
            notes.write_store(data, ["rebuilt by hand"])
            req = urllib.request.Request(url + "/admin/reload", method="POST", headers={"Authorization": f"Bearer {token}"})  # noqa: S310
            urllib.request.urlopen(req, timeout=5).close()  # noqa: S310
        incident = responder.wait_closed(incidents[0], timeout=max(1.0, deadline - time.monotonic()))
        with state.lock:
            restored = list(state.notes)
    finally:
        if watcher:
            watcher.stop()
        httpd.shutdown()
        httpd.server_close()
        for key, value in env_before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(work, ignore_errors=True)

    checks = objective_checks(incident)
    if scenario == "corrupt-data":
        expected = [f"before snapshot {i}" for i in range(kept_notes)]
        passed = incident.finalized and incident.recovery_state == "succeeded" and restored == expected and all(c[3] == "met" for c in checks)
        data_line = f"data: {len(restored)} notes restored, {lost_notes} written after the snapshot were lost (expected: RPO > 0)"
    else:
        followup = any(a.startswith(f"Automation '{incident.playbook}' failed") for a, _ in suggested_actions(incident))
        passed = incident.finalized and incident.recovery_state == "failed" and restored == ["rebuilt by hand"] and followup
        data_line = f"data: automation refused to restore a corrupt snapshot and escalated; {kept_notes + lost_notes} notes lost, rebuilt by hand"
    summary = [
        f"scenario {scenario}: incident {incident.id}, recovery {incident.recovery_state}, postmortem {incident.postmortem_path}",
        data_line,
        *(f"{name}: target {target}, observed {observed} -> {verdict}" for name, target, observed, verdict in checks),
        "DRILL PASSED" if passed else "DRILL FAILED",
    ]
    return DrillResult(passed, incident.id, Path(incident.postmortem_path or ""), summary)
