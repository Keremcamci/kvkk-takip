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


def test_index_escapes_kaynak_url_before_href_injection():
    # Regression guard for the kaynak_url attribute-injection/XSS gap: the
    # served index.html must run kaynak_url through esc() before interpolating
    # it into the href attribute, same as every other field in kararKart().
    client = backend.app.test_client()
    response = client.get("/")
    body = response.get_data(as_text=True)
    assert 'href="${esc(karar.kaynak_url)}"' in body
    assert 'href="${karar.kaynak_url}"' not in body
