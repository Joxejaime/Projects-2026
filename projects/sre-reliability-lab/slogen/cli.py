"""slogen command line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .model import load_slo_file
from .rules import render
from .simulate import Incident, budget_report, minutes, simulate


def _load_all(paths: list[str]):
    slos, errors = [], []
    for p in paths:
        s, e = load_slo_file(Path(p))
        slos += s
        errors += e
    return slos, errors


def cmd_check(args: argparse.Namespace) -> int:
    slos, errors = _load_all(args.files)
    for e in errors:
        print(f"ERROR {e}", file=sys.stderr)
    if errors:
        return 1
    print(f"OK: {len(slos)} SLO(s) valid")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    slos, errors = _load_all([args.file])
    if errors:
        for e in errors:
            print(f"ERROR {e}", file=sys.stderr)
        return 1
    text = render(slos, args.file)
    if args.check:
        current = Path(args.output).read_text() if Path(args.output).exists() else None
        if current != text:
            print(f"STALE: {args.output} does not match {args.file}; run `make generate`", file=sys.stderr)
            return 1
        print(f"OK: {args.output} is up to date")
        return 0
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(text)
    print(f"Wrote {args.output} ({len(slos)} SLO(s))")
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    incident = Incident(start=args.start_minute, duration=args.duration, error_ratio=args.error_ratio)
    results = simulate(args.objective, args.window, incident)
    allowed = 1 - args.objective / 100
    print(
        f"SLO {args.objective:g}% over {args.window} (error budget {allowed:.4%}); incident: "
        f"{args.error_ratio:.1%} errors for {args.duration} min (burn rate {args.error_ratio / allowed:.1f}x)\n"
    )
    print(
        f"{'policy':<13}{'severity':<9}{'threshold':>10}  {'fires?':<7}{'after':>8}  {'budget used at alert':>21}  {'clears after end':>17}"
    )
    for r in results:
        if r.fired:
            row = (
                f"{r.detection_delay:>5} min  {r.budget_consumed_at_detection:>20.2%}  "
                f"{(str(r.resolved_after_end) + ' min') if r.resolved_after_end is not None else 'n/a':>17}"
            )
        else:
            row = f"{'-':>8}  {'-':>21}  {'-':>17}"
        print(f"{r.policy.name:<13}{r.policy.severity:<9}{r.threshold:>10.5f}  {'yes' if r.fired else 'no':<7}{row}")
    total = incident.error_ratio * incident.duration / (minutes(args.window) * allowed)
    print(f"\nTotal error budget consumed by the incident: {total:.2%}")
    return 0


def cmd_budget(args: argparse.Namespace) -> int:
    try:
        r = budget_report(args.objective, args.window, args.good, args.total)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"SLI achieved:        {r['sli']:.4%}  (objective {r['objective']:.2%}, {'MET' if r['met'] else 'MISSED'})")
    print(f"Bad events:          {r['bad_events']:,} of {r['allowed_bad_events']:,.0f} allowed")
    print(f"Budget consumed:     {r['budget_consumed']:.1%}")
    print(f"Budget remaining:    {r['budget_remaining']:.1%}")
    print(f"Full-outage minutes allowed per {args.window}: {r['full_outage_minutes_allowed']:.1f}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="slogen", description="SLOs as code: rules, simulation, budgets.")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="validate SLO definition files")
    check.add_argument("files", nargs="+")
    check.set_defaults(func=cmd_check)

    gen = sub.add_parser("generate", help="generate Prometheus rules from an SLO file")
    gen.add_argument("file")
    gen.add_argument("-o", "--output", required=True)
    gen.add_argument("--check", action="store_true", help="fail if the output file is stale")
    gen.set_defaults(func=cmd_generate)

    sim = sub.add_parser("simulate", help="replay an incident through the alert policies")
    sim.add_argument("--objective", type=float, default=99.9, help="percent, e.g. 99.9")
    sim.add_argument("--window", default="30d")
    sim.add_argument("--start-minute", type=int, default=0)
    sim.add_argument("--duration", type=int, required=True, help="incident length in minutes")
    sim.add_argument("--error-ratio", type=float, required=True, help="fraction of requests failing, 0-1")
    sim.set_defaults(func=cmd_simulate)

    bud = sub.add_parser("budget", help="error budget status from event counts")
    bud.add_argument("--objective", type=float, required=True)
    bud.add_argument("--window", default="30d")
    bud.add_argument("--good", type=int, required=True)
    bud.add_argument("--total", type=int, required=True)
    bud.set_defaults(func=cmd_budget)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
