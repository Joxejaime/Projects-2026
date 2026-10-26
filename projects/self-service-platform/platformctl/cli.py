"""platformctl command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .catalog import collect, to_json, to_markdown
from .models import TIER_DEFAULTS, ServiceSpec, validate_fields
from .policy import load_policy, validate_repo
from .scaffold import ScaffoldError, render_environment, render_service


def cmd_new(args: argparse.Namespace) -> int:
    findings = validate_fields(args.name, args.owner, args.tier, args.port)
    if findings:
        for f in findings:
            print(f.format(), file=sys.stderr)
        return 2
    spec = ServiceSpec(name=args.name, owner=args.owner, tier=args.tier, port=args.port, registry=args.registry)
    out = Path(args.out) if args.out else Path(args.name)
    try:
        files = render_service(spec, out, force=args.force)
    except ScaffoldError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Created {spec.name} (tier={spec.tier}, owner={spec.owner}) in {out}/ with {len(files)} files:")
    for path in files:
        print(f"  {path.relative_to(out)}")
    print(f"\nNext: cd {out} && git init && python -m platformctl validate .")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        policy = load_policy(Path(args.policy) if args.policy else None)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    root = Path(args.path)
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    spec, findings = validate_repo(root, policy)
    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]
    if args.format == "json":
        print(json.dumps({"service": spec.name if spec else None, "findings": [f.as_dict() for f in findings]}, indent=2))
    else:
        for f in findings:
            print(f.format())
        label = spec.name if spec else str(root)
        print(f"\n{label}: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors or (args.strict and warnings) else 0


def cmd_catalog(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    entries = collect(root)
    print(to_json(entries, root) if args.format == "json" else to_markdown(entries, root), end="")
    return 1 if any(f.severity == "error" for e in entries for f in e.findings) else 0


def cmd_env_add(args: argparse.Namespace) -> int:
    try:
        target = render_environment(
            args.service, args.env, args.repo, args.owner, args.tier, args.budget, Path(args.out), args.force
        )
    except ScaffoldError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote {target}\nOpen a pull request; `terraform plan` runs in CI and a platform engineer approves the apply.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="platformctl", description="Self-service golden paths and guardrails.")
    parser.add_argument("--version", action="version", version=f"platformctl {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="scaffold a new service repository from the golden path")
    new.add_argument("name")
    new.add_argument("--owner", required=True, help="owning team, e.g. team-orders")
    new.add_argument("--tier", default="standard", choices=sorted(TIER_DEFAULTS))
    new.add_argument("--port", type=int, default=8080)
    new.add_argument("--registry", default="ghcr.io/joxejaime")
    new.add_argument("--out", help="output directory (default: ./<name>)")
    new.add_argument("--force", action="store_true")
    new.set_defaults(func=cmd_new)

    val = sub.add_parser("validate", help="check a service repository against platform policy")
    val.add_argument("path", nargs="?", default=".")
    val.add_argument("--policy", help="policy YAML overriding the defaults")
    val.add_argument("--format", choices=["text", "json"], default="text")
    val.add_argument("--strict", action="store_true", help="treat warnings as failures")
    val.set_defaults(func=cmd_validate)

    cat = sub.add_parser("catalog", help="list every service found under a directory")
    cat.add_argument("path", nargs="?", default=".")
    cat.add_argument("--format", choices=["md", "json"], default="md")
    cat.set_defaults(func=cmd_catalog)

    env = sub.add_parser("env", help="request cloud environments")
    env_sub = env.add_subparsers(dest="env_command", required=True)
    add = env_sub.add_parser("add", help="generate the Terraform for a service environment")
    add.add_argument("--service", required=True)
    add.add_argument("--env", required=True, help="dev | staging | prod")
    add.add_argument("--repo", required=True, help="GitHub repository allowed to deploy, org/name")
    add.add_argument("--owner", required=True)
    add.add_argument("--tier", default="standard", choices=sorted(TIER_DEFAULTS))
    add.add_argument("--budget", type=int, default=50, help="monthly budget alert in USD")
    add.add_argument("--out", default="infra/services")
    add.add_argument("--force", action="store_true")
    add.set_defaults(func=cmd_env_add)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
