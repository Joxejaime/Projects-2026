#!/usr/bin/env python3
"""Policy-as-code checks for rendered Kubernetes manifests (stdlib + PyYAML).

Usage:  kustomize build k8s/overlays/prod | python3 scripts/policy_check.py

Checks, per workload container: non-root, read-only root fs, no privilege escalation,
all capabilities dropped, RuntimeDefault seccomp, resource requests+limits, probes,
pinned image tag (no :latest). Per namespace: a default-deny NetworkPolicy exists and
the Namespace enforces Pod Security "restricted". Per Deployment: an HPA and a PDB.

It exists so the guardrails are executable and unit-tested (see test_policy_check.py),
and so the same rules run locally, in CI and before an Argo CD sync.
"""

from __future__ import annotations

import sys

import yaml

WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet"}


def pod_spec(doc: dict) -> dict:
    return doc.get("spec", {}).get("template", {}).get("spec", {})


def check_container(workload: str, pod: dict, container: dict) -> list[str]:
    name = f"{workload}/{container.get('name', '?')}"
    errs: list[str] = []
    sc = container.get("securityContext", {})
    pod_sc = pod.get("securityContext", {})

    if not (sc.get("runAsNonRoot") or pod_sc.get("runAsNonRoot")):
        errs.append(f"{name}: runAsNonRoot must be true")
    if sc.get("readOnlyRootFilesystem") is not True:
        errs.append(f"{name}: readOnlyRootFilesystem must be true")
    if sc.get("allowPrivilegeEscalation") is not False:
        errs.append(f"{name}: allowPrivilegeEscalation must be false")
    if "ALL" not in sc.get("capabilities", {}).get("drop", []):
        errs.append(f"{name}: capabilities must drop ALL")
    seccomp = (sc.get("seccompProfile") or pod_sc.get("seccompProfile") or {}).get("type")
    if seccomp not in ("RuntimeDefault", "Localhost"):
        errs.append(f"{name}: seccompProfile must be RuntimeDefault or Localhost")
    if sc.get("privileged"):
        errs.append(f"{name}: privileged containers are not allowed")

    resources = container.get("resources", {})
    for kind in ("requests", "limits"):
        for res in ("cpu", "memory"):
            if res not in resources.get(kind, {}):
                errs.append(f"{name}: resources.{kind}.{res} is required")

    for probe in ("livenessProbe", "readinessProbe"):
        if probe not in container:
            errs.append(f"{name}: {probe} is required")

    image = container.get("image", "")
    tag = image.rsplit(":", 1)[1] if ":" in image.rsplit("/", 1)[-1] else ""
    if "@sha256:" not in image and (not tag or tag == "latest"):
        errs.append(f"{name}: image must be pinned to a tag or digest, not '{tag or 'latest'}'")
    return errs


def check(docs: list[dict]) -> list[str]:
    errs: list[str] = []
    by_kind: dict[str, list[dict]] = {}
    for doc in docs:
        by_kind.setdefault(doc["kind"], []).append(doc)

    for doc in docs:
        if doc["kind"] not in WORKLOADS:
            continue
        pod = pod_spec(doc)
        label = f"{doc['kind']}/{doc['metadata']['name']}"
        if pod.get("automountServiceAccountToken") is not False:
            errs.append(f"{label}: automountServiceAccountToken must be false unless the app needs the API")
        if pod.get("hostNetwork") or pod.get("hostPID") or pod.get("hostIPC"):
            errs.append(f"{label}: host namespaces are not allowed")
        for container in pod.get("containers", []) + pod.get("initContainers", []):
            errs += check_container(label, pod, container)

        if doc["kind"] == "Deployment":
            name = doc["metadata"]["name"]
            if not any(h["spec"]["scaleTargetRef"]["name"] == name for h in by_kind.get("HorizontalPodAutoscaler", [])):
                errs.append(f"{label}: no HorizontalPodAutoscaler targets this Deployment")
            labels = doc["spec"]["selector"]["matchLabels"]
            if not any(
                labels.items() <= p["spec"]["selector"].get("matchLabels", {}).items()
                or p["spec"]["selector"].get("matchLabels", {}).items() <= labels.items()
                for p in by_kind.get("PodDisruptionBudget", [])
            ):
                errs.append(f"{label}: no PodDisruptionBudget selects this Deployment")

    for ing in by_kind.get("Ingress", []):
        label = f"Ingress/{ing['metadata']['name']}"
        tls_hosts = {h for entry in ing["spec"].get("tls", []) for h in entry.get("hosts", [])}
        for rule in ing["spec"].get("rules", []):
            if rule.get("host") not in tls_hosts:
                errs.append(f"{label}: host {rule.get('host')!r} is not covered by a spec.tls entry (plain HTTP)")

    namespaces = {d["metadata"]["name"]: d for d in by_kind.get("Namespace", [])}
    used = {d["metadata"].get("namespace") for d in docs if d["kind"] in WORKLOADS}
    for ns in sorted(n for n in used if n):
        netpols = [p for p in by_kind.get("NetworkPolicy", []) if p["metadata"].get("namespace") == ns]
        has_default_deny = any(
            p["spec"].get("podSelector") == {} and {"Ingress", "Egress"} <= set(p["spec"].get("policyTypes", []))
            for p in netpols
        )
        if not has_default_deny:
            errs.append(f"namespace {ns}: missing default-deny NetworkPolicy (ingress and egress)")
        labels = namespaces.get(ns, {}).get("metadata", {}).get("labels", {})
        if labels.get("pod-security.kubernetes.io/enforce") != "restricted":
            errs.append(f"namespace {ns}: must enforce Pod Security 'restricted'")
    return errs


def main() -> int:
    docs = [d for d in yaml.safe_load_all(sys.stdin) if d]
    errs = check(docs)
    if errs:
        print(f"FAILED: {len(errs)} policy violation(s)")
        for err in errs:
            print(f"  - {err}")
        return 1
    workloads = sum(1 for d in docs if d["kind"] in WORKLOADS)
    print(f"OK: {len(docs)} resources, {workloads} workload(s) satisfy policy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
