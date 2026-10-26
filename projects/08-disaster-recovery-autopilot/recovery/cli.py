"""Command line for the recovery tools (the commands drpilot playbooks call).

    snapshot      validate, dump, prove the dump restores, upload
    restore       restore the newest snapshot that proves itself
    restore-test  prove the newest snapshot restores; optionally write Prometheus textfile metrics
    validate      run the data checks against DATABASE_URL (optionally a write-path smoke test)
    list          snapshots in the store

DATABASE_URL names the database; BACKUP_STORE (or --store) is a directory or an s3://bucket/prefix.
Commands that measure something end with a JSON line {"facts": {...}} that drpilot copies into the postmortem.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from . import snapshots
from .pg import RecoveryError, database_url
from .store import open_store, snapshot_names
from .validate import format_checks, validate

METRIC_PREFIX = "drpilot_restore_test"


def facts_line(facts: dict) -> None:
    print(json.dumps({"facts": facts}))


def previous_success(path: Path) -> float | None:
    try:
        match = re.search(rf"^{METRIC_PREFIX}_last_success_timestamp_seconds (\S+)$", path.read_text(), re.MULTILINE)
    except OSError:
        return None
    return float(match.group(1)) if match else None


def write_metrics(path: Path, ok: bool, facts: dict, duration: float) -> None:
    """Prometheus textfile-collector format, so the existing Prometheus (project 04) can alert on it."""
    now = time.time()
    last_success = now if ok else previous_success(path)
    lines = [
        f"# HELP {METRIC_PREFIX}_success 1 if the newest snapshot restored and validated on the last run.",
        f"# TYPE {METRIC_PREFIX}_success gauge",
        f"{METRIC_PREFIX}_success {1 if ok else 0}",
        f"# HELP {METRIC_PREFIX}_last_run_timestamp_seconds Unix time of the last restore test.",
        f"# TYPE {METRIC_PREFIX}_last_run_timestamp_seconds gauge",
        f"{METRIC_PREFIX}_last_run_timestamp_seconds {now:.0f}",
        f"# HELP {METRIC_PREFIX}_duration_seconds How long the last restore test took (what a restore costs).",
        f"# TYPE {METRIC_PREFIX}_duration_seconds gauge",
        f"{METRIC_PREFIX}_duration_seconds {duration:.2f}",
    ]
    if last_success is not None:
        lines += [
            f"# HELP {METRIC_PREFIX}_last_success_timestamp_seconds Unix time of the last restore test that passed.",
            f"# TYPE {METRIC_PREFIX}_last_success_timestamp_seconds gauge",
            f"{METRIC_PREFIX}_last_success_timestamp_seconds {last_success:.0f}",
        ]
    if "snapshot_age_seconds" in facts:
        lines += [f"# TYPE {METRIC_PREFIX}_snapshot_age_seconds gauge", f"{METRIC_PREFIX}_snapshot_age_seconds {facts['snapshot_age_seconds']}"]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkstemp(dir=path.parent, prefix=".drpilot-", suffix=".tmp")[1])
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, path)  # the collector must never read a half-written file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="recover", description=__doc__.split("\n\n")[0])
    parser.add_argument("--store", default=os.environ.get("BACKUP_STORE"), help="directory or s3://bucket/prefix (default: $BACKUP_STORE)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--prefix", default="orders")
    s.add_argument("--unverified", action="store_true", help="skip validation (simulates a backup job without it; used by the drills)")
    sub.add_parser("restore")
    t = sub.add_parser("restore-test")
    t.add_argument("--metrics-file", type=Path, help="write Prometheus textfile-collector metrics here")
    t.add_argument("--max-age-seconds", type=float, help="fail if the newest snapshot is older than this (backups stopped)")
    v = sub.add_parser("validate")
    v.add_argument("--manifest", type=Path)
    v.add_argument("--smoke-url", help="also POST a test order through the service at this base URL")
    sub.add_parser("list")
    args = parser.parse_args(argv)

    started = time.monotonic()
    try:
        if args.cmd == "validate":
            manifest = json.loads(args.manifest.read_text()) if args.manifest else None
            checks, facts = validate(database_url(), manifest, args.smoke_url)
            print(format_checks(checks))
            facts_line(facts)
            return 0 if all(c.ok for c in checks) else 1
        if not args.store:
            raise RecoveryError("no backup store: set BACKUP_STORE or pass --store")
        store = open_store(args.store)
        if args.cmd == "list":
            for name in snapshot_names(store):
                print(name)
            return 0
        if args.cmd == "snapshot":
            manifest = snapshots.take(database_url(), store, prefix=args.prefix, verify=not args.unverified)
            facts_line({"snapshot": manifest["name"], "snapshot_created_at": manifest["created_at"], **{f"rows_{t}": n for t, n in manifest["tables"].items()}})
        elif args.cmd == "restore":
            facts_line(snapshots.restore(database_url(), store))
        else:  # restore-test
            try:
                facts = snapshots.restore_test(database_url(), store, args.max_age_seconds)
            except RecoveryError:
                if args.metrics_file:
                    write_metrics(args.metrics_file, False, {}, time.monotonic() - started)
                raise
            if args.metrics_file:
                write_metrics(args.metrics_file, True, facts, facts["restore_test_seconds"])
            facts_line(facts)
    except (RecoveryError, OSError) as err:
        print(f"{args.cmd} failed: {err}", file=sys.stderr)
        return 1
    return 0
