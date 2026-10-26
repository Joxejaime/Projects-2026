import copy
import tempfile
import unittest
from pathlib import Path

import yaml

from platformctl.models import load_spec
from platformctl.policy import check_dockerfile, check_k8s_doc, check_workflow, load_policy

POLICY = load_policy(None)

GOOD = {
    "apiVersion": "apps/v1",
    "kind": "Deployment",
    "metadata": {
        "name": "x",
        "labels": {"app.kubernetes.io/name": "x", "platform.example/owner": "team-a", "platform.example/tier": "standard"},
    },
    "spec": {
        "replicas": 2,
        "template": {
            "spec": {
                "securityContext": {"runAsNonRoot": True},
                "containers": [
                    {
                        "name": "x",
                        "image": "ghcr.io/joxejaime/x:1.0.0",
                        "resources": {"requests": {"cpu": "1m", "memory": "1Mi"}, "limits": {"memory": "2Mi"}},
                        "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True},
                        "readinessProbe": {"httpGet": {"path": "/", "port": 1}},
                        "livenessProbe": {"httpGet": {"path": "/", "port": 1}},
                    }
                ],
            }
        },
    },
}


def mutate(fn):
    doc = copy.deepcopy(GOOD)
    fn(doc)
    return doc


def container(doc):
    return doc["spec"]["template"]["spec"]["containers"][0]


def rules(doc, tier="standard"):
    return {(f.rule, f.severity) for f in check_k8s_doc(doc, POLICY, tier, "t.yaml")}


class K8sPolicyTests(unittest.TestCase):
    def test_good_manifest_is_clean(self):
        self.assertEqual(rules(GOOD), set())

    def test_violations_are_detected(self):
        cases = {
            "latest tag": (lambda d: container(d).update(image="ghcr.io/joxejaime/x:latest"), ("K8S001", "error")),
            "untagged": (lambda d: container(d).update(image="ghcr.io/joxejaime/x"), ("K8S001", "error")),
            "foreign registry": (lambda d: container(d).update(image="evil.io/x:1"), ("K8S002", "error")),
            "no resources": (lambda d: container(d).pop("resources"), ("K8S003", "error")),
            "root": (lambda d: d["spec"]["template"]["spec"].pop("securityContext"), ("K8S004", "error")),
            "priv escalation": (lambda d: container(d)["securityContext"].pop("allowPrivilegeEscalation"), ("K8S005", "error")),
            "writable fs": (
                lambda d: container(d)["securityContext"].update(readOnlyRootFilesystem=False),
                ("K8S006", "warning"),
            ),
            "no readiness": (lambda d: container(d).pop("readinessProbe"), ("K8S007", "error")),
            "privileged": (lambda d: container(d)["securityContext"].update(privileged=True), ("K8S008", "error")),
            "host network": (lambda d: d["spec"]["template"]["spec"].update(hostNetwork=True), ("K8S008", "error")),
            "too few replicas": (lambda d: d["spec"].update(replicas=1), ("K8S009", "error")),
            "missing label": (lambda d: d["metadata"]["labels"].pop("platform.example/owner"), ("K8S010", "error")),
            "no liveness": (lambda d: container(d).pop("livenessProbe"), ("K8S011", "warning")),
        }
        for label, (change, expected) in cases.items():
            with self.subTest(label):
                self.assertIn(expected, rules(mutate(change)))

    def test_digest_pins_are_accepted(self):
        doc = mutate(lambda d: container(d).update(image="ghcr.io/joxejaime/x@sha256:" + "a" * 64))
        self.assertEqual(rules(doc), set())

    def test_replica_minimum_depends_on_tier(self):
        one_replica = mutate(lambda d: d["spec"].update(replicas=1))
        self.assertNotIn(("K8S009", "error"), rules(one_replica, tier="best-effort"))
        self.assertIn(("K8S009", "error"), rules(one_replica, tier="standard"))
        two = mutate(lambda d: d["spec"].update(replicas=2))
        self.assertIn(("K8S009", "error"), rules(two, tier="critical"))

    def test_non_workload_kinds_ignored(self):
        self.assertEqual(check_k8s_doc({"kind": "Service", "metadata": {"name": "s"}}, POLICY, "standard", "t"), [])

    def test_cronjob_pod_spec_is_found(self):
        cron = {
            "kind": "CronJob",
            "metadata": {"name": "c", "labels": GOOD["metadata"]["labels"]},
            "spec": {"jobTemplate": {"spec": {"template": {"spec": {"containers": [{"name": "c", "image": "busybox"}]}}}}},
        }
        found = {f.rule for f in check_k8s_doc(cron, POLICY, "standard", "t")}
        self.assertTrue({"K8S001", "K8S002", "K8S003", "K8S004"} <= found)

    def test_policy_override_changes_allowed_registries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.yaml"
            path.write_text(yaml.safe_dump({"allowed_registries": ["registry.corp.example/"]}))
            policy = load_policy(path)
            self.assertIn(("K8S002", "error"), {(f.rule, f.severity) for f in check_k8s_doc(GOOD, policy, "standard", "t")})
            path.write_text("bogus: 1")
            with self.assertRaises(ValueError):
                load_policy(path)


