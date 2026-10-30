#!/usr/bin/env python3
"""Fail if the supply-chain pinning has regressed.

Two rules, both learned the hard way:

  1. Every `uses:` in a workflow names a 40-character commit SHA, not a tag. Tags are mutable:
     the publisher can repoint them, and several of these actions run in jobs holding
     `contents: write` or `packages: write`.

  2. Every setup action that downloads a tool pins the tool's version. Pinning the action does not
     pin what it installs: `setup-tflint` defaults to the latest TFLint, which is how a green
     pipeline broke overnight with no change to this repository.

  3. Every dependency in a requirements file is pinned with `==`. An unbounded `ruff` turns CI
     red on someone else's release schedule.

Dependabot has twice proposed changes that would undo rule 1, because its branch was cut before
the pins landed. This check makes that impossible to merge by accident rather than relying on a
reviewer noticing a SHA turning back into a tag.

`pyproject.toml` is deliberately NOT checked: a package's declared dependencies belong as
ranges, while the reproducible install is what gets pinned.

    python3 scripts/check_supply_chain.py        # from the repository root
"""

from __future__ import annotations

import pathlib
import re
import sys

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
USES_RE = re.compile(r"^\s*-?\s*uses:\s*(\S+)")
# Local actions (./.github/...) and docker:// references are not tag-pinnable the same way.
EXEMPT_PREFIXES = ("./", "docker://")


def check_workflows(root: pathlib.Path) -> list[str]:
    problems = []
    for wf in sorted((root / ".github" / "workflows").glob("*.yml")):
        for n, line in enumerate(wf.read_text().splitlines(), 1):
            m = USES_RE.match(line)
            if not m:
                continue
            ref = m.group(1)
            if ref.startswith(EXEMPT_PREFIXES):
                continue
            if "@" not in ref:
                problems.append(f"{wf.relative_to(root)}:{n}: '{ref}' has no version at all")
                continue
            version = ref.rsplit("@", 1)[1]
            if not SHA_RE.match(version):
                problems.append(
                    f"{wf.relative_to(root)}:{n}: '{ref}' is pinned to the mutable tag "
                    f"'{version}'; use the commit SHA with the tag as a trailing comment"
                )
    return problems


# Actions that download a tool and default to "latest" unless told otherwise. Pinning the action
# does not pin what it installs, which is how a TFLint release once broke a green pipeline.
TOOL_SETUP_ACTIONS = {
    "terraform-linters/setup-tflint": "tflint_version",
    "hashicorp/setup-terraform": "terraform_version",
    "opentofu/setup-opentofu": "tofu_version",
}


def check_tool_versions(root: pathlib.Path) -> list[str]:
    problems = []
    for wf in sorted((root / ".github" / "workflows").glob("*.yml")):
        lines = wf.read_text().splitlines()
        for n, line in enumerate(lines):
            m = USES_RE.match(line)
            if not m:
                continue
            action = m.group(1).split("@", 1)[0]
            key = TOOL_SETUP_ACTIONS.get(action)
            if not key:
                continue
            # Look ahead over this step's `with:` block for the version input.
            block = []
            for nxt in lines[n + 1 :]:
                if USES_RE.match(nxt) or re.match(r"^\s*- name:", nxt):
                    break
                block.append(nxt)
            if not any(f"{key}:" in b for b in block):
                problems.append(
                    f"{wf.relative_to(root)}:{n + 1}: '{action}' does not set '{key}', so it "
                    f"installs the latest release and the job is not reproducible"
                )
    return problems


def check_requirements(root: pathlib.Path) -> list[str]:
    problems = []
    for req in sorted(root.glob("projects/*/requirements*.txt")):
        for n, raw in enumerate(req.read_text().splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-r "):
                continue
            if "==" not in line:
                problems.append(
                    f"{req.relative_to(root)}:{n}: '{line}' is not pinned; use '=='"
                )
    return problems


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent.parent
    problems = check_workflows(root) + check_tool_versions(root) + check_requirements(root)
    if problems:
        print(f"Supply-chain guard: {len(problems)} problem(s)\n", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print(
            "\nIf a Dependabot pull request caused this, it was branched before the pins "
            "landed. Apply the version bump as a SHA pin instead of merging the tag.",
            file=sys.stderr,
        )
        return 1
    print("Supply-chain guard: actions SHA-pinned, tool versions pinned, requirements pinned with ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
