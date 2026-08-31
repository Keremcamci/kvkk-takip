import db


def test_get_connection_enables_wal_mode_and_busy_timeout(tmp_path):
    """Web sunumu (backend.py) ve tarama (--scrape) aynı SQLite dosyasına
    eşzamanlı erişebilir. Varsayılan "rollback journal" modunda bu
    "database is locked" hatasına yol açabilir. WAL modu + busy_timeout
    (kilit anında hemen hata vermek yerine bekleme) bu riski azaltır."""
    connection = db.get_connection(tmp_path / "wal_test.db")
    try:
        mod = connection.execute("PRAGMA journal_mode").fetchone()[0]
        assert mod.lower() == "wal"
        zaman_asimi = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        assert zaman_asimi >= 5000
    finally:
        connection.close()


def test_init_db_creates_table(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='kararlar'"
    ).fetchone()
    assert row is not None


def test_insert_karar_if_new_returns_true_for_new_row(conn):
    eklendi = db.insert_karar_if_new(
        conn, kaynak="kvkk", baslik="Test Karar", tarih="2026-01-01",
        kaynak_url="https://example.com/1", ozet_ham="Test Karar",
    )
    assert eklendi is True


def test_insert_karar_if_new_returns_false_for_duplicate(conn):
    db.insert_karar_if_new(
        conn, kaynak="kvkk", baslik="Test Karar", tarih="2026-01-01",
        kaynak_url="https://example.com/1", ozet_ham="Test Karar",
    )
    eklendi = db.insert_karar_if_new(
        conn, kaynak="kvkk", baslik="Değişik başlık", tarih="2026-01-02",
        kaynak_url="https://example.com/1", ozet_ham="Değişik başlık",
    )
    assert eklendi is False


def test_get_pending_kararlar_returns_unprocessed_rows(conn):
    db.insert_karar_if_new(
        conn, kaynak="kvkk", baslik="Bekleyen Karar", tarih="2026-01-01",
        kaynak_url="https://example.com/2", ozet_ham="Bekleyen Karar",
    )
    bekleyenler = db.get_pending_kararlar(conn)
    assert len(bekleyenler) == 1
    assert bekleyenler[0]["baslik"] == "Bekleyen Karar"
    assert bekleyenler[0]["deneme_sayisi"] == 0


def test_update_karar_classification_marks_processed(conn):
    db.insert_karar_if_new(
        conn, kaynak="kvkk", baslik="Karar", tarih="2026-01-01",
        kaynak_url="https://example.com/3", ozet_ham="Karar",
    )
    karar_id = db.get_pending_kararlar(conn)[0]["id"]
    db.update_karar_classification(
        conn, karar_id,
        sektorler=["e-ticaret", "genel"],
        ozet="Kısa özet.",
        yapilmasi_gerekenler=["Madde 1"],
        aciliyet_var=True,
        aciliyet_aciklama="Ceza riski var",
    )
    assert db.get_pending_kararlar(conn) == []
    sonuclar = db.get_kararlar_by_profil(conn, "e-ticaret")
    assert len(sonuclar) == 1
    assert sonuclar[0]["sektorler"] == ["e-ticaret", "genel"]
    assert sonuclar[0]["aciliyet_var"] is True


def test_mark_karar_failed_increments_and_caps_at_permanent_failure(conn):
    db.insert_karar_if_new(
        conn, kaynak="kvkk", baslik="Karar", tarih="2026-01-01",
        kaynak_url="https://example.com/4", ozet_ham="Karar",
    )
    karar_id = db.get_pending_kararlar(conn)[0]["id"]

    assert db.mark_karar_failed(conn, karar_id) is False
    assert db.mark_karar_failed(conn, karar_id) is False
    assert len(db.get_pending_kararlar(conn)) == 1

    assert db.mark_karar_failed(conn, karar_id) is True
    assert db.get_pending_kararlar(conn) == []
    row = conn.execute(
        "SELECT islendi_mi, deneme_sayisi FROM kararlar WHERE id = ?", (karar_id,)
    ).fetchone()
    assert row["islendi_mi"] == -1
    assert row["deneme_sayisi"] == 3


