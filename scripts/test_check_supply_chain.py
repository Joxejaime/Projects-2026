"""Mutation tests: break one thing at a time and expect the guard to name it.

A checker nobody has watched fail is a checker you do not know works, so each case here is a
regression that has actually been proposed against this repository at least once.
"""

from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest

import check_supply_chain as guard

ROOT = pathlib.Path(__file__).resolve().parent.parent


class Sandbox(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / ".github" / "workflows").mkdir(parents=True)
        (self.tmp / "projects" / "demo").mkdir(parents=True)

    def workflow(self, body: str) -> None:
        (self.tmp / ".github" / "workflows" / "01-demo.yml").write_text(body)

    def requirements(self, body: str) -> None:
        (self.tmp / "projects" / "demo" / "requirements.txt").write_text(body)


class WorkflowPinning(Sandbox):
    GOOD = "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4\n"

    def test_sha_pin_passes(self) -> None:
        self.workflow(self.GOOD)
        self.assertEqual(guard.check_workflows(self.tmp), [])

    def test_mutable_tag_is_caught(self) -> None:
        """The exact regression Dependabot proposed in #16 and #17."""
        self.workflow("      - uses: actions/checkout@v4\n")
        problems = guard.check_workflows(self.tmp)
        self.assertEqual(len(problems), 1)
        self.assertIn("mutable tag", problems[0])

    def test_missing_version_is_caught(self) -> None:
        self.workflow("      - uses: actions/checkout\n")
        self.assertIn("no version at all", guard.check_workflows(self.tmp)[0])

    def test_short_sha_is_caught(self) -> None:
        self.workflow("      - uses: actions/checkout@11d5960\n")
        self.assertEqual(len(guard.check_workflows(self.tmp)), 1)

    def test_local_action_is_exempt(self) -> None:
        self.workflow("      - uses: ./.github/actions/thing\n")
        self.assertEqual(guard.check_workflows(self.tmp), [])

    def test_one_bad_pin_among_good_ones_is_found(self) -> None:
        self.workflow(self.GOOD + "      - uses: docker/login-action@v4\n" + self.GOOD)
        problems = guard.check_workflows(self.tmp)
        self.assertEqual(len(problems), 1)
        self.assertIn("docker/login-action", problems[0])


class ToolVersionPinning(Sandbox):
    """Pinning the action does not pin what the action downloads."""

    PINNED = (
        "      - uses: terraform-linters/setup-tflint@6ffdbaa3be476b3431f7275c26966ef32ff60337 # v6\n"
        "        with:\n"
        "          tflint_version: v0.64.0\n"
    )
    UNPINNED = "      - uses: terraform-linters/setup-tflint@6ffdbaa3be476b3431f7275c26966ef32ff60337 # v6\n"

    def test_pinned_tool_version_passes(self) -> None:
        self.workflow(self.PINNED)
        self.assertEqual(guard.check_tool_versions(self.tmp), [])

    def test_unpinned_tflint_is_caught(self) -> None:
        """The real regression: a TFLint release broke a green pipeline with no change here."""
        self.workflow(self.UNPINNED)
        problems = guard.check_tool_versions(self.tmp)
        self.assertEqual(len(problems), 1)
        self.assertIn("tflint_version", problems[0])

    def test_unpinned_terraform_is_caught(self) -> None:
        self.workflow("      - uses: hashicorp/setup-terraform@abc\n")
        self.assertIn("terraform_version", guard.check_tool_versions(self.tmp)[0])

    def test_a_later_step_does_not_satisfy_an_earlier_one(self) -> None:
        """The version input must belong to that step, not merely appear somewhere below it."""
        self.workflow(self.UNPINNED + "      - name: TFLint\n        run: tflint_version is not an input here\n")
        self.assertEqual(len(guard.check_tool_versions(self.tmp)), 1)

    def test_unrelated_actions_are_ignored(self) -> None:
        self.workflow("      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4\n")
        self.assertEqual(guard.check_tool_versions(self.tmp), [])


class RequirementPinning(Sandbox):
    def test_exact_pin_passes(self) -> None:
        self.requirements("pyyaml==6.0.3\njinja2==3.1.6\n")
        self.assertEqual(guard.check_requirements(self.tmp), [])

    def test_range_is_caught(self) -> None:
        """What merging #24 into main would have done."""
        self.requirements("pyyaml>=6.0.3,<7\n")
        self.assertIn("not pinned", guard.check_requirements(self.tmp)[0])

    def test_unbounded_is_caught(self) -> None:
        """ruff was unbounded, so any release could turn CI red."""
        self.requirements("ruff\n")
        self.assertEqual(len(guard.check_requirements(self.tmp)), 1)

    def test_comments_and_includes_are_skipped(self) -> None:
        self.requirements("# a comment\n\n-r requirements.txt\npytest==9.2.0\n")
        self.assertEqual(guard.check_requirements(self.tmp), [])

    def test_trailing_comment_does_not_hide_a_range(self) -> None:
        self.requirements("pyyaml>=6  # pinned later, honest\n")
        self.assertEqual(len(guard.check_requirements(self.tmp)), 1)


class RealRepository(unittest.TestCase):
    def test_this_repository_currently_passes(self) -> None:
        self.assertEqual(
            guard.check_workflows(ROOT) + guard.check_tool_versions(ROOT) + guard.check_requirements(ROOT),
            [],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
