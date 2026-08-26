import db


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


def test_get_kararlar_by_profil_genel_only_returns_genel_tagged(conn):
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Finans Karar", tarih="2026-01-01", kaynak_url="https://example.com/8", ozet_ham="x")
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Genel Karar", tarih="2026-01-02", kaynak_url="https://example.com/9", ozet_ham="x")
    ids = {row["baslik"]: row["id"] for row in conn.execute("SELECT id, baslik FROM kararlar").fetchall()}

    db.update_karar_classification(conn, ids["Finans Karar"], ["finans"], "özet", [], False, "")
    db.update_karar_classification(conn, ids["Genel Karar"], ["genel"], "özet", [], False, "")

    genel_sonuc = db.get_kararlar_by_profil(conn, "genel")
    assert [k["baslik"] for k in genel_sonuc] == ["Genel Karar"]