def test_get_kararlar_by_profil_includes_genel_and_matching_profile(conn):
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Genel Karar", tarih="2026-01-01", kaynak_url="https://example.com/5", ozet_ham="x")
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Finans Karar", tarih="2026-01-02", kaynak_url="https://example.com/6", ozet_ham="x")
    ids = {row["baslik"]: row["id"] for row in conn.execute("SELECT id, baslik FROM kararlar").fetchall()}

    db.update_karar_classification(conn, ids["Genel Karar"], ["genel"], "özet", [], False, "")
    db.update_karar_classification(conn, ids["Finans Karar"], ["finans"], "özet", [], False, "")

    e_ticaret_sonuc = db.get_kararlar_by_profil(conn, "e-ticaret")
    assert [k["baslik"] for k in e_ticaret_sonuc] == ["Genel Karar"]

    finans_sonuc = db.get_kararlar_by_profil(conn, "finans")
    assert sorted(k["baslik"] for k in finans_sonuc) == ["Finans Karar", "Genel Karar"]


def test_get_son_guncelleme_returns_none_when_empty(conn):
    assert db.get_son_guncelleme(conn) is None


def test_get_son_guncelleme_returns_timestamp_after_insert(conn):
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Karar", tarih="2026-01-01", kaynak_url="https://example.com/7", ozet_ham="x")
    assert db.get_son_guncelleme(conn) is not None


def test_created_at_is_marked_as_utc_with_z_suffix(conn):
    """SQLite strftime('now') UTC döner ama saat dilimi belirtmeden. Bir
    tarayıcıda `new Date(iso)` saat dilimi olmayan bir ISO dize-zaman
    değerini YEREL saat olarak yorumlar; bu yüzden "Son güncelleme" saati
    kullanıcıya yanlış gösterilir. 'Z' soneki değeri açıkça UTC olarak
    işaretler."""
    db.insert_karar_if_new(
        conn, kaynak="kvkk", baslik="Karar", tarih="2026-01-01",
        kaynak_url="https://example.com/zsuffix", ozet_ham="x",
    )
    son_guncelleme = db.get_son_guncelleme(conn)
    assert son_guncelleme.endswith("Z")


def test_reset_failed_kararlar_requeues_permanently_failed_rows(conn):
    db.insert_karar_if_new(
        conn, kaynak="kvkk", baslik="Zehirlenmiş Karar", tarih="2026-01-01",
        kaynak_url="https://example.com/10", ozet_ham="x",
    )
    karar_id = db.get_pending_kararlar(conn)[0]["id"]
    for _ in range(3):
        db.mark_karar_failed(conn, karar_id)
    assert db.get_pending_kararlar(conn) == []

    assert db.reset_failed_kararlar(conn) == 1

    bekleyenler = db.get_pending_kararlar(conn)
    assert len(bekleyenler) == 1
    assert bekleyenler[0]["id"] == karar_id
    assert bekleyenler[0]["deneme_sayisi"] == 0


def test_reset_failed_kararlar_leaves_pending_and_processed_rows_untouched(conn):
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Bekleyen", tarih="2026-01-01", kaynak_url="https://example.com/11", ozet_ham="x")
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="İşlenmiş", tarih="2026-01-02", kaynak_url="https://example.com/12", ozet_ham="x")
    ids = {row["baslik"]: row["id"] for row in conn.execute("SELECT id, baslik FROM kararlar").fetchall()}
    db.update_karar_classification(conn, ids["İşlenmiş"], ["genel"], "özet", [], False, "")
    db.mark_karar_failed(conn, ids["Bekleyen"])  # deneme_sayisi = 1, hâlâ bekliyor

    assert db.reset_failed_kararlar(conn) == 0

    row = conn.execute("SELECT deneme_sayisi FROM kararlar WHERE id = ?", (ids["Bekleyen"],)).fetchone()
    assert row["deneme_sayisi"] == 1  # sıfırlanmadı
    assert len(db.get_kararlar_by_profil(conn, "genel")) == 1  # işlenmiş karar bozulmadı


def test_reset_failed_kararlar_returns_zero_when_nothing_failed(conn):
    assert db.reset_failed_kararlar(conn) == 0


