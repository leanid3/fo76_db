"""Тесты работают в пустой временной папке: FO76DB_HOME задаётся до импорта fo76db (db.ROOT считается при импорте)."""
import os
import tempfile

_HOME = tempfile.mkdtemp(prefix="fo76db-test-")
os.environ["FO76DB_HOME"] = _HOME
os.environ.pop("FO76DB_TOKEN", None)
os.environ.pop("FO76DB_GAME_DATA", None)

import pytest  # noqa: E402


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from fo76db.web.app import app
    # TestClient ходит с client.host = "testclient": для «локальных» тестов подменяем адрес и Host
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


@pytest.fixture
def remote():
    from fastapi.testclient import TestClient

    from fo76db.web.app import app
    return TestClient(app, base_url="http://pc.example", client=("203.0.113.5", 50000))
