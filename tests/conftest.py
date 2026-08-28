import pytest

import db


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test_kvkk.db"
    connection = db.get_connection(db_path)
    db.init_db(connection)
    yield connection
    connection.close()
