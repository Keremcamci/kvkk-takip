import socket

import pytest

import backend
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


@pytest.fixture(autouse=True)
def db_setup(monkeypatch, tmp_path):
    """Her test için geçici bir veritabanı kur. Testler gerçek kvkk.db'ye
    değil, izole bir tmp_path veritabanına karşı çalışır."""
    db_path = tmp_path / "test_kvkk.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    conn = db.get_connection()
    db.init_db(conn)
    conn.close()
    yield


@pytest.fixture(autouse=True)
def limiter_sifirla():
    """Flask-Limiter'ın rate-limit state'i process boyunca (tek `app`
    singleton'ında) kalıcıdır. Rate-limit testi limiti bilerek aşacağı
    için, bu state sıfırlanmazsa diğer /api/kararlar testlerine sızıp
    onları da 429'a düşürebilir — test sırasına bağlı, kırılgan bir hata
    sınıfı. Her testten önce sayaçları sıfırlamak bunu önler."""
    backend.limiter.reset()
    yield
