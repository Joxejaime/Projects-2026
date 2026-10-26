"""Take, restore and test snapshots. A snapshot only counts once it has been restored and validated.

take          validate the live data, pg_dump it, restore the dump into a scratch database to prove it
              restores and to measure what is inside it, then upload dump and manifest
restore       newest snapshot first: checksum it, restore it into a scratch database, validate it against its
              manifest; the first that passes is restored over the live database and validated again
restore_test  the same proof on the newest snapshot, without touching live data, with timings
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .pg import RecoveryError, dbname_of, run_tool, scratch_database
from .store import DUMP_SUFFIX, MANIFEST_SUFFIX, LocalStore, S3Store, check_name, snapshot_names
from .validate import TABLES, format_checks, validate

Store = LocalStore | S3Store
Log = Callable[[str], None]


def utcnow() -> datetime:
    return datetime.now(UTC)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _failures(checks) -> str:
    return "; ".join(f"{c.name}: {c.detail}" for c in checks if not c.ok)


def _restore_into_scratch(dump: Path, scratch_url: str) -> None:
    run_tool("pg_restore", ["--no-owner", "--exit-on-error", f"--dbname={dbname_of(scratch_url)}", str(dump)], scratch_url)


def take(url: str, store: Store, prefix: str = "orders", verify: bool = True, clock: Callable[[], datetime] = utcnow, log: Log = print) -> dict:
    """Snapshot the database. With verify=False the data is not validated first and a failing validation of
    the snapshot is not fatal: that is what a backup job without recovery validation does (the drills use it)."""
    if verify:
        checks, _ = validate(url)
        if not all(c.ok for c in checks):
            raise RecoveryError(f"refusing to snapshot data that fails validation ({_failures(checks)})")
    created = clock()
    name = check_name(f"{prefix}-{created:%Y%m%dT%H%M%SZ}")
    if f"{name}{MANIFEST_SUFFIX}" in store.keys():
        raise RecoveryError(f"a snapshot named {name} already exists (names have one-second resolution); not overwriting it")
    with tempfile.TemporaryDirectory(prefix="snapshot-") as tmp:
        dump = Path(tmp) / f"{name}{DUMP_SUFFIX}"
        run_tool("pg_dump", ["--format=custom", "--no-owner", f"--dbname={dbname_of(url)}", "--file", str(dump)], url)
        with scratch_database(url) as scratch:
            _restore_into_scratch(dump, scratch)
            checks, facts = validate(scratch)
        if verify and not all(c.ok for c in checks):
            raise RecoveryError(f"snapshot did not validate after restoring it ({_failures(checks)})")
        if any(f"rows_{t}" not in facts for t in TABLES):
            raise RecoveryError("snapshot restored without the expected tables")
        manifest = {
            "format": 1,
            "name": name,
            "created_at": created.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "database": dbname_of(url),
            "dump_sha256": sha256(dump),
            "dump_bytes": dump.stat().st_size,
            "tables": {t: facts[f"rows_{t}"] for t in TABLES},
            "validated": verify,
        }
        manifest_path = Path(tmp) / f"{name}{MANIFEST_SUFFIX}"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
        store.put(dump, dump.name)  # dump first, manifest last: no manifest, no snapshot
        store.put(manifest_path, manifest_path.name)
    log(f"snapshot written: {name} ({manifest['dump_bytes']} bytes, " + ", ".join(f"{t}={n}" for t, n in manifest["tables"].items()) + ")")
    return manifest


def fetch(store: Store, name: str, directory: Path) -> tuple[dict, Path]:
    """Download a snapshot and prove the dump is the one the manifest describes."""
    check_name(name)
    manifest_path, dump = directory / f"{name}{MANIFEST_SUFFIX}", directory / f"{name}{DUMP_SUFFIX}"
    store.get(manifest_path.name, manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text())
        expected = manifest["dump_sha256"]
        created = manifest["created_at"]
        manifest["tables"]  # noqa: B018  (must exist)
    except (ValueError, KeyError, TypeError) as err:
        raise RecoveryError(f"manifest unreadable ({err.__class__.__name__})") from err
    if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", str(created)):
        raise RecoveryError("manifest has no valid created_at")
    store.get(dump.name, dump)
    actual = sha256(dump)
    if actual != expected:
        raise RecoveryError(f"checksum mismatch (manifest {expected[:12]}, dump {actual[:12]})")
    return manifest, dump


def _created(manifest: dict) -> datetime:
    return datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))


def _prove(store: Store, name: str, url: str, directory: Path) -> tuple[dict, Path]:
    """Fetch a snapshot and restore it into a scratch database; raises if anything about it is wrong."""
    manifest, dump = fetch(store, name, directory)
    with scratch_database(url) as scratch:
        try:
            _restore_into_scratch(dump, scratch)
        except RecoveryError as err:
            raise RecoveryError(f"does not restore ({err})") from err
        checks, _ = validate(scratch, manifest)
    if not all(c.ok for c in checks):
        raise RecoveryError(f"fails validation ({_failures(checks)})")
    return manifest, dump


def restore(url: str, store: Store, clock: Callable[[], datetime] = utcnow, log: Log = print) -> dict:
    """Restore the newest snapshot that proves itself over the live database. Returns facts for the postmortem."""
    names = snapshot_names(store)
    if not names:
        raise RecoveryError(f"no snapshots found in {store}")
    skipped: list[str] = []
    with tempfile.TemporaryDirectory(prefix="restore-") as tmp:
        for name in names:
            try:
                manifest, dump = _prove(store, name, url, Path(tmp))
            except RecoveryError as err:
                skipped.append(f"{name}: {err}")
                log(f"skipping {name}: {err}")
                continue
            started = time.monotonic()
            run_tool(
                "pg_restore",
                ["--clean", "--if-exists", "--no-owner", "--exit-on-error", "--single-transaction", f"--dbname={dbname_of(url)}", str(dump)],
                url,
            )
            checks, facts = validate(url, manifest)
            log(format_checks(checks))
            if not all(c.ok for c in checks):
                raise RecoveryError(f"restored {name} but the live database fails validation ({_failures(checks)})")
            log(f"restored {name} ({manifest['created_at']})")
            return {
                "snapshot": name,
                "snapshot_created_at": manifest["created_at"],
                "snapshot_age_seconds": round((clock() - _created(manifest)).total_seconds(), 1),
                "restore_seconds": round(time.monotonic() - started, 2),
                "snapshots_skipped": len(skipped),
                **({"skipped_reasons": " | ".join(skipped)} if skipped else {}),
                **facts,
            }
    raise RecoveryError("no snapshot verified (" + " | ".join(skipped) + ")")


def restore_test(url: str, store: Store, max_age_seconds: float | None = None, clock: Callable[[], datetime] = utcnow, log: Log = print) -> dict:
    """Prove the newest snapshot restores and validates, without touching live data. Raises RecoveryError if not."""
    names = snapshot_names(store)
    if not names:
        raise RecoveryError(f"no snapshots found in {store}")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="restore-test-") as tmp:
        try:
            manifest, _ = _prove(store, names[0], url, Path(tmp))
        except RecoveryError as err:
            raise RecoveryError(f"newest snapshot {names[0]} is not restorable: {err}") from err
    duration = round(time.monotonic() - started, 2)
    age = round((clock() - _created(manifest)).total_seconds(), 1)
    if max_age_seconds is not None and age > max_age_seconds:
        raise RecoveryError(f"newest snapshot {names[0]} restores, but it is {age:.0f}s old (limit {max_age_seconds:.0f}s): backups have stopped")
    log(f"newest snapshot {names[0]} restores and validates ({duration}s, {age:.0f}s old)")
    return {"snapshot": names[0], "snapshot_age_seconds": age, "restore_test_seconds": duration, **{f"rows_{t}": n for t, n in manifest["tables"].items()}}
