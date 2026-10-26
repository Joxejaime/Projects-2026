import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from platformctl.models import ServiceSpec
from platformctl.policy import load_policy, validate_repo
from platformctl.scaffold import ScaffoldError, render_environment, render_service

EXPECTED_FILES = {
    "service.yaml", "README.md", "CODEOWNERS", "Dockerfile", ".dockerignore", ".gitignore",
    "app/__init__.py", "app/main.py", "tests/__init__.py", "tests/test_app.py",
    "k8s/deployment.yaml", ".github/workflows/ci.yml", "docs/runbook.md",
}  # fmt: skip


class ScaffoldTests(unittest.TestCase):
    def scaffold(self, tmp, tier="standard", name="orders-api"):
        spec = ServiceSpec(name=name, owner="team-orders", tier=tier)
        out = Path(tmp) / name
        render_service(spec, out)
        return spec, out

    def test_creates_every_golden_path_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self.scaffold(tmp)
            created = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
            self.assertEqual(created, EXPECTED_FILES)

    def test_generated_repo_passes_platform_policy_for_every_tier(self):
        for tier in ("critical", "standard", "best-effort"):
            with self.subTest(tier=tier), tempfile.TemporaryDirectory() as tmp:
                _, out = self.scaffold(tmp, tier=tier)
                _, findings = validate_repo(out, load_policy(None))
                errors = [f.format() for f in findings if f.severity == "error"]
                self.assertEqual(errors, [])

    def test_generated_yaml_is_valid_and_reflects_tier(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self.scaffold(tmp, tier="critical")
            docs = list(yaml.safe_load_all((out / "k8s/deployment.yaml").read_text()))
            kinds = [d["kind"] for d in docs]
            self.assertEqual(kinds, ["Deployment", "Service", "PodDisruptionBudget"])
            self.assertEqual(docs[0]["spec"]["replicas"], 3)
            ci = yaml.safe_load((out / ".github/workflows/ci.yml").read_text())
            self.assertIn("test", ci["jobs"])
            self.assertIn("${{ github.ref }}", ci["concurrency"]["group"])  # GH expressions survive templating

    def test_best_effort_has_no_pdb(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self.scaffold(tmp, tier="best-effort")
            kinds = [d["kind"] for d in yaml.safe_load_all((out / "k8s/deployment.yaml").read_text())]
            self.assertEqual(kinds, ["Deployment", "Service"])

    def test_generated_service_tests_actually_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self.scaffold(tmp)
            result = subprocess.run(  # noqa: S603
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                cwd=out, capture_output=True, text=True, timeout=60, check=False,
            )  # fmt: skip
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_refuses_to_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec, out = self.scaffold(tmp)
            with self.assertRaises(ScaffoldError):
                render_service(spec, out)
            render_service(spec, out, force=True)


class EnvironmentTests(unittest.TestCase):
    def test_renders_module_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = render_environment("orders-api", "dev", "Joxejaime/orders-api", "team-orders", "standard", 75, Path(tmp))
            text = path.read_text()
            self.assertEqual(path.name, "orders-api-dev.tf")
            for expected in (
                'module "orders_api_dev"',
                'github_repo = "Joxejaime/orders-api"',
                "monthly_budget_usd       = 75",
            ):
                self.assertIn(expected, text)

    def test_rejects_bad_input_and_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ScaffoldError):
                render_environment("Bad_Name", "qa", "not-a-repo", "owner", "gold", 0, Path(tmp))
            render_environment("svc", "dev", "o/r", "team-x", "standard", 10, Path(tmp))
            with self.assertRaises(ScaffoldError):
                render_environment("svc", "dev", "o/r", "team-x", "standard", 10, Path(tmp))


if __name__ == "__main__":
    unittest.main()
