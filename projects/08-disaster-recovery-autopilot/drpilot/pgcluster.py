"""A throwaway PostgreSQL server for drills and tests: its own data directory, loopback only, deleted on exit.

Uses the server binaries already on the machine (initdb, pg_ctl). When run as root, which PostgreSQL
refuses, the server runs as the `postgres` OS user. Authentication is `trust` on 127.0.0.1: acceptable
only because the server is temporary and unreachable from anywhere else.
"""

from __future__ import annotations

import os
import pwd
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

from recovery.pg import RecoveryError, find_bin


@dataclass(frozen=True)
class Cluster:
    port: int
    root: Path

    def url(self, dbname: str = "postgres") -> str:
        return f"postgresql://postgres@127.0.0.1:{self.port}/{dbname}"

    def create_database(self, name: str) -> str:
        with psycopg.connect(self.url(), autocommit=True, connect_timeout=5) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        return self.url(name)


def available() -> bool:
    try:
        find_bin("initdb"), find_bin("pg_ctl"), find_bin("postgres"), find_bin("pg_dump"), find_bin("pg_restore")
    except RecoveryError:
        return False
    return True


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def temporary_cluster() -> Iterator[Cluster]:
    if not available():
        raise RecoveryError("PostgreSQL server binaries (initdb, pg_ctl, postgres) and client tools are required for drills")
    root = Path(tempfile.mkdtemp(prefix="drpilot-pg-"))
    prefix: list[str] = []
    if os.geteuid() == 0:
        try:
            pwd.getpwnam("postgres")
        except KeyError as err:
            raise RecoveryError("running as root and there is no `postgres` OS user to run the server as") from err
        shutil.chown(root, user="postgres")
        prefix = [shutil.which("runuser") or "runuser", "-u", "postgres", "--"]
    data, port = root / "data", _free_port()
    try:
        subprocess.run([*prefix, find_bin("initdb"), "-D", str(data), "-A", "trust", "-U", "postgres", "--no-sync"], check=True, capture_output=True)  # noqa: S603
        subprocess.run(  # noqa: S603
            [
                *prefix,
                find_bin("pg_ctl"),
                "-D",
                str(data),
                "-l",
                str(root / "server.log"),
                "-o",
                f"-p {port} -c listen_addresses=127.0.0.1 -c unix_socket_directories= -c fsync=off",
                "-w",
                "start",
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as err:
        shutil.rmtree(root, ignore_errors=True)
        raise RecoveryError(f"could not start a temporary PostgreSQL server: {err.stderr.decode(errors='replace').strip()[-300:]}") from err
    try:
        yield Cluster(port, root)
    finally:
        subprocess.run([*prefix, find_bin("pg_ctl"), "-D", str(data), "-m", "immediate", "-w", "stop"], check=False, capture_output=True)  # noqa: S603
        shutil.rmtree(root, ignore_errors=True)