class DockerfileAndCiTests(unittest.TestCase):
    def dockerfile(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Dockerfile"
            path.write_text(text)
            return {(f.rule, f.severity) for f in check_dockerfile(path)}

    def test_good_dockerfile(self):
        self.assertEqual(self.dockerfile("FROM python:3.13-slim\nUSER 10001\nHEALTHCHECK CMD true\n"), set())

    def test_root_and_latest(self):
        found = self.dockerfile("FROM python:latest\nCMD x\n")
        self.assertTrue({("DOCK001", "error"), ("DOCK002", "error"), ("DOCK003", "warning")} <= found)

    def test_explicit_root_user_is_rejected(self):
        self.assertIn(("DOCK001", "error"), self.dockerfile("FROM python:3.13\nUSER root\nHEALTHCHECK CMD true\n"))

    def test_multistage_stage_alias_is_not_a_base_image(self):
        text = "FROM golang:1.23 AS build\nFROM build AS final\nUSER 1000\nHEALTHCHECK CMD true\n"
        self.assertEqual(self.dockerfile(text), set())

    def test_workflow_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ci.yml"
            path.write_text("on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n      - uses: actions/checkout\n")
            found = {f.rule for f in check_workflow(path)}
            self.assertEqual(found, {"CI001", "CI002"})


class SpecTests(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "service.yaml"
            path.write_text(text)
            spec, findings = load_spec(path)
            return spec, {f.rule for f in findings}

    def test_valid_spec_uses_tier_defaults(self):
        spec, rules_found = self.load("name: orders\nowner: team-orders\ntier: critical\n")
        self.assertEqual(rules_found, set())
        self.assertEqual((spec.replicas, spec.slo_availability), (3, 99.95))

    def test_invalid_specs(self):
        cases = {
            "name: Bad_Name\nowner: team-a\n": "SPEC002",
            "name: ok\nowner: alice\n": "SPEC003",
            "name: ok\nowner: team-a\ntier: gold\n": "SPEC004",
            "name: ok\nowner: team-a\ntypo: 1\n": "SPEC005",
            "name: ok\nowner: team-a\nport: 80\n": "SPEC006",
            "name: ok\n": "SPEC001",
            "name: ok\nowner: team-a\nenvironments: [qa]\n": "SPEC009",
            "name: ok\nowner: team-a\nslo: {availability: 100}\n": "SPEC010",
            "- a list\n": "SPEC000",
        }
        for text, expected in cases.items():
            with self.subTest(expected):
                spec, found = self.load(text)
                self.assertIsNone(spec)
                self.assertIn(expected, found)


if __name__ == "__main__":
    unittest.main()
