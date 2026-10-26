"""Consistency between this project's alert rules, playbooks and Alertmanager snippet, and project 04 which they plug into."""

import copy
from pathlib import Path

import pytest
import yaml

from drpilot import playbooks as pb

ROOT = Path(__file__).resolve().parent.parent
P04 = ROOT.parent / "04-observability-slo"


def rules(path):
    doc = yaml.safe_load(Path(path).read_text())
    return [r for g in doc["groups"] for r in g["rules"] if "alert" in r]


@pytest.fixture(scope="module")
def books():
    return pb.load_dir(ROOT / "playbooks")


def test_every_autoremediated_alert_has_a_playbook_and_every_alert_a_runbook(books):
    mine = rules(ROOT / "observability" / "alert-rules.yml")
    assert {r["alert"] for r in mine} == {"OrdersDataUnhealthy", "BackupRestoreTestFailing", "BackupRestoreTestStale"}
    for rule in mine:
        labels = {"alertname": rule["alert"], **rule["labels"]}
        if rule["labels"].get("autoremediate") == "true":
            assert pb.select(books, labels) is not None, f"{rule['alert']} is routed to drpilot but no playbook matches it"
        else:
            assert pb.select(books, labels) is None, f"{rule['alert']} has a playbook but is not routed to drpilot"
        assert (ROOT / rule["annotations"]["runbook"]).is_file(), f"{rule['alert']}: runbook {rule['annotations']['runbook']} does not exist"


def test_playbooks_for_project_04_alerts_name_alerts_that_exist_there(books):
    theirs = {r["alert"]: r for r in rules(P04 / "prometheus" / "rules" / "service-alerts.yml")}
    for book in books:
        if book.match["alertname"] in {"TargetDown", "CrashLooping"}:
            rule = theirs[book.match["alertname"]]
            assert rule["labels"]["service"] == book.match["service"], f"{book.name} no longer matches 04's {rule['alert']} labels"
    prometheus = yaml.safe_load((P04 / "prometheus" / "prometheus.yml").read_text())
    assert "environment" in prometheus["global"]["external_labels"], "04 must keep attaching an `environment` label for the dev-only playbooks to match"


def test_alertmanager_snippet_merges_into_project_04_without_disturbing_its_routes():
    base = yaml.safe_load((P04 / "alertmanager" / "alertmanager.yml").read_text())
    snippet = yaml.safe_load((ROOT / "observability" / "alertmanager-snippet.yml").read_text())
    merged = copy.deepcopy(base)
    merged["route"]["routes"] = snippet["route"]["routes"] + merged["route"]["routes"]
    merged["receivers"] += snippet["receivers"]

    first = merged["route"]["routes"][0]
    assert first["receiver"] == "drpilot" and first["continue"] is True, "without continue, humans would no longer be paged"
    assert [r["receiver"] for r in merged["route"]["routes"][1:]] == [r["receiver"] for r in base["route"]["routes"]]
    names = [r["name"] for r in merged["receivers"]]
    assert len(names) == len(set(names)) and {"default", "pager", "ticket", "drpilot"} <= set(names)
    hook = next(r for r in merged["receivers"] if r["name"] == "drpilot")["webhook_configs"][0]
    assert hook["send_resolved"] is True and hook["url"].endswith("/alerts")
    assert "credentials_file" in hook["http_config"]["authorization"], "the token must come from a file, never inline"
