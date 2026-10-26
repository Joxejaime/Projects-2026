"""Parse Alertmanager webhook payloads (version 4) into alerts the responder can act on."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .model import parse_time


class PayloadError(ValueError):
    pass


@dataclass(frozen=True)
class Alert:
    fingerprint: str
    status: str  # firing | resolved
    labels: dict
    annotations: dict
    starts_at: datetime | None
    ends_at: datetime | None

    @property
    def name(self) -> str:
        return self.labels.get("alertname", "unnamed")

    @property
    def service(self) -> str:
        return self.labels.get("service") or self.labels.get("job") or "unknown"

    @property
    def severity(self) -> str:
        return self.labels.get("severity", "unknown")

    @property
    def incident_key(self) -> str:
        return f"{self.name}|{self.service}"


def parse_payload(payload: object) -> list[Alert]:
    if not isinstance(payload, dict) or not isinstance(payload.get("alerts"), list):
        raise PayloadError("expected an Alertmanager webhook payload with an 'alerts' list")
    alerts = []
    for raw in payload["alerts"]:
        if not isinstance(raw, dict):
            raise PayloadError("each alert must be an object")
        status = raw.get("status")
        labels = raw.get("labels") or {}
        if status not in ("firing", "resolved") or not isinstance(labels, dict) or "alertname" not in labels:
            raise PayloadError("each alert needs status firing|resolved and an alertname label")
        try:
            starts, ends = parse_time(raw.get("startsAt")), parse_time(raw.get("endsAt"))
        except ValueError as err:
            raise PayloadError(f"bad timestamp: {err}") from err
        fingerprint = raw.get("fingerprint") or "|".join(f"{k}={labels[k]}" for k in sorted(labels))
        alerts.append(Alert(str(fingerprint), status, {str(k): str(v) for k, v in labels.items()}, raw.get("annotations") or {}, starts, ends))
    return alerts
