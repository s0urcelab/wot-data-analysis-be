import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "wot.db"))
    monkeypatch.setenv("SCHEDULER_ENABLED", "0")
    from wotapp.database import init_db, reset_db

    reset_db()
    init_db()
    yield
    reset_db()


@pytest.fixture()
def client(db):
    from wotapp.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
