"""Policy-as-code: checks run against a service repository (spec, k8s, Dockerfile, CI)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .models import TIER_DEFAULTS, Finding, ServiceSpec, load_spec

DEFAULT_POLICY = {
    "allowed_registries": ["ghcr.io/joxejaime/"],
    "required_labels": ["app.kubernetes.io/name", "platform.example/owner", "platform.example/tier"],
    "min_replicas": {tier: d["replicas"] if tier != "best-effort" else 1 for tier, d in TIER_DEFAULTS.items()},
}

WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "CronJob", "Pod"}


def load_policy(path: Path | None) -> dict:
    policy = {k: (dict(v) if isinstance(v, dict) else list(v)) for k, v in DEFAULT_POLICY.items()}
    if path is None:
        return policy
    data = yaml.safe_load(path.read_text()) or {}
    for key, value in data.items():
        if key not in policy:
            raise ValueError(f"unknown policy key {key!r} in {path}")
        if isinstance(policy[key], dict):
            policy[key].update(value)
        else:
            policy[key] = list(value)
    return policy


# --- Kubernetes --------------------------------------------------------------------------
def _pod_spec(doc: dict) -> dict | None:
    kind = doc.get("kind")
    spec = doc.get("spec") or {}
    if kind == "Pod":
        return spec
    if kind == "CronJob":
        return (((spec.get("jobTemplate") or {}).get("spec") or {}).get("template") or {}).get("spec")
    return (spec.get("template") or {}).get("spec")


def _image_findings(image: str, policy: dict, where: str) -> list[Finding]:
    out: list[Finding] = []
    last = image.rsplit("/", 1)[-1]
    if "@sha256:" not in image and (":" not in last or last.endswith(":latest")):
        out.append(Finding("K8S001", "error", f"image {image!r} must use a pinned tag or digest, not 'latest'", where))
    if not any(image.startswith(prefix) for prefix in policy["allowed_registries"]):
        out.append(
            Finding("K8S002", "error", f"image {image!r} is not from an allowed registry {policy['allowed_registries']}", where)
        )
    return out


def check_k8s_doc(doc: dict, policy: dict, tier: str | None, where: str) -> list[Finding]:
    if not isinstance(doc, dict) or doc.get("kind") not in WORKLOAD_KINDS:
        return []
    name = (doc.get("metadata") or {}).get("name", "?")
    where = f"{where} [{doc['kind']}/{name}]"
    findings: list[Finding] = []
    pod = _pod_spec(doc)
    if pod is None:
        return findings

    labels = (doc.get("metadata") or {}).get("labels") or {}
    for label in policy["required_labels"]:
        if label not in labels:
            findings.append(Finding("K8S010", "error", f"missing required label {label!r}", where))

    if doc["kind"] == "Deployment" and tier in policy["min_replicas"]:
        replicas = (doc.get("spec") or {}).get("replicas", 1)
        if replicas < policy["min_replicas"][tier]:
            findings.append(
                Finding(
                    "K8S009",
                    "error",
                    f"tier {tier!r} requires at least {policy['min_replicas'][tier]} replicas, got {replicas}",
                    where,
                )
            )

    pod_sc = pod.get("securityContext") or {}
    for key in ("hostNetwork", "hostPID", "hostIPC"):
        if pod.get(key):
            findings.append(Finding("K8S008", "error", f"{key} must not be enabled", where))

    for container in (pod.get("initContainers") or []) + (pod.get("containers") or []):
        cwhere = f"{where} container {container.get('name', '?')}"
        sc = container.get("securityContext") or {}
        findings += _image_findings(container.get("image", ""), policy, cwhere)

        resources = container.get("resources") or {}
        requests, limits = resources.get("requests") or {}, resources.get("limits") or {}
        missing = [k for k in ("cpu", "memory") if k not in requests] + (["limits.memory"] if "memory" not in limits else [])
        if missing:
            findings.append(Finding("K8S003", "error", f"resources missing: {', '.join(missing)}", cwhere))

        if not (sc.get("runAsNonRoot") or pod_sc.get("runAsNonRoot")):
            findings.append(Finding("K8S004", "error", "must set runAsNonRoot: true", cwhere))
        if sc.get("allowPrivilegeEscalation") is not False:
            findings.append(Finding("K8S005", "error", "must set allowPrivilegeEscalation: false", cwhere))
        if sc.get("privileged"):
            findings.append(Finding("K8S008", "error", "privileged containers are not allowed", cwhere))
        if not sc.get("readOnlyRootFilesystem"):
            findings.append(Finding("K8S006", "warning", "consider readOnlyRootFilesystem: true", cwhere))
        if container in (pod.get("containers") or []):
            if "readinessProbe" not in container:
                findings.append(Finding("K8S007", "error", "readinessProbe is required", cwhere))
            if "livenessProbe" not in container:
                findings.append(Finding("K8S011", "warning", "livenessProbe is recommended", cwhere))
    return findings


def check_k8s_file(path: Path, policy: dict, tier: str | None) -> list[Finding]:
    try:
        docs = [d for d in yaml.safe_load_all(path.read_text()) if d]
    except yaml.YAMLError as exc:
        return [Finding("K8S000", "error", f"invalid YAML: {exc}", str(path))]
    findings: list[Finding] = []
    for doc in docs:
        findings += check_k8s_doc(doc, policy, tier, str(path))
    return findings


# --- Dockerfile ---------------------------------------------------------------------------
def check_dockerfile(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    stages: set[str] = set()
    last_user: str | None = None
    has_healthcheck = False
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        keyword, _, rest = line.partition(" ")
        keyword = keyword.upper()
        if keyword == "FROM":
            parts = rest.split()
            image = next((p for p in parts if not p.startswith("--")), "")
            if " as " in f" {rest.lower()} ":
                stages.add(parts[-1].lower())
            base = image.rsplit("/", 1)[-1]
            if (
                image.lower() not in stages
                and image != "scratch"
                and ("@sha256:" not in image and (":" not in base or base.endswith(":latest")))
            ):
                findings.append(
                    Finding("DOCK002", "error", f"base image {image!r} must use a pinned tag, not 'latest'", str(path))
                )
            last_user = None  # USER resets per stage
        elif keyword == "USER":
            last_user = rest.strip().split(":")[0]
        elif keyword == "HEALTHCHECK" and not rest.strip().upper().startswith("NONE"):
            has_healthcheck = True
    if last_user is None or last_user in {"root", "0"}:
        findings.append(Finding("DOCK001", "error", "final stage must set a non-root USER", str(path)))
    if not has_healthcheck:
        findings.append(
            Finding("DOCK003", "warning", "no HEALTHCHECK instruction (fine if the orchestrator probes it)", str(path))
        )
    return findings


# --- CI workflows -------------------------------------------------------------------------
def check_workflow(path: Path) -> list[Finding]:
    try:
        doc = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        return [Finding("CI000", "error", f"invalid YAML: {exc}", str(path))]
    findings: list[Finding] = []
    if isinstance(doc, dict) and "permissions" not in doc:
        findings.append(
            Finding("CI001", "warning", "workflow has no top-level `permissions:` (token defaults may be too broad)", str(path))
        )
    text = path.read_text()
    for match in re.finditer(r"uses:\s*([^\s#]+)", text):
        ref = match.group(1)
        if not ref.startswith("./") and "@" not in ref:
            findings.append(Finding("CI002", "error", f"action {ref!r} has no version pin", str(path)))
    return findings


# --- Whole repository ----------------------------------------------------------------------
def validate_repo(root: Path, policy: dict) -> tuple[ServiceSpec | None, list[Finding]]:
    spec_path = root / "service.yaml"
    if not spec_path.exists():
        return None, [Finding("SPEC000", "error", "no service.yaml found", str(root))]
    spec, findings = load_spec(spec_path)
    tier = spec.tier if spec else None

    for path in sorted((root / "k8s").rglob("*.y*ml")) if (root / "k8s").is_dir() else []:
        findings += check_k8s_file(path, policy, tier)
    dockerfile = root / "Dockerfile"
    if dockerfile.exists():
        findings += check_dockerfile(dockerfile)
    else:
        findings.append(Finding("DOCK000", "warning", "no Dockerfile found", str(root)))
    wf_dir = root / ".github" / "workflows"
    for path in sorted(wf_dir.glob("*.y*ml")) if wf_dir.is_dir() else []:
        findings += check_workflow(path)
    return spec, findings
