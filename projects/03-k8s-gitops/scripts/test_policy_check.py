"""Tests prove the policy checker actually rejects bad manifests (not just passes good ones)."""

import copy
import os
import subprocess
import sys
import unittest

import yaml

sys.path.insert(0, os.path.dirname(__file__))
import policy_check

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def render(overlay: str) -> list[dict]:
    out = subprocess.run(
        ["kustomize", "build", os.path.join(ROOT, "k8s", "overlays", overlay)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def deployment(docs):
    return next(d for d in docs if d["kind"] == "Deployment")


class TestPolicyCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.good = {env: render(env) for env in ("dev", "prod")}

    def test_real_overlays_pass(self):
        for env, docs in self.good.items():
            with self.subTest(env=env):
                self.assertEqual(policy_check.check(docs), [])

    def mutate(self, fn):
        docs = copy.deepcopy(self.good["prod"])
        fn(docs)
        return policy_check.check(docs)

    def container(self, docs):
        return deployment(docs)["spec"]["template"]["spec"]["containers"][0]

    def test_rejects_root(self):
        def fn(docs):
            deployment(docs)["spec"]["template"]["spec"]["securityContext"]["runAsNonRoot"] = False

        self.assertTrue(any("runAsNonRoot" in e for e in self.mutate(fn)))

    def test_rejects_writable_rootfs(self):
        errs = self.mutate(lambda d: self.container(d)["securityContext"].update(readOnlyRootFilesystem=False))
        self.assertTrue(any("readOnlyRootFilesystem" in e for e in errs))

    def test_rejects_latest_tag(self):
        errs = self.mutate(lambda d: self.container(d).update(image="ghcr.io/x/y:latest"))
        self.assertTrue(any("pinned" in e for e in errs))

    def test_rejects_untagged_image(self):
        errs = self.mutate(lambda d: self.container(d).update(image="ghcr.io/x/y"))
        self.assertTrue(any("pinned" in e for e in errs))

    def test_accepts_digest_pin(self):
        errs = self.mutate(lambda d: self.container(d).update(image="ghcr.io/x/y@sha256:" + "a" * 64))
        self.assertFalse(any("pinned" in e for e in errs))

    def test_rejects_missing_limits(self):
        errs = self.mutate(lambda d: self.container(d)["resources"].pop("limits"))
        self.assertTrue(any("limits.cpu" in e for e in errs))

    def test_rejects_missing_probe(self):
        errs = self.mutate(lambda d: self.container(d).pop("readinessProbe"))
        self.assertTrue(any("readinessProbe" in e for e in errs))

    def test_rejects_privilege_escalation(self):
        errs = self.mutate(lambda d: self.container(d)["securityContext"].update(allowPrivilegeEscalation=True))
        self.assertTrue(any("allowPrivilegeEscalation" in e for e in errs))

    def test_rejects_missing_default_deny(self):
        def fn(docs):
            docs[:] = [d for d in docs if not (d["kind"] == "NetworkPolicy" and d["metadata"]["name"] == "default-deny-all")]

        self.assertTrue(any("default-deny" in e for e in self.mutate(fn)))

    def test_rejects_missing_hpa_and_pdb(self):
        errs = self.mutate(lambda d: d.__setitem__(slice(None), [x for x in d if x["kind"] not in ("HorizontalPodAutoscaler", "PodDisruptionBudget")]))
        self.assertTrue(any("HorizontalPodAutoscaler" in e for e in errs))
        self.assertTrue(any("PodDisruptionBudget" in e for e in errs))

    def test_rejects_weak_pod_security_label(self):
        def fn(docs):
            ns = next(d for d in docs if d["kind"] == "Namespace")
            ns["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] = "baseline"

        self.assertTrue(any("restricted" in e for e in self.mutate(fn)))

    def test_rejects_ingress_without_tls(self):
        def fn(docs):
            next(d for d in docs if d["kind"] == "Ingress")["spec"].pop("tls")

        self.assertTrue(any("spec.tls" in e for e in self.mutate(fn)))

    def test_rejects_ingress_host_missing_from_tls(self):
        def fn(docs):
            next(d for d in docs if d["kind"] == "Ingress")["spec"]["tls"][0]["hosts"] = ["other.example.com"]

        self.assertTrue(any("spec.tls" in e for e in self.mutate(fn)))

    def test_rejects_host_network(self):
        errs = self.mutate(lambda d: deployment(d)["spec"]["template"]["spec"].update(hostNetwork=True))
        self.assertTrue(any("host namespaces" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
