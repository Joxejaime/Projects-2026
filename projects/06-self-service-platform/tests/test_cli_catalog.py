import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from platformctl.cli import main


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as exc:  # argparse errors
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def test_new_then_validate_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "billing-api")
            code, out, _ = run("new", "billing-api", "--owner", "team-billing", "--tier", "critical", "--out", target)
            self.assertEqual(code, 0)
            self.assertIn("tier=critical", out)
            code, out, _ = run("validate", target)
            self.assertEqual(code, 0, out)
            self.assertIn("0 error(s)", out)

    def test_validate_fails_on_broken_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "svc"
            run("new", "svc", "--owner", "team-a", "--out", str(target))
            deployment = target / "k8s/deployment.yaml"
            deployment.write_text(deployment.read_text().replace(":0.1.0", ":latest"))
            code, out, _ = run("validate", str(target), "--format", "json")
            self.assertEqual(code, 1)
            self.assertIn("K8S001", [f["rule"] for f in json.loads(out)["findings"]])

    def test_strict_mode_fails_on_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "svc"
            run("new", "svc", "--owner", "team-a", "--out", str(target))
            (target / "Dockerfile").write_text((target / "Dockerfile").read_text().split("HEALTHCHECK")[0] + "USER 10001\n")
            self.assertEqual(run("validate", str(target))[0], 0)
            self.assertEqual(run("validate", str(target), "--strict")[0], 1)

    def test_bad_new_arguments_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run("new", "Bad Name", "--owner", "bob", "--out", str(Path(tmp) / "x"))
            self.assertEqual(code, 2)
            self.assertIn("SPEC002", err)

    def test_env_add(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = ("env", "add", "--service", "svc", "--env", "dev", "--repo", "o/r", "--owner", "team-a", "--out", tmp)
            self.assertEqual(run(*args)[0], 0)
            self.assertEqual(run(*args)[0], 2)  # exists
            self.assertTrue((Path(tmp) / "svc-dev.tf").exists())


class CatalogTests(unittest.TestCase):
    def build_fleet(self, tmp):
        for name, owner, tier in [
            ("alpha", "team-a", "critical"),
            ("beta", "team-a", "standard"),
            ("gamma", "team-b", "best-effort"),
        ]:
            run("new", name, "--owner", owner, "--tier", tier, "--out", str(Path(tmp) / "services" / name))

    def test_markdown_catalog_summarises_fleet(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build_fleet(tmp)
            code, out, _ = run("catalog", tmp)
            self.assertEqual(code, 0)
            self.assertIn("3 valid service(s)", out)
            self.assertIn("| alpha | team-a | critical | 99.95% | 3 |", out)
            self.assertIn("**By owner:** team-a: 2, team-b: 1", out)

    def test_json_catalog_and_problem_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build_fleet(tmp)
            (Path(tmp) / "services" / "broken").mkdir()
            (Path(tmp) / "services" / "broken" / "service.yaml").write_text("name: Broken Name\nowner: me\n")
            run("new", "alpha", "--owner", "team-z", "--out", str(Path(tmp) / "services2" / "alpha"))
            code, out, _ = run("catalog", tmp, "--format", "json")
            data = json.loads(out)
            self.assertEqual(code, 1)
            self.assertEqual(len(data["services"]), 5)
            rules = {f["rule"] for s in data["services"] for f in s["findings"]}
            self.assertTrue({"SPEC002", "SPEC003", "CAT001"} <= rules)


if __name__ == "__main__":
    unittest.main()