def test_get_kararlar_by_profil_genel_only_returns_genel_tagged(conn):
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Finans Karar", tarih="2026-01-01", kaynak_url="https://example.com/8", ozet_ham="x")
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Genel Karar", tarih="2026-01-02", kaynak_url="https://example.com/9", ozet_ham="x")
    ids = {row["baslik"]: row["id"] for row in conn.execute("SELECT id, baslik FROM kararlar").fetchall()}

    db.update_karar_classification(conn, ids["Finans Karar"], ["finans"], "özet", [], False, "")
    db.update_karar_classification(conn, ids["Genel Karar"], ["genel"], "özet", [], False, "")

    genel_sonuc = db.get_kararlar_by_profil(conn, "genel")
    assert [k["baslik"] for k in genel_sonuc] == ["Genel Karar"]


def test_get_pending_kararlar_includes_kaynak(conn):
    db.insert_karar_if_new(
        conn, kaynak="bddk", baslik="BDDK Kararı", tarih="2026-01-01",
        kaynak_url="https://example.com/b1", ozet_ham="x",
    )
    bekleyenler = db.get_pending_kararlar(conn)
    assert bekleyenler[0]["kaynak"] == "bddk"


def test_get_kararlar_by_profil_includes_kaynak(conn):
    db.insert_karar_if_new(
        conn, kaynak="spk", baslik="SPK Kararı", tarih="2026-01-01",
        kaynak_url="https://example.com/spk1", ozet_ham="x",
    )
    karar_id = db.get_pending_kararlar(conn)[0]["id"]
    db.update_karar_classification(conn, karar_id, ["genel"], "özet", [], False, "")
    sonuc = db.get_kararlar_by_profil(conn, "genel")
    assert sonuc[0]["kaynak"] == "spk"


def _ekle_ve_isle(conn, kaynak, baslik, url, sektorler=None):
    """Bir karar ekleyip sınıflandırılmış (islendi_mi = 1) hale getirir."""
    db.insert_karar_if_new(
        conn, kaynak=kaynak, baslik=baslik, tarih="2026-01-01",
        kaynak_url=url, ozet_ham="x",
    )
    karar_id = next(
        k["id"] for k in db.get_pending_kararlar(conn) if k["baslik"] == baslik
    )
    db.update_karar_classification(
        conn, karar_id, sektorler or ["genel"], "özet", [], False, ""
    )


def test_get_kaynak_sayilari_counts_per_kaynak(conn):
    """Kaynak özeti, profil filtresinden bağımsız olarak her kaynağın
    işlenmiş karar sayısını vermeli."""
    _ekle_ve_isle(conn, "kvkk", "KVKK 1", "https://example.com/k1", ["genel"])
    _ekle_ve_isle(conn, "kvkk", "KVKK 2", "https://example.com/k2", ["saglik"])
    _ekle_ve_isle(conn, "bddk", "BDDK 1", "https://example.com/b1", ["finans"])
    _ekle_ve_isle(conn, "bddk", "BDDK 2", "https://example.com/b2", ["finans"])
    _ekle_ve_isle(conn, "bddk", "BDDK 3", "https://example.com/b3", ["finans"])
    _ekle_ve_isle(conn, "spk", "SPK 1", "https://example.com/s1", ["finans"])

    assert db.get_kaynak_sayilari(conn) == {"kvkk": 2, "bddk": 3, "spk": 1}


def test_get_kaynak_sayilari_ignores_pending_and_failed_kararlar(conn):
    """Yalnızca islendi_mi = 1 sayılmalı: bekleyen (0) ve kalıcı hataya
    düşmüş (-1) kararlar arayüzde görünmediği için sayıma da girmemeli."""
    _ekle_ve_isle(conn, "kvkk", "İşlenmiş", "https://example.com/p1")
    db.insert_karar_if_new(
        conn, kaynak="bddk", baslik="Bekleyen", tarih="2026-01-01",
        kaynak_url="https://example.com/p2", ozet_ham="x",
    )
    db.insert_karar_if_new(
        conn, kaynak="spk", baslik="Kalıcı Hata", tarih="2026-01-01",
        kaynak_url="https://example.com/p3", ozet_ham="x",
    )
    hatali_id = next(
        k["id"] for k in db.get_pending_kararlar(conn) if k["baslik"] == "Kalıcı Hata"
    )
    for _ in range(3):
        db.mark_karar_failed(conn, hatali_id)

    assert db.get_kaynak_sayilari(conn) == {"kvkk": 1}


