#!/usr/bin/env python3
"""Snapshot and restore the notes data file.

    backup.py snapshot --data notes.json --dir backups/     copy + verify a snapshot
    backup.py restore  --data notes.json --dir backups/     restore the newest snapshot that verifies

A snapshot is only useful if it restores, so both commands verify checksums; restore skips corrupt
snapshots instead of copying them over the data file. Restore prints a final JSON line with facts the
responder records in the postmortem (snapshot age is the recovery point actually achieved).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notes import read_store  # noqa: E402


def snapshot(data: Path, directory: Path) -> Path:
    notes = read_store(data)  # never snapshot a file that is already broken
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / f"notes-{time.time_ns()}.json"
    shutil.copy2(data, dest)
    if read_store(dest) != notes:
        dest.unlink()
        raise ValueError("snapshot did not verify after copying")
    return dest


def restore(data: Path, directory: Path) -> dict:
    snaps = sorted(directory.glob("notes-*.json"), key=lambda p: int(p.stem.split("-")[1]), reverse=True)
    skipped = []
    for snap in snaps:
        try:
            notes = read_store(snap)
        except ValueError as err:
            skipped.append(f"{snap.name}: {err}")
            continue
        tmp = data.with_name(data.name + ".restore")
        shutil.copy2(snap, tmp)
        os.replace(tmp, data)
        age = time.time() - int(snap.stem.split("-")[1]) / 1e9
        return {"snapshot": snap.name, "snapshot_age_seconds": round(age, 1), "notes_restored": len(notes), "corrupt_snapshots_skipped": len(skipped)}
    raise ValueError("no snapshot verified" + (f" (skipped: {'; '.join(skipped)})" if skipped else ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["snapshot", "restore"])
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            print(f"snapshot written: {snapshot(args.data, args.dir)}")
        else:
            facts = restore(args.data, args.dir)
            print(f"restored {facts['notes_restored']} notes from {facts['snapshot']}")
            print(json.dumps({"facts": facts}))
    except ValueError as err:
        print(f"{args.command} failed: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
