import threading

import orders
import pytest

from drpilot import pgcluster
from drpilot import playbooks as pb
from drpilot.engine import Responder
from drpilot.model import IncidentStore
from recovery.store import LocalStore

from .helpers import Clock, write_playbook


@pytest.fixture(scope="session")
def project_root():
    from pathlib import Path

    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def pg_cluster():
    """One throwaway PostgreSQL server for the whole run; tests that need it are skipped where PostgreSQL is not installed."""
    if not pgcluster.available():
        pytest.skip("PostgreSQL server binaries and client tools are not installed")
    with pgcluster.temporary_cluster() as cluster:
        yield cluster


@pytest.fixture
def db_url(pg_cluster, monkeypatch):
    """A fresh database with the orders schema; DATABASE_URL points at it."""
    import uuid

    url = pg_cluster.create_database(f"t_{uuid.uuid4().hex[:10]}")
    orders.init_schema(url)
    monkeypatch.setenv("DATABASE_URL", url)
    return url


@pytest.fixture
def orders_service(db_url):
    httpd = orders.create_server("127.0.0.1", 0, db_url)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def store(tmp_path):
    return LocalStore(tmp_path / "backups")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def make_responder(tmp_path, clock):
    def build(*books, **kwargs):
        loaded = [pb.load(write_playbook(tmp_path, f"book{i}", text)) for i, text in enumerate(books)]
        return Responder(IncidentStore(tmp_path / "state"), loaded, tmp_path / "pm", clock=clock, run_async=False, **kwargs)

    return build
