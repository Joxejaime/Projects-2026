"""Service spec model, tier defaults and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

NAME_RE = re.compile(r"^[a-z]([-a-z0-9]{0,40}[a-z0-9])?$")  # DNS-1123 label, max 42 chars
OWNER_RE = re.compile(r"^team-[a-z][a-z0-9-]{0,30}$")
ENV_NAMES = {"dev", "staging", "prod"}
LANGUAGES = {"python"}
KNOWN_KEYS = {"apiVersion", "kind", "name", "owner", "tier", "language", "port", "replicas", "registry",
               "environments", "slo"}  # fmt: skip

# What each reliability tier means in terms of platform defaults. Teams pick a tier; the
# platform turns it into replicas, resources and disruption policy.
TIER_DEFAULTS: dict[str, dict] = {
    "critical": {
        "replicas": 3,
        "cpu_request": "250m",
        "cpu_limit": "1000m",
        "memory_request": "256Mi",
        "memory_limit": "512Mi",
        "slo_availability": 99.95,
        "pdb": True,
        "min_available": 2,
    },
    "standard": {
        "replicas": 2,
        "cpu_request": "100m",
        "cpu_limit": "500m",
        "memory_request": "128Mi",
        "memory_limit": "256Mi",
        "slo_availability": 99.9,
        "pdb": True,
        "min_available": 1,
    },
    "best-effort": {
        "replicas": 1,
        "cpu_request": "50m",
        "cpu_limit": "250m",
        "memory_request": "64Mi",
        "memory_limit": "128Mi",
        "slo_availability": 99.0,
        "pdb": False,
        "min_available": 0,
    },
}


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str  # "error" | "warning"
    message: str
    path: str = ""

    def format(self) -> str:
        where = f"{self.path}: " if self.path else ""
        return f"{self.severity.upper():7} {self.rule} {where}{self.message}"

    def as_dict(self) -> dict:
        return {"rule": self.rule, "severity": self.severity, "message": self.message, "path": self.path}


@dataclass
class ServiceSpec:
    name: str
    owner: str
    tier: str = "standard"
    language: str = "python"
    port: int = 8080
    replicas: int = 0  # 0 => use the tier default
    registry: str = "ghcr.io/example-org"
    environments: list[str] = field(default_factory=lambda: ["dev", "prod"])
    slo_availability: float = 0.0  # 0 => use the tier default

    def __post_init__(self) -> None:
        defaults = TIER_DEFAULTS.get(self.tier, TIER_DEFAULTS["standard"])
        if not self.replicas:
            self.replicas = defaults["replicas"]
        if not self.slo_availability:
            self.slo_availability = defaults["slo_availability"]

    @property
    def tier_defaults(self) -> dict:
        return TIER_DEFAULTS[self.tier]

    def to_dict(self) -> dict:
        return {
            "apiVersion": "platform/v1",
            "kind": "Service",
            "name": self.name,
            "owner": self.owner,
            "tier": self.tier,
            "language": self.language,
            "port": self.port,
            "replicas": self.replicas,
            "registry": self.registry,
            "environments": list(self.environments),
            "slo": {"availability": self.slo_availability},
        }


def validate_fields(name, owner, tier, port=8080, replicas=None, language="python") -> list[Finding]:
    """Shared checks for both the spec file and the `new` command arguments."""
    findings: list[Finding] = []
    if not isinstance(name, str) or not NAME_RE.match(name):
        findings.append(Finding("SPEC002", "error", f"name {name!r} must be a lowercase DNS label (a-z, 0-9, '-', max 42 chars)"))
    if not isinstance(owner, str) or not OWNER_RE.match(owner):
        findings.append(Finding("SPEC003", "error", f"owner {owner!r} must look like 'team-<name>'"))
    if tier not in TIER_DEFAULTS:
        findings.append(Finding("SPEC004", "error", f"tier {tier!r} must be one of {sorted(TIER_DEFAULTS)}"))
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        findings.append(Finding("SPEC006", "error", f"port {port!r} must be an integer between 1024 and 65535"))
    if replicas is not None and (isinstance(replicas, bool) or not isinstance(replicas, int) or replicas < 1):
        findings.append(Finding("SPEC007", "error", f"replicas {replicas!r} must be a positive integer"))
    if language not in LANGUAGES:
        findings.append(Finding("SPEC008", "error", f"language {language!r} must be one of {sorted(LANGUAGES)}"))
    return findings


def load_spec(path: Path) -> tuple[ServiceSpec | None, list[Finding]]:
    """Parse and validate a service.yaml. Returns (spec or None, findings)."""
    rel = str(path)
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        return None, [Finding("SPEC000", "error", f"cannot read spec: {exc}", rel)]
    if not isinstance(data, dict):
        return None, [Finding("SPEC000", "error", "spec must be a YAML mapping", rel)]

    findings = [Finding("SPEC005", "error", f"unknown field {key!r}", rel) for key in sorted(set(data) - KNOWN_KEYS)]
    for required in ("name", "owner"):
        if required not in data:
            findings.append(Finding("SPEC001", "error", f"missing required field {required!r}", rel))
    findings += [
        Finding(f.rule, f.severity, f.message, rel)
        for f in validate_fields(
            data.get("name"),
            data.get("owner"),
            data.get("tier", "standard"),
            data.get("port", 8080),
            data.get("replicas"),
            data.get("language", "python"),
        )
    ]
    envs = data.get("environments", ["dev", "prod"])
    if not isinstance(envs, list) or not envs or any(e not in ENV_NAMES for e in envs):
        findings.append(Finding("SPEC009", "error", f"environments must be a non-empty subset of {sorted(ENV_NAMES)}", rel))
    slo = (data.get("slo") or {}).get("availability") if isinstance(data.get("slo", {}), dict) else None
    if slo is not None and (isinstance(slo, bool) or not isinstance(slo, (int, float)) or not 90 <= slo < 100):
        findings.append(Finding("SPEC010", "error", "slo.availability must be a percentage in [90, 100)", rel))

    if any(f.severity == "error" for f in findings):
        return None, findings
    spec = ServiceSpec(
        name=data["name"],
        owner=data["owner"],
        tier=data.get("tier", "standard"),
        language=data.get("language", "python"),
        port=data.get("port", 8080),
        replicas=data.get("replicas") or 0,
        registry=data.get("registry", "ghcr.io/example-org"),
        environments=list(envs),
        slo_availability=float(slo) if slo is not None else 0.0,
    )
    return spec, findings
