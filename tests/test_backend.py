import re
import sys

import db
import backend


def test_index_serves_html_with_disclaimer():
    client = backend.app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "hukuki tavsiye değildir" in body


def test_baseline_security_headers_present_on_index():
    """Hiçbir güvenlik başlığı ayarlanmıyordu (CSP, X-Frame-Options,
    X-Content-Type-Options, HSTS)."""
    response = backend.app.test_client().get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "max-age=" in response.headers["Strict-Transport-Security"]


def test_baseline_security_headers_present_on_api_endpoint():
    """Başlıklar yalnızca / rotasına değil, tüm yanıtlara uygulanmalı."""
    response = backend.app.test_client().get("/api/kararlar")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "max-age=" in response.headers["Strict-Transport-Security"]


def test_csp_uses_nonce_matching_injected_script_and_style_tags():
    """index.html inline <script> ve <style> kullanıyor; 'unsafe-inline'
    CSP'yi neredeyse anlamsız kılar (enjekte edilen HERHANGİ bir script de
    çalışır). Bunun yerine her istekte üretilen bir nonce, hem CSP başlığına
    hem de sayfadaki <script>/<style> etiketlerine yazılmalı — yalnızca
    sunucunun kendi ürettiği script/style çalışır, başka bir enjeksiyon
    (esc()/escAttr() atlanan bir hata olsa bile) nonce'u bilemeyeceği için
    tarayıcı tarafından engellenir."""
    response = backend.app.test_client().get("/")
    csp = response.headers["Content-Security-Policy"]
    m = re.search(r"nonce-([A-Za-z0-9_-]+)", csp)
    assert m is not None, f"CSP'de nonce bulunamadı: {csp}"
    nonce = m.group(1)

    body = response.get_data(as_text=True)
    assert f'<script nonce="{nonce}">' in body
    assert f'<style nonce="{nonce}">' in body
    assert "script-src 'self' 'nonce-" in csp
    assert "style-src 'self' 'nonce-" in csp
    assert "'unsafe-inline'" not in csp


def test_csp_nonce_differs_between_requests():
    """Sabit/hardcoded bir nonce, gerçek bir nonce olmaz — enjekte edilen
    script de o sabit değeri kolayca taşıyabilir."""
    client = backend.app.test_client()

    def _nonce():
        csp = client.get("/").headers["Content-Security-Policy"]
        return re.search(r"nonce-([A-Za-z0-9_-]+)", csp).group(1)

    assert _nonce() != _nonce()


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


def test_api_kararlar_returns_kaynak_sayilari_for_every_profil(monkeypatch, tmp_path):
    """Kaynak sayıları profil filtresinden BAĞIMSIZ olmalı.

    Bulgu buydu: varsayılan "genel" profili yalnızca "genel" etiketli
    kararları döndürüyor, bu yüzden BDDK/SPK kararları veritabanında
    olmasına rağmen kullanıcıya hiçbir iz bırakmıyordu. Bu alan
    `son_guncelleme` gibi davranır: hangi profil istenirse istensin aynı
    değeri döner.
    """
    db_path = tmp_path / "test_backend_kaynak.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)

    conn = db.get_connection()
    db.init_db(conn)
    # Gerçek dağılımın minik hali: KVKK "genel", BDDK/SPK "finans".
    veriler = [
        ("kvkk", "KVKK Kararı", "https://example.com/k1", ["genel"]),
        ("bddk", "BDDK Kararı 1", "https://example.com/b1", ["finans"]),
        ("bddk", "BDDK Kararı 2", "https://example.com/b2", ["finans"]),
        ("spk", "SPK Kararı", "https://example.com/s1", ["finans"]),
    ]
    for kaynak, baslik, url, sektorler in veriler:
        db.insert_karar_if_new(conn, kaynak=kaynak, baslik=baslik, tarih="2026-01-01", kaynak_url=url, ozet_ham="x")
        karar_id = next(k["id"] for k in db.get_pending_kararlar(conn) if k["baslik"] == baslik)
        db.update_karar_classification(conn, karar_id, sektorler, "özet", [], False, "")
    conn.close()

    client = backend.app.test_client()
    beklenen = {"kvkk": 1, "bddk": 2, "spk": 1}

    # Varsayılan (genel) profil: liste yalnızca 1 karar gösterse bile
    # kullanıcı diğer 3 kararın var olduğunu görebilmeli.
    varsayilan = client.get("/api/kararlar").get_json()
    assert varsayilan["kaynak_sayilari"] == beklenen
    assert len(varsayilan["kararlar"]) == 1

    # Ve değer profile göre DEĞİŞMEMELİ.
    for profil in ["genel", "e-ticaret", "finans", "saglik", "egitim"]:
        veri = client.get(f"/api/kararlar?profil={profil}").get_json()
        assert veri["kaynak_sayilari"] == beklenen, profil


def test_api_kararlar_kaynak_sayilari_is_empty_when_db_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_backend_kaynak_bos.db")
    conn = db.get_connection()
    db.init_db(conn)
    conn.close()

    veri = backend.app.test_client().get("/api/kararlar").get_json()
    assert veri["kaynak_sayilari"] == {}


