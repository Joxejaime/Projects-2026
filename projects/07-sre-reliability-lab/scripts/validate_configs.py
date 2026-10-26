#!/usr/bin/env python3
"""Offline sanity checks for the lab's config files (no Prometheus/Alertmanager binaries needed)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def load(path: Path):
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        fail(f"{path.relative_to(ROOT)}: invalid YAML: {exc}")


def main() -> int:
    for path in sorted(ROOT.rglob("*.y*ml")):
        if ".git" not in path.parts:
            load(path)

    prom = load(ROOT / "observability" / "prometheus.yml") or {}
    if not prom.get("scrape_configs"):
        fail("prometheus.yml: no scrape_configs")

    am = load(ROOT / "observability" / "alertmanager.yml") or {}
    receivers = {r["name"] for r in am.get("receivers", [])}
    route = am.get("route", {})
    used = {route.get("receiver")} | {r.get("receiver") for r in route.get("routes", [])}
    for name in used - receivers:
        fail(f"alertmanager.yml: route uses undefined receiver {name!r}")

    rules = load(ROOT / "generated" / "shop-api.rules.yml") or {}
    for group in rules.get("groups", []):
        for rule in group["rules"]:
            if not str(rule.get("expr", "")).strip():
                fail(f"{group['name']}: empty expr")
            if "alert" in rule and rule["labels"].get("severity") not in {"page", "ticket"}:
                fail(f"{rule['alert']}: severity must be page or ticket (alertmanager routes on it)")

    for path in ROOT.rglob("*.json"):
        if ".git" in path.parts:
            continue
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            fail(f"{path.relative_to(ROOT)}: invalid JSON: {exc}")
            continue
        for panel in data.get("panels", []):
            if not panel.get("targets"):
                fail(f"{path.name}: panel {panel.get('title')!r} has no queries")

    if errors:
        print("\n".join(f"FAIL {e}" for e in errors))
        return 1
    print("OK: config files are consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
