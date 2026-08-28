import sys

import db
import backend


def test_index_serves_html_with_disclaimer():
    client = backend.app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "hukuki tavsiye değildir" in body


def test_api_kararlar_returns_son_guncelleme_and_filtered_list(monkeypatch, tmp_path):
    db_path = tmp_path / "test_backend.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)

    conn = db.get_connection()
    db.init_db(conn)
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Genel Karar", tarih="2026-01-01", kaynak_url="https://example.com/1", ozet_ham="x")
    karar_id = db.get_pending_kararlar(conn)[0]["id"]
    db.update_karar_classification(conn, karar_id, ["genel"], "özet", ["madde"], False, "")
    conn.close()

    client = backend.app.test_client()
    response = client.get("/api/kararlar?profil=e-ticaret")
    veri = response.get_json()
    assert veri["son_guncelleme"] is not None
    assert len(veri["kararlar"]) == 1
    assert veri["kararlar"][0]["baslik"] == "Genel Karar"


def test_api_kararlar_defaults_to_genel_profile_when_empty(monkeypatch, tmp_path):
    db_path = tmp_path / "test_backend2.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    conn = db.get_connection()
    db.init_db(conn)
    conn.close()

    client = backend.app.test_client()
    response = client.get("/api/kararlar")
    veri = response.get_json()
    assert veri["kararlar"] == []
    assert veri["son_guncelleme"] is None


# NOT: index.html'in öznitelik kaçırma (escaping) koruması artık
# tests/test_frontend.py'de — hem kaynak seviyesinde hem node ile gerçekten
# çalıştırılarak. Buradaki eski test yalnızca sayfa kaynağında
# `esc(karar.kaynak_url)` metnini arıyordu; tırnak kaçırma açığı canlıyken
# bile geçtiği için gerçek bir regresyon koruması değildi.


def test_reset_failed_cli_requeues_and_reports_count(monkeypatch, tmp_path, capsys):
    db_path = tmp_path / "test_reset_cli.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)

    conn = db.get_connection()
    db.init_db(conn)
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Karar", tarih="2026-01-01", kaynak_url="https://example.com/r1", ozet_ham="x")
    karar_id = db.get_pending_kararlar(conn)[0]["id"]
    for _ in range(3):
        db.mark_karar_failed(conn, karar_id)
    conn.close()

    monkeypatch.setattr(sys, "argv", ["backend.py", "--reset-failed"])
    backend.main()

    assert "1 karar" in capsys.readouterr().out
    conn = db.get_connection()
    try:
        assert len(db.get_pending_kararlar(conn)) == 1
    finally:
        conn.close()


def test_reset_failed_cli_does_not_also_run_scrape(monkeypatch, tmp_path, capsys):
    """--reset-failed ayrı ve açık bir eylemdir; aynı çağrıda scrape etmez."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_reset_cli2.db")
    cagrildi = []
    monkeypatch.setattr(backend, "run_scrape", lambda: cagrildi.append("scrape"))
    monkeypatch.setattr(sys, "argv", ["backend.py", "--reset-failed"])

    backend.main()

    assert cagrildi == []
    assert "0 karar" in capsys.readouterr().out
