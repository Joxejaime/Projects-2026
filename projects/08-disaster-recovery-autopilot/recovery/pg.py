"""PostgreSQL plumbing for the recovery tools: connection details, client binaries, scratch databases.

Connection details come from DATABASE_URL (a libpq URI or key=value string) and are handed to the
PostgreSQL client tools as PG* environment variables, never as arguments, so a password does not
show up in a process listing.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ENV_FOR_KEY = {
    "host": "PGHOST",
    "port": "PGPORT",
    "user": "PGUSER",
    "password": "PGPASSWORD",
    "dbname": "PGDATABASE",
    "sslmode": "PGSSLMODE",
    "sslrootcert": "PGSSLROOTCERT",
    "connect_timeout": "PGCONNECT_TIMEOUT",
}
TOOL_TIMEOUT = 600


class RecoveryError(RuntimeError):
    pass


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RecoveryError("DATABASE_URL is not set")
    return url


def with_dbname(url: str, name: str) -> str:
    return make_conninfo(url, dbname=name)


def dbname_of(url: str) -> str:
    name = conninfo_to_dict(url).get("dbname")
    if not name:
        raise RecoveryError("DATABASE_URL must name the database explicitly")
    return name


def connect(url: str, **kwargs) -> psycopg.Connection:
    try:
        return psycopg.connect(url, connect_timeout=5, **kwargs)
    except psycopg.OperationalError as err:
        raise RecoveryError(f"cannot connect to the database: {str(err).strip().splitlines()[-1]}") from err


def pg_env(url: str) -> dict[str, str]:
    """libpq environment for a client tool. Unknown connection keys are an error, not silently dropped."""
    env = dict(os.environ)
    for key in ENV_FOR_KEY.values():
        env.pop(key, None)
    for key, value in conninfo_to_dict(url).items():
        if key not in ENV_FOR_KEY:
            raise RecoveryError(f"connection option {key!r} is not supported by the recovery tools")
        env[ENV_FOR_KEY[key]] = str(value)
    return env


def find_bin(name: str) -> str:
    """A PostgreSQL client or server binary: on PATH, else the newest /usr/lib/postgresql/<major>/bin."""
    found = shutil.which(name)
    if found:
        return found
    versioned = []
    for path in glob.glob(f"/usr/lib/postgresql/*/bin/{name}"):
        match = re.search(r"/postgresql/(\d+)/bin/", path)
        if match:
            versioned.append((int(match.group(1)), path))
    if versioned:
        return max(versioned)[1]
    raise RecoveryError(f"{name} not found; install the PostgreSQL client tools")


def run_tool(name: str, args: list[str], url: str) -> str:
    argv = [find_bin(name), *args]
    try:
        proc = subprocess.run(argv, env=pg_env(url), capture_output=True, text=True, timeout=TOOL_TIMEOUT, check=False)  # noqa: S603
    except subprocess.TimeoutExpired as err:
        raise RecoveryError(f"{name} timed out after {TOOL_TIMEOUT}s") from err
    if proc.returncode != 0:
        lines = [ln.strip() for ln in proc.stderr.splitlines() if ln.strip()]
        raise RecoveryError(f"{name} failed: {lines[-1] if lines else f'exit {proc.returncode}'}")
    return proc.stdout


@contextmanager
def scratch_database(url: str, label: str = "verify") -> Iterator[str]:
    """A throwaway database next to the real one, for restoring a snapshot without touching live data.

    Needs the CREATEDB privilege. The database is dropped (connections forced off) when the block ends.
    """
    name = f"{dbname_of(url)}_{label}_{uuid.uuid4().hex[:8]}"
    with connect(with_dbname(url, "postgres"), autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield with_dbname(url, name)
    finally:
        with connect(with_dbname(url, "postgres"), autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
