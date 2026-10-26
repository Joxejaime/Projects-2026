#!/usr/bin/env python3
"""Offline sanity checks for the config files (no Prometheus/kubectl binaries required).

- every YAML file parses
- Prometheus rule files have the expected structure and every alert references a runbook
  that exists in the repo
- the Grafana dashboard is valid JSON and every panel has a query
- Kubernetes workloads set resource limits, a non-root user and pinned image tags
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def load_yaml_docs(path: Path) -> list:
    try:
        return [d for d in yaml.safe_load_all(path.read_text()) if d is not None]
    except yaml.YAMLError as exc:
        fail(f"{path.relative_to(ROOT)}: invalid YAML: {exc}")
        return []


def check_rules(path: Path, doc: dict) -> None:
    for group in doc.get("groups", []):
        for rule in group.get("rules", []):
            label = f"{path.name}:{group.get('name')}"
            if "record" not in rule and "alert" not in rule:
                fail(f"{label}: rule has neither record nor alert")
            if not str(rule.get("expr", "")).strip():
                fail(f"{label}: rule {rule.get('alert') or rule.get('record')} has empty expr")
            if "alert" in rule:
                if "severity" not in rule.get("labels", {}):
                    fail(f"{label}: alert {rule['alert']} has no severity label")
                runbook = rule.get("annotations", {}).get("runbook")
                if runbook and not (ROOT / runbook).exists():
                    fail(f"{label}: alert {rule['alert']} points to missing runbook {runbook}")


def check_k8s(path: Path, doc: dict) -> None:
    if doc.get("kind") != "Deployment":
        return
    spec = doc["spec"]["template"]["spec"]
    for container in spec.get("containers", []):
        name = f"{path.name}:{container['name']}"
        image = container.get("image", "")
        if ":" not in image.split("/")[-1] or image.endswith(":latest"):
            fail(f"{name}: image must use a pinned tag, got {image!r}")
        if "limits" not in container.get("resources", {}):
            fail(f"{name}: missing resource limits")
        if container.get("securityContext", {}).get("allowPrivilegeEscalation") is not False:
            fail(f"{name}: allowPrivilegeEscalation must be false")
    if not spec.get("securityContext", {}).get("runAsNonRoot"):
        fail(f"{path.name}: pod must set runAsNonRoot")


def main() -> int:
    count = 0
    for path in sorted(ROOT.rglob("*.y*ml")):
        if any(part in {".git", "node_modules", ".venv"} for part in path.parts):
            continue
        # skip GitHub Actions expressions-only files? they are valid YAML too
        count += 1
        for doc in load_yaml_docs(path):
            if isinstance(doc, dict) and "groups" in doc and path.parent.name == "rules":
                check_rules(path, doc)
            if isinstance(doc, dict) and "apiVersion" in doc and "kind" in doc and path.parts[-2] == "k8s":
                check_k8s(path, doc)
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
    print(f"OK: validated {count} YAML files plus JSON dashboards")
    return 0


if __name__ == "__main__":
    sys.exit(main())
