#!/usr/bin/env python3
"""Static wiring check for the Terraform modules (no providers or network needed).

`terraform validate` needs provider plugins, which are not always reachable (air-gapped
laptops, restricted CI runners, sandboxes). This script catches the most common
module-wiring mistakes without them:

  * a module call passes an argument the module does not declare
  * a module call omits a required variable (one with no default)
  * a reference like module.foo.bar points at an output that does not exist
  * a var.xxx reference in an environment has no matching variable block

It is a *complement* to `terraform validate`, not a replacement; CI runs both.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def blocks(text: str, keyword: str) -> dict[str, str]:
    """Return {label: body} for top-level `keyword "label" { ... }` blocks (brace matched)."""
    found: dict[str, str] = {}
    for match in re.finditer(rf'^{keyword}\s+"([^"]+)"\s*\{{', text, re.MULTILINE):
        depth, i = 1, match.end()
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        found[match.group(1)] = text[match.end() : i - 1]
    return found


def read_dir(path: Path) -> str:
    return "\n".join(p.read_text() for p in sorted(path.glob("*.tf")))


def top_level_keys(body: str) -> set[str]:
    """Argument names at nesting depth 0 of a block body."""
    keys, depth = set(), 0
    for line in body.splitlines():
        stripped = line.strip()
        if depth == 0:
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", stripped)
            if m:
                keys.add(m.group(1))
        depth += stripped.count("{") + stripped.count("[") + stripped.count("(")
        depth -= stripped.count("}") + stripped.count("]") + stripped.count(")")
    return keys


def check_environment(env_dir: Path) -> list[str]:
    errors: list[str] = []
    text = read_dir(env_dir)
    declared_vars = set(blocks(text, "variable"))

    for name in sorted(set(re.findall(r"\bvar\.([A-Za-z_][A-Za-z0-9_]*)", text)) - declared_vars):
        errors.append(f"{env_dir.name}: var.{name} is used but never declared")

    module_outputs: dict[str, set[str]] = {}
    for label, body in blocks(text, "module").items():
        source = re.search(r'source\s*=\s*"([^"]+)"', body)
        if not source:
            errors.append(f"{env_dir.name}: module.{label} has no source")
            continue
        module_dir = (env_dir / source.group(1)).resolve()
        module_text = read_dir(module_dir)
        variables = blocks(module_text, "variable")
        required = {name for name, vbody in variables.items() if not re.search(r"^\s*default\s*=", vbody, re.MULTILINE)}
        passed = top_level_keys(body) - {"source", "version", "providers", "count", "for_each", "depends_on"}
        for name in sorted(passed - set(variables)):
            errors.append(f"{env_dir.name}: module.{label} passes undeclared variable '{name}'")
        for name in sorted(required - passed):
            errors.append(f"{env_dir.name}: module.{label} is missing required variable '{name}'")
        module_outputs[label] = set(blocks(module_text, "output"))

    for label, attr in re.findall(r"\bmodule\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_]+)", text):
        if label not in module_outputs:
            errors.append(f"{env_dir.name}: reference to unknown module.{label}")
        elif attr not in module_outputs[label]:
            errors.append(f"{env_dir.name}: module.{label}.{attr} is not an output of that module")
    return errors


def main() -> int:
    errors: list[str] = []
    envs = sorted(p for p in (ROOT / "envs").iterdir() if p.is_dir())
    for env in envs:
        errors += check_environment(env)
    if errors:
        print("Wiring errors:")
        for err in errors:
            print(f"  - {err}")
        return 1
    print(f"OK: {len(envs)} environments, module wiring consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
