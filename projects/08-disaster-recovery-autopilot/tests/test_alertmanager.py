from datetime import UTC, datetime

import pytest

from drpilot.alertmanager import PayloadError, parse_payload
from drpilot.engine import synthetic_alert
from drpilot.model import parse_time

from .helpers import T0, payload


def test_parses_alertmanager_nanosecond_timestamps_and_zero_time():
    assert parse_time("2026-10-26T10:00:00.123456789Z") == datetime(2026, 10, 26, 10, 0, 0, 123456, tzinfo=UTC)
    assert parse_time("0001-01-01T00:00:00Z") is None
    assert parse_time(None) is None


def test_parse_payload():
    alerts = parse_payload(payload("firing"))
    assert alerts[0].incident_key == "DiskFull|api"
    assert alerts[0].ends_at is None


@pytest.mark.parametrize(
    "bad",
    [[], {"alerts": "x"}, {"alerts": [{"status": "weird", "labels": {"alertname": "a"}}]}, {"alerts": [{"status": "firing", "labels": {}}]}],
)
def test_rejects_malformed_payloads(bad):
    with pytest.raises(PayloadError):
        parse_payload(bad)


def test_synthetic_alert_round_trips():
    alert = parse_payload(synthetic_alert("A", "firing", {"service": "s"}, {}, T0))[0]
    assert (alert.name, alert.service, alert.starts_at) == ("A", "s", T0)
