"""Testkonfiguration: DB nur initialisieren, wenn die App sie nicht schon gesetzt hat."""
import pytest

from server import db


@pytest.fixture(autouse=True)
def _db(tmp_path):
    if db.DB_PATH is None:
        db.init(tmp_path / "susmob_test.db")
    yield
