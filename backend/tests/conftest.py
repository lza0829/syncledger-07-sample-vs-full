import os
import tempfile

import pytest


@pytest.fixture()
def fresh_db():
    """Isolated DATA_DIR + SQLite file per test."""
    tmp = tempfile.mkdtemp(prefix="syncledger-test-")
    os.environ["DATA_DIR"] = tmp

    from app import db as db_mod
    from app.config import DB_FILENAME
    from app.seed import init_db

    db_mod.DB_PATH = os.path.join(tmp, DB_FILENAME)
    init_db()
    yield tmp


@pytest.fixture()
def pair_ids(fresh_db):
    from app.services import reconcile_service as svc

    return {p["code"]: p["id"] for p in svc.list_pairs()}