def test_api_kararlar_rejects_unknown_profil_with_400(monkeypatch, tmp_path):
    """profil query param'ı doğrulanmıyordu: bilinmeyen bir değer (örn.
    ?profil=xyz) sessizce yalnızca "genel" etiketli kararları döndürüyordu.
    Şimdi izin verilen listede olmayan bir değer 400 ile reddedilmeli."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_backend_gecersiz_profil.db")
    conn = db.get_connection()
    db.init_db(conn)
    conn.close()

    client = backend.app.test_client()
    response = client.get("/api/kararlar?profil=xyz")

    assert response.status_code == 400
    assert "profil" in response.get_json()["error"]


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


def test_run_scrape_continues_when_one_source_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_run_scrape.db")

    calls = []

    monkeypatch.setattr(backend.kvkk, "scrape_and_store", lambda conn: calls.append("kvkk") or 1)
    monkeypatch.setattr(
        backend.bddk, "scrape_and_store",
        lambda conn: (_ for _ in ()).throw(RuntimeError("BDDK sitesi erişilemedi")),
    )
    monkeypatch.setattr(backend.spk, "scrape_and_store", lambda conn: calls.append("spk") or 2)
    monkeypatch.setattr(
        backend.resmi_gazete, "scrape_and_store",
        lambda conn: calls.append("resmi_gazete") or 3,
    )
    monkeypatch.setattr(
        backend.classifier, "classify_pending",
        lambda conn: {"basarili": 0, "basarisiz": 0, "kalici_hata": 0},
    )

    backend.run_scrape()

    assert calls == ["kvkk", "spk", "resmi_gazete"]
    cikti = capsys.readouterr().out
    assert "kvkk: 1 yeni karar" in cikti
    assert "spk: 2 yeni karar" in cikti
    assert "resmi_gazete: 3 yeni karar" in cikti
    # bddk başarısız olduğu için "bddk: ... yeni karar" satırı YOK — bu
    # kaynağın hatası, print edilen özet çıktısına hiç girmemeli.
    assert "bddk:" not in cikti


def test_run_scrape_logs_warning_for_failed_source(monkeypatch, tmp_path, caplog):
    import logging

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_run_scrape2.db")
    monkeypatch.setattr(backend.kvkk, "scrape_and_store", lambda conn: 0)
    monkeypatch.setattr(
        backend.bddk, "scrape_and_store",
        lambda conn: (_ for _ in ()).throw(RuntimeError("BDDK sitesi erişilemedi")),
    )
    monkeypatch.setattr(backend.spk, "scrape_and_store", lambda conn: 0)
    monkeypatch.setattr(backend.resmi_gazete, "scrape_and_store", lambda conn: 0)
    monkeypatch.setattr(backend.classifier, "classify_pending", lambda conn: {"basarili": 0, "basarisiz": 0, "kalici_hata": 0})

    with caplog.at_level(logging.WARNING):
        backend.run_scrape()

    assert "bddk" in caplog.text
    assert "BDDK sitesi erişilemedi" in caplog.text


def test_run_scrape_logs_traceback_for_failed_source(monkeypatch, tmp_path, caplog):
    """Kaynak hatası ayıklanabilir olmalı: yığın izi (traceback) olmadan
    log yalnızca "spk scrape başarısız: 'link'" der — hangi dosya/satır,
    hangi alan olduğu bilinmez. Kaynaklar birbirini engellemediği için bu
    hata her koşuda sessizce tekrarlanabilir; bu yüzden exc_info şart.
    """
    import logging

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_run_scrape3.db")
    monkeypatch.setattr(backend.kvkk, "scrape_and_store", lambda conn: 0)
    monkeypatch.setattr(backend.bddk, "scrape_and_store", lambda conn: 0)
    monkeypatch.setattr(backend.resmi_gazete, "scrape_and_store", lambda conn: 0)
    # Gerçekçi hata: SPK API kaydında "link" alanı eksik.
    monkeypatch.setattr(
        backend.spk, "scrape_and_store",
        lambda conn: (_ for _ in ()).throw(KeyError("link")),
    )
    monkeypatch.setattr(
        backend.classifier, "classify_pending",
        lambda conn: {"basarili": 0, "basarisiz": 0, "kalici_hata": 0},
    )

    with caplog.at_level(logging.WARNING):
        backend.run_scrape()

    (kayit,) = [r for r in caplog.records if "scrape başarısız" in r.getMessage()]
    assert kayit.exc_info is not None, "exc_info eksik — traceback yakalanmıyor"
    assert kayit.exc_info[0] is KeyError
    assert "Traceback" in caplog.text
    assert "KeyError" in caplog.text
    # Biçimlenmiş MESAJ metni değişmemeli (exc_info yalnızca traceback ekler),
    # yani mevcut mesaj tabanlı testler bundan etkilenmez.
    assert kayit.getMessage() == "spk scrape başarısız: 'link'"


def test_api_kararlar_allows_up_to_rate_limit():
    client = backend.app.test_client()
    for _ in range(30):
        response = client.get("/api/kararlar")
        assert response.status_code == 200


def test_api_kararlar_returns_429_after_exceeding_rate_limit():
    client = backend.app.test_client()
    for _ in range(30):
        client.get("/api/kararlar")
    response = client.get("/api/kararlar")
    assert response.status_code == 429
    assert "error" in response.get_json()


def test_api_kararlar_429_response_includes_retry_after_header():
    client = backend.app.test_client()
    for _ in range(30):
        client.get("/api/kararlar")
    response = client.get("/api/kararlar")
    assert "Retry-After" in response.headers