def test_get_kaynak_sayilari_returns_empty_dict_when_no_kararlar(conn):
    assert db.get_kaynak_sayilari(conn) == {}


def test_mark_karar_failed_respects_configurable_threshold(conn, monkeypatch):
    """MAX_KARAR_DENEME tek bir yerde (db.py) tanımlanmalı; classifier.py'deki
    ayrı bir sabit ile senkronsuzluk (drift) riski taşımamalı. Bu test eşiği
    monkeypatch ile değiştirip mark_karar_failed'in gerçekten bu modül
    sabitini okuduğunu (hardcoded 3 değil) kanıtlar."""
    monkeypatch.setattr(db, "MAX_KARAR_DENEME", 2)
    db.insert_karar_if_new(
        conn, kaynak="kvkk", baslik="Karar", tarih="2026-01-01",
        kaynak_url="https://example.com/esik", ozet_ham="Karar",
    )
    karar_id = db.get_pending_kararlar(conn)[0]["id"]

    assert db.mark_karar_failed(conn, karar_id) is False
    assert db.mark_karar_failed(conn, karar_id) is True


def test_karar_var_mi_returns_false_for_unknown_url(conn):
    assert db.karar_var_mi(conn, "https://example.com/hic-yok") is False


def test_karar_var_mi_returns_true_for_known_url(conn):
    db.insert_karar_if_new(
        conn, kaynak="kvkk", baslik="Karar", tarih="2026-01-01",
        kaynak_url="https://example.com/biliniyor", ozet_ham="x",
    )
    assert db.karar_var_mi(conn, "https://example.com/biliniyor") is True


def test_init_db_migrates_old_spk_url_scheme_to_avoid_duplicates(conn):
    """SPK kararlarının kaynak_url'i eskiden SPA sayfasına gidiyordu,
    artık doğrudan PDF API'sine gidiyor. Migrasyon çalışmazsa, aynı
    karar --scrape'in bir sonraki koşusunda YENİ url ile ikinci kez
    eklenir (kaynak_url UNIQUE olduğu için karar_var_mi bunları farklı
    görür)."""
    conn.execute(
        "INSERT INTO kararlar (kaynak, baslik, tarih, kaynak_url, ozet_ham) "
        "VALUES ('spk', 'Eski Şemalı Karar', '2026-01-01', "
        "'https://mevzuat.spk.gov.tr/IlkeKarari/Dosya/377', 'x')"
    )
    conn.commit()
    db.init_db(conn)
    satir = conn.execute(
        "SELECT kaynak_url FROM kararlar WHERE baslik = 'Eski Şemalı Karar'"
    ).fetchone()
    assert satir["kaynak_url"] == "https://mevzuat.spk.gov.tr/api/IlkeKarari/File/377"


def test_init_db_migration_does_not_touch_other_kaynaklar(conn):
    conn.execute(
        "INSERT INTO kararlar (kaynak, baslik, tarih, kaynak_url, ozet_ham) "
        "VALUES ('kvkk', 'KVKK Karar', '2026-01-01', "
        "'https://www.kvkk.gov.tr/Icerik/1/1', 'x')"
    )
    conn.commit()
    db.init_db(conn)
    satir = conn.execute(
        "SELECT kaynak_url FROM kararlar WHERE baslik = 'KVKK Karar'"
    ).fetchone()
    assert satir["kaynak_url"] == "https://www.kvkk.gov.tr/Icerik/1/1"


def test_init_db_migration_is_idempotent(conn):
    conn.execute(
        "INSERT INTO kararlar (kaynak, baslik, tarih, kaynak_url, ozet_ham) "
        "VALUES ('spk', 'Eski Şemalı Karar', '2026-01-01', "
        "'https://mevzuat.spk.gov.tr/IlkeKarari/Dosya/377', 'x')"
    )
    conn.commit()
    db.init_db(conn)
    db.init_db(conn)
    sayi = conn.execute(
        "SELECT COUNT(*) AS n FROM kararlar WHERE baslik = 'Eski Şemalı Karar'"
    ).fetchone()["n"]
    assert sayi == 1
