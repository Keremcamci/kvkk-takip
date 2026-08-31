import socket

import pytest

import db


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test_kvkk.db"
    connection = db.get_connection(db_path)
    db.init_db(connection)
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def gercek_aga_cikisi_engelle():
    """Test paketi tamamen hermetik olmalı — hiçbir test gerçek ağa
    çıkmamalı. socket.socket.connect()'i bloklayarak, bir mock
    yanlışlıkla silinirse test sessizce gerçek bir siteye bağlanmak
    yerine anlaşılır bir hata ile HEMEN başarısız olur. Bu, tek tek
    call_count assertion'ları eklemekten çok daha kapsamlı bir koruma:
    dosyadaki HER test için, gelecekte eklenecek testler dahil, otomatik
    çalışır."""

    def _engellenmis_baglanti(self, address):
        raise RuntimeError(
            f"Test gerçek ağa çıkmaya çalıştı ({address}) — bir "
            "mock eksik veya yanlışlıkla silinmiş olabilir."
        )

    orijinal_connect = socket.socket.connect
    socket.socket.connect = _engellenmis_baglanti
    try:
        yield
    finally:
        socket.socket.connect = orijinal_connect
