"""Where snapshots live: a directory, or an S3 prefix reached through the AWS CLI.

A snapshot is two objects: <name>.dump (pg_dump custom format) and <name>.manifest.json. The dump is
uploaded first and the manifest last, so a snapshot without a manifest does not exist as far as
restore is concerned: a half-uploaded snapshot is never picked.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .pg import RecoveryError

MANIFEST_SUFFIX = ".manifest.json"
DUMP_SUFFIX = ".dump"
NAME = re.compile(r"^[a-z0-9_-]+-\d{8}T\d{6}Z$")


def check_name(name: str) -> str:
    if not NAME.match(name):
        raise RecoveryError(f"unexpected snapshot name {name!r}")
    return name


class LocalStore:
    def __init__(self, directory: Path):
        self.dir = Path(directory)

    def put(self, local: Path, key: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local, self.dir / key)

    def get(self, key: str, dest: Path) -> None:
        try:
            shutil.copyfile(self.dir / key, dest)
        except OSError as err:
            raise RecoveryError(f"cannot read {key}: {err}") from err

    def keys(self) -> list[str]:
        return sorted(p.name for p in self.dir.iterdir()) if self.dir.is_dir() else []

    def __str__(self) -> str:
        return str(self.dir)


class S3Store:
    """Uses the `aws` CLI (argv, no shell) so credentials come from the normal AWS credential chain."""

    def __init__(self, uri: str):
        match = re.match(r"^s3://([a-z0-9][a-z0-9.-]{1,61}[a-z0-9])(?:/(.*))?$", uri)
        if not match:
            raise RecoveryError(f"not an s3 URI: {uri!r}")
        self.bucket, self.prefix = match.group(1), (match.group(2) or "").strip("/")

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def _aws(self, *args: str) -> str:
        try:
            proc = subprocess.run(["aws", *args], capture_output=True, text=True, timeout=600, check=False)  # noqa: S603, S607
        except (OSError, subprocess.TimeoutExpired) as err:
            raise RecoveryError(f"aws CLI failed to run: {err}") from err
        if proc.returncode != 0:
            lines = [ln.strip() for ln in proc.stderr.splitlines() if ln.strip()]
            raise RecoveryError(f"aws {args[0]} {args[1]} failed: {lines[-1] if lines else proc.returncode}")
        return proc.stdout

    def put(self, local: Path, key: str) -> None:
        self._aws("s3", "cp", str(local), f"s3://{self.bucket}/{self._key(key)}", "--only-show-errors")

    def get(self, key: str, dest: Path) -> None:
        self._aws("s3", "cp", f"s3://{self.bucket}/{self._key(key)}", str(dest), "--only-show-errors")

    def keys(self) -> list[str]:
        prefix = f"{self.prefix}/" if self.prefix else ""
        out = self._aws("s3api", "list-objects-v2", "--bucket", self.bucket, "--prefix", prefix, "--query", "Contents[].Key", "--output", "json")
        listed = json.loads(out or "null") or []
        return sorted(k[len(prefix) :] for k in listed if "/" not in k[len(prefix) :])

    def __str__(self) -> str:
        return f"s3://{self.bucket}/{self.prefix}"


def open_store(spec: str) -> LocalStore | S3Store:
    return S3Store(spec) if spec.startswith("s3://") else LocalStore(Path(spec))


def snapshot_names(store: LocalStore | S3Store) -> list[str]:
    """Snapshot names that have a manifest, newest first (names embed a sortable UTC timestamp)."""
    names = [k[: -len(MANIFEST_SUFFIX)] for k in store.keys() if k.endswith(MANIFEST_SUFFIX)]
    return sorted((n for n in names if NAME.match(n)), reverse=True)
