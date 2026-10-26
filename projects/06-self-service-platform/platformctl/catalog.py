"""Service catalog: discover every service.yaml under a directory and report on them."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .models import Finding, ServiceSpec, load_spec


@dataclass
class CatalogEntry:
    path: Path
    spec: ServiceSpec | None
    findings: list[Finding] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.spec is not None


def collect(root: Path) -> list[CatalogEntry]:
    entries = []
    for path in sorted(root.rglob("service.yaml")):
        if any(part.startswith(".") for part in path.relative_to(root).parts[:-1]):
            continue
        spec, findings = load_spec(path)
        entries.append(CatalogEntry(path, spec, findings))
    names = Counter(e.spec.name for e in entries if e.spec)
    for entry in entries:
        if entry.spec and names[entry.spec.name] > 1:
            entry.findings.append(Finding("CAT001", "error", f"duplicate service name {entry.spec.name!r}", str(entry.path)))
    return entries


def to_json(entries: list[CatalogEntry], root: Path) -> str:
    services = []
    for e in entries:
        item = {"path": str(e.path.relative_to(root)), "valid": e.valid, "findings": [f.as_dict() for f in e.findings]}
        if e.spec:
            item.update(e.spec.to_dict())
        services.append(item)
    return json.dumps({"services": services}, indent=2)


def to_markdown(entries: list[CatalogEntry], root: Path) -> str:
    valid = [e for e in entries if e.spec]
    lines = ["# Service catalog", "", f"{len(valid)} valid service(s), {len(entries) - len(valid)} invalid.", ""]
    if valid:
        lines += ["| Service | Owner | Tier | SLO | Replicas | Environments | Spec |", "|---|---|---|---|---|---|---|"]
        for e in sorted(valid, key=lambda x: x.spec.name):
            s = e.spec
            lines.append(
                f"| {s.name} | {s.owner} | {s.tier} | {s.slo_availability:g}% | {s.replicas} | "
                f"{', '.join(s.environments)} | `{e.path.relative_to(root)}` |"
            )
        by_tier = Counter(e.spec.tier for e in valid)
        by_owner = Counter(e.spec.owner for e in valid)
        lines += ["", "## Summary", "", "**By tier:** " + ", ".join(f"{k}: {v}" for k, v in sorted(by_tier.items()))]
        lines.append("**By owner:** " + ", ".join(f"{k}: {v}" for k, v in sorted(by_owner.items())))
    problems = [e for e in entries if any(f.severity == "error" for f in e.findings)]
    if problems:
        lines += ["", "## Problems", ""]
        for e in problems:
            for f in e.findings:
                lines.append(f"- `{e.path.relative_to(root)}`: {f.rule} {f.message}")
    return "\n".join(lines) + "\n"
