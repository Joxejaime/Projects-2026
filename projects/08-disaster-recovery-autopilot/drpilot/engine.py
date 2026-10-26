"""The responder: alerts open incidents, playbooks try to recover, resolution writes the postmortem.

Lifecycle of one incident:
    firing alert  -> incident opened, detection time recorded
                  -> matching playbook runs (up to max_attempts), each attempt verified by health probes
                  -> no playbook, or every attempt failed: escalated to a human (recorded on the timeline)
    all alerts resolved and no recovery running -> postmortem draft rendered (and optionally published)

Repeated notifications for an alert that is already firing are idempotent: Alertmanager re-sends at
repeat_interval, and that must not re-run a restore.
"""

from __future__ import annotations

import re
import threading
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from . import playbooks as pb
from .alertmanager import Alert, parse_payload
from .model import Attempt, Incident, IncidentStore, iso, utcnow
from .render import render_postmortem


class Responder:
    def __init__(
        self,
        store: IncidentStore,
        books: list[pb.Playbook],
        postmortem_dir: Path,
        clock: Callable[[], datetime] = utcnow,
        run_async: bool = True,
        publisher=None,
        sleep=None,
    ):
        self.store = store
        self.books = books
        self.postmortem_dir = Path(postmortem_dir)
        self.clock = clock
        self.run_async = run_async
        self.publisher = publisher
        self.sleep = sleep
        self.lock = threading.RLock()
        self.threads: dict[str, threading.Thread] = {}
        self.finalized = threading.Condition(self.lock)

    # ---- webhook entry point -------------------------------------------------------------------
    def handle_payload(self, payload: object) -> list[str]:
        touched = []
        for alert in parse_payload(payload):
            incident_id = self._on_firing(alert) if alert.status == "firing" else self._on_resolved(alert)
            if incident_id and incident_id not in touched:
                touched.append(incident_id)
        return touched

    def _on_firing(self, alert: Alert) -> str:
        with self.lock:
            now = self.clock()
            incident = self.store.open_by_key(alert.incident_key)
            if incident and incident.alert_state == "resolved":
                # Resolved but its postmortem is still waiting on a running recovery: a new firing is a new incident.
                incident = None
            if incident:
                if alert.fingerprint not in incident.active_alerts:
                    incident.active_alerts.append(alert.fingerprint)
                    incident.log(now, "alert", f"Another alert joined the incident ({alert.fingerprint})")
                    self.store.save(incident)
                return incident.id
            incident = self._open(alert, now)
            book = pb.select(self.books, alert.labels)
            if book is None:
                incident.recovery_state = "no_playbook"
                incident.log(now, "escalation", f"No playbook matches {alert.name}; paging a human")
                self.store.save(incident)
                return incident.id
            incident.playbook, incident.objectives = book.name, dict(book.objectives)
            incident.recovery_state = "running"
            incident.log(now, "automation", f"Playbook '{book.name}' selected (up to {book.max_attempts} attempt(s))")
            self.store.save(incident)
        if self.run_async:
            thread = threading.Thread(target=self._recover, args=(incident.id, book, alert.labels), daemon=True)
            self.threads[incident.id] = thread
            thread.start()
        else:
            self._recover(incident.id, book, alert.labels)
        return incident.id

    def _open(self, alert: Alert, now: datetime) -> Incident:
        slug = re.sub(r"[^a-z0-9]+", "-", alert.name.lower()).strip("-")[:32] or "alert"
        incident = Incident(
            id=f"{now:%Y%m%d-%H%M%S}-{slug}-{uuid.uuid4().hex[:4]}",
            key=alert.incident_key,
            title=alert.annotations.get("summary") or f"{alert.name} on {alert.service}",
            service=alert.service,
            severity=alert.severity,
            labels=alert.labels,
            annotations=alert.annotations,
            impact_started_at=iso(alert.starts_at) or iso(now),
            detected_at=iso(now),
            active_alerts=[alert.fingerprint],
        )
        if alert.starts_at:
            incident.log(alert.starts_at, "impact", "Impact began (alert condition first true)")
        incident.log(now, "alert", f"{alert.name} fired ({alert.severity}); incident opened")
        return incident

    def _on_resolved(self, alert: Alert) -> str | None:
        with self.lock:
            incident = self.store.open_by_key(alert.incident_key)
            if incident is None or alert.fingerprint not in incident.active_alerts:
                return None  # resolution for something we never saw firing, or already handled
            now = self.clock()
            incident.active_alerts.remove(alert.fingerprint)
            if incident.active_alerts:
                incident.log(now, "alert", f"One alert resolved; {len(incident.active_alerts)} still firing")
                self.store.save(incident)
                return incident.id
            ended = alert.ends_at if alert.ends_at and alert.ends_at <= now else now
            incident.alert_state, incident.resolved_at = "resolved", iso(ended)
            incident.log(ended, "resolved", f"{alert.name} resolved; impact over")
            self.store.save(incident)
            self._maybe_finalize(incident)
            return incident.id

    # ---- automated recovery ----------------------------------------------------------------------
    def _recover(self, incident_id: str, book: pb.Playbook, labels: dict) -> None:
        recovered = False
        for number in range(1, book.max_attempts + 1):
            attempt = Attempt(number, iso(self.clock()))
            self._update(incident_id, lambda i, n=number: i.log(self.clock(), "automation", f"Recovery attempt {n} started"))
            facts: dict = {}
            for step in book.steps:
                result, step_facts = pb.run_step(step, book, labels)
                attempt.steps.append(result)
                facts |= step_facts
                self._update(incident_id, lambda i, r=result: i.log(self.clock(), "step", f"{r.name}: {'ok' if r.ok else 'FAILED'} ({r.detail})"))
                if not result.ok:
                    break
            else:
                checks, check_facts = pb.verify(book, labels, **({"sleep": self.sleep} if self.sleep else {}))
                attempt.steps.extend(checks)
                facts |= check_facts
                attempt.verified = recovered = all(c.ok for c in checks)

                def log_checks(i: Incident, results=checks, ok=recovered) -> None:
                    for c in results:
                        i.log(self.clock(), "verify", f"{c.name}: {'passed' if c.ok else 'FAILED'} ({c.detail})")
                    i.log(self.clock(), "verify", f"Verification {'passed' if ok else 'FAILED'}")

                self._update(incident_id, log_checks)
            attempt.finished_at = iso(self.clock())

            def record(i: Incident, a=attempt, f=facts, ok=recovered) -> None:
                i.attempts.append(a)
                i.facts |= f
                if ok:
                    i.recovery_state, i.mitigated_at = "succeeded", a.finished_at
                    i.log(self.clock(), "mitigated", f"Service recovered by automation (attempt {a.number})")

            self._update(incident_id, record)
            if recovered:
                break
        if not recovered:

            def give_up(i: Incident) -> None:
                i.recovery_state = "failed"
                i.log(self.clock(), "escalation", f"Automation gave up after {book.max_attempts} attempt(s); paging a human")

            self._update(incident_id, give_up)
        with self.lock:
            self.threads.pop(incident_id, None)
            self._maybe_finalize(self.store.get(incident_id))

    def _update(self, incident_id: str, change: Callable[[Incident], None]) -> None:
        with self.lock:
            incident = self.store.get(incident_id)
            change(incident)
            self.store.save(incident)

    # ---- postmortem ------------------------------------------------------------------------------
    def _maybe_finalize(self, incident: Incident) -> None:
        if incident.finalized or incident.alert_state != "resolved" or incident.recovery_state in ("pending", "running"):
            return
        now = self.clock()
        incident.log(now, "postmortem", "Postmortem draft generated")
        self.postmortem_dir.mkdir(parents=True, exist_ok=True)
        path = self.postmortem_dir / f"{incident.id}.md"
        incident.finalized, incident.postmortem_path = True, str(path)
        path.write_text(render_postmortem(incident, generated_at=now))
        if self.publisher is not None:
            try:
                incident.published_url = self.publisher.publish(incident, path.read_text())
                incident.log(self.clock(), "postmortem", f"Draft published for review: {incident.published_url}")
            except Exception as err:  # publishing is best effort; the file on disk is the record
                incident.log(self.clock(), "postmortem", f"Publishing the draft failed: {err}")
            path.write_text(render_postmortem(incident, generated_at=now))
        self.store.save(incident)
        self.finalized.notify_all()

    def wait_closed(self, incident_id: str, timeout: float) -> Incident:
        """Block until the incident's postmortem is written (used by the drill and tests)."""
        with self.finalized:
            self.finalized.wait_for(lambda: self.store.get(incident_id).finalized, timeout=timeout)
            return self.store.get(incident_id)


def synthetic_alert(alertname: str, status: str, labels: dict, annotations: dict, starts_at: datetime, ends_at: datetime | None = None) -> dict:
    """An Alertmanager-shaped payload, for the probe watcher and for replaying incidents by hand."""
    all_labels = {"alertname": alertname, **labels}
    return {
        "version": "4",
        "status": status,
        "alerts": [
            {
                "status": status,
                "labels": all_labels,
                "annotations": annotations,
                "startsAt": iso(starts_at),
                "endsAt": iso(ends_at) if ends_at else "0001-01-01T00:00:00Z",
                "fingerprint": "probe-" + "-".join(f"{k}={all_labels[k]}" for k in sorted(all_labels)),
            }
        ],
    }
