"""Incidents, their timeline, and a small JSON-file store.

One incident groups every alert that shares an incident key (alertname + service). It is open while
any of those alerts is firing, and it is finalized (postmortem written) once all of them have resolved
and no automated recovery is still running.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


def utcnow() -> datetime:
    return datetime.now(UTC)


_FRACTION = re.compile(r"\.(\d+)")


def parse_time(value: str | None) -> datetime | None:
    """Parse RFC 3339 timestamps as Alertmanager sends them (nanoseconds, 'Z' suffix, or the zero time)."""
    if not value or value.startswith("0001-01-01"):
        return None
    text = value.strip().replace("Z", "+00:00")
    text = _FRACTION.sub(lambda m: "." + m.group(1)[:6].ljust(6, "0"), text, count=1)
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z") if value else None


@dataclass
class Event:
    at: str
    kind: str
    message: str
    data: dict = field(default_factory=dict)


@dataclass
class StepResult:
    name: str
    ok: bool
    seconds: float
    detail: str
    output: str = ""


@dataclass
class Attempt:
    number: int
    started_at: str
    finished_at: str | None = None
    steps: list[StepResult] = field(default_factory=list)
    verified: bool = False


@dataclass
class Incident:
    id: str
    key: str
    title: str
    service: str
    severity: str
    labels: dict
    annotations: dict
    impact_started_at: str | None
    detected_at: str
    alert_state: str = "firing"  # firing | resolved
    recovery_state: str = "pending"  # pending | running | succeeded | failed | no_playbook
    playbook: str | None = None
    objectives: dict = field(default_factory=dict)
    mitigated_at: str | None = None
    resolved_at: str | None = None
    active_alerts: list[str] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    finalized: bool = False
    postmortem_path: str | None = None
    published_url: str | None = None

    @property
    def status(self) -> str:
        if self.finalized:
            return "closed"
        if self.alert_state == "resolved":
            return "resolved"
        return {"succeeded": "mitigated", "failed": "escalated", "no_playbook": "escalated"}.get(self.recovery_state, "open")

    def log(self, at: datetime, kind: str, message: str, **data) -> None:
        self.events.append(Event(iso(at), kind, message, data))

    def to_dict(self) -> dict:
        return asdict(self) | {"status": self.status}

    @classmethod
    def from_dict(cls, raw: dict) -> Incident:
        raw = {k: v for k, v in raw.items() if k != "status"}
        raw["events"] = [Event(**e) for e in raw.get("events", [])]
        raw["attempts"] = [Attempt(**{**a, "steps": [StepResult(**s) for s in a.get("steps", [])]}) for a in raw.get("attempts", [])]
        return cls(**raw)


class IncidentStore:
    """Incidents as one JSON file each. Writes are atomic so a crash never leaves half a file."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def _path(self, incident_id: str) -> Path:
        return self.dir / f"{incident_id}.json"

    def save(self, incident: Incident) -> None:
        with self.lock:
            tmp = self._path(incident.id).with_suffix(".tmp")
            tmp.write_text(json.dumps(incident.to_dict(), indent=2, sort_keys=True))
            os.replace(tmp, self._path(incident.id))

    def get(self, incident_id: str) -> Incident:
        with self.lock:
            return Incident.from_dict(json.loads(self._path(incident_id).read_text()))

    def all(self) -> list[Incident]:
        with self.lock:
            return sorted((self.get(p.stem) for p in self.dir.glob("*.json")), key=lambda i: i.detected_at)

    def open_by_key(self, key: str) -> Incident | None:
        """The unfinished incident for this key, if any (survives restarts: it is read from disk)."""
        for incident in reversed(self.all()):
            if incident.key == key and not incident.finalized:
                return incident
        return None
