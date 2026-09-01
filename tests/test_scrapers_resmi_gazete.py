import json
from pathlib import Path
from unittest.mock import Mock, patch

import db
from scrapers import resmi_gazete
from scrapers import tammetin

FIXTURE = Path(__file__).parent / "fixtures" / "resmi_gazete_kararlar_sample.json"


def _fixture_veri() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_kararlar_maps_fields_and_sorts_newest_first():
    kararlar = resmi_gazete.parse_kararlar(_fixture_veri())
    assert len(kararlar) == 3
    assert kararlar[0]["tarih"] == "2026-08-29"
    assert "Özel Hastaneler" in kararlar[0]["baslik"]
    assert kararlar[1]["tarih"] == "2026-08-29"
    assert "Askeri Yasak Bölge" in kararlar[1]["baslik"]
    assert kararlar[2]["tarih"] == "2026-08-28"
    assert "İstihdamı Koruma" in kararlar[2]["baslik"]
    assert kararlar[0]["ozet_ham"] == kararlar[0]["baslik"]


def test_parse_kararlar_builds_absolute_fihrist_url():
    kararlar = resmi_gazete.parse_kararlar(
        _fixture_veri(), base_url="https://www.resmigazete.gov.tr/"
    )
    for karar in kararlar:
        assert karar["kaynak_url"].startswith(
            "https://www.resmigazete.gov.tr/fihrist?tarih="
        )


def test_fetch_veri_posts_json_body_and_returns_parsed_response():
    fake_response = Mock()
    fake_response.json.return_value = {"data": []}
    fake_response.raise_for_status = Mock()
    with patch(
        "scrapers.resmi_gazete.requests.post", return_value=fake_response
    ) as mock_post:
        veri = resmi_gazete.fetch_veri("https://example.com/api")
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert "User-Agent" in kwargs["headers"]
    assert kwargs["json"]["parameters"]["mevzuatTuru"] == "2"
    assert kwargs["json"]["parameters"]["searchtype"] == 1
    assert veri == {"data": []}


def test_scrape_and_store_inserts_new_kararlar(conn):
    with patch(
        "scrapers.resmi_gazete.fetch_veri", return_value=_fixture_veri()
    ):
        yeni_sayisi = resmi_gazete.scrape_and_store(conn)
    assert yeni_sayisi == 3
    assert len(db.get_pending_kararlar(conn)) == 3


def test_scrape_and_store_is_idempotent(conn):
    with patch(
        "scrapers.resmi_gazete.fetch_veri", return_value=_fixture_veri()
    ):
        resmi_gazete.scrape_and_store(conn)
        ikinci_calistirma = resmi_gazete.scrape_and_store(conn)
    assert ikinci_calistirma == 0


def test_scrape_and_store_respects_limit(conn):
    with patch(
        "scrapers.resmi_gazete.fetch_veri", return_value=_fixture_veri()
    ):
        yeni_sayisi = resmi_gazete.scrape_and_store(conn, limit=1)
    assert yeni_sayisi == 1


def test_parse_kararlar_gives_distinct_urls_to_same_day_items():
    kararlar = resmi_gazete.parse_kararlar(_fixture_veri())
    ayni_gun = [k for k in kararlar if k["tarih"] == "2026-08-29"]
    assert len(ayni_gun) == 2
    assert ayni_gun[0]["kaynak_url"] != ayni_gun[1]["kaynak_url"]


def test_parse_kararlar_skips_record_missing_konu_instead_of_raising(caplog):
    """spk.py'deki aynı bulgu sınıfı: "konu" veya "url" eksikse eski
    davranış ham bir KeyError fırlatıp o turdaki TÜM Resmi Gazete
    kararlarını tek bir bozuk kayıt yüzünden kaybediyordu."""
    import logging

    veri = _fixture_veri()
    del veri["data"][0]["konu"]

    with caplog.at_level(logging.WARNING):
        kararlar = resmi_gazete.parse_kararlar(veri)

    assert len(kararlar) == 2
    assert "konu" in caplog.text


def test_parse_kararlar_skips_record_missing_url_instead_of_raising(caplog):
    import logging

    veri = _fixture_veri()
    del veri["data"][1]["url"]

    with caplog.at_level(logging.WARNING):
        kararlar = resmi_gazete.parse_kararlar(veri)

    assert len(kararlar) == 2
    assert "url" in caplog.text


def test_fetch_veri_passes_guven_paketi_to_requests():
    fake_response = Mock()
    fake_response.json.return_value = {"data": []}
    fake_response.raise_for_status = Mock()
    with patch("scrapers.resmi_gazete.requests.post", return_value=fake_response) as mock_post:
        resmi_gazete.fetch_veri("https://example.com/api")
    _, kwargs = mock_post.call_args
    assert kwargs["verify"] == tammetin.guven_paketi()


FIHRIST_HTML = """
<html><body>
<div class="html-subtitle">YÖNETMELİKLER</div>
<div class="fihrist-item mb-1">
  <a href="https://www.resmigazete.gov.tr/eskiler/2026/09/20260901-1.htm" data-modal="True">
    –– İzmir Tınaztepe Üniversitesi Lisansüstü Eğitim-Öğretim Yönetmeliğinde Değişiklik Yapılmasına Dair Yönetmelik
  </a>
</div>
<div class="fihrist-item mb-1">
  <a href="https://www.resmigazete.gov.tr/eskiler/2026/09/20260901-2.htm" data-modal="True">
    –– İzmir Tınaztepe Üniversitesi Ön Lisans ve Lisans Eğitim Öğretim Yönetmeliğinde Değişiklik Yapılmasına Dair Yönetmelik
  </a>
</div>
</body></html>
"""

LISANSUSTU_BASLIK = (
    "İzmir Tınaztepe Üniversitesi Lisansüstü Eğitim-Öğretim Yönetmeliğinde "
    "Değişiklik Yapılmasına Dair Yönetmelik"
)
ON_LISANS_BASLIK = (
    "İzmir Tınaztepe Üniversitesi Ön Lisans ve Lisans Eğitim Öğretim "
    "Yönetmeliğinde Değişiklik Yapılmasına Dair Yönetmelik"
)


def test_normalize_baslik_strips_leading_dash_prefix_and_collapses_whitespace():
    assert resmi_gazete._normalize_baslik("––  İzmir   Tınaztepe\n Üniversitesi ") == \
        "İzmir Tınaztepe Üniversitesi"


def test_fihrist_linkleri_maps_normalized_title_to_href():
    fake = Mock()
    fake.text = FIHRIST_HTML
    fake.raise_for_status = Mock()
    with patch("scrapers.resmi_gazete.requests.get", return_value=fake):
        linkler = resmi_gazete._fihrist_linkleri("2026-09-01")
    assert linkler[LISANSUSTU_BASLIK] == \
        "https://www.resmigazete.gov.tr/eskiler/2026/09/20260901-1.htm"
    assert linkler[ON_LISANS_BASLIK] == \
        "https://www.resmigazete.gov.tr/eskiler/2026/09/20260901-2.htm"


def test_fihrist_linkleri_returns_empty_dict_on_network_error(caplog):
    import logging

    with patch("scrapers.resmi_gazete.requests.get", side_effect=ConnectionError("zaman aşımı")):
        with caplog.at_level(logging.WARNING):
            linkler = resmi_gazete._fihrist_linkleri("2026-09-01")
    assert linkler == {}
    assert "indirilemedi" in caplog.text


def test_fihrist_linkleri_passes_guven_paketi_to_requests():
    fake = Mock()
    fake.text = FIHRIST_HTML
    fake.raise_for_status = Mock()
    with patch("scrapers.resmi_gazete.requests.get", return_value=fake) as mock_get:
        resmi_gazete._fihrist_linkleri("2026-09-01")
    _, kwargs = mock_get.call_args
    assert kwargs["verify"] == tammetin.guven_paketi()


def test_madde_url_bul_returns_matching_href():
    fake = Mock()
    fake.text = FIHRIST_HTML
    fake.raise_for_status = Mock()
    with patch("scrapers.resmi_gazete.requests.get", return_value=fake):
        url = resmi_gazete._madde_url_bul("2026-09-01", LISANSUSTU_BASLIK, {})
    assert url == "https://www.resmigazete.gov.tr/eskiler/2026/09/20260901-1.htm"


def test_madde_url_bul_returns_none_when_no_match():
    fake = Mock()
    fake.text = FIHRIST_HTML
    fake.raise_for_status = Mock()
    with patch("scrapers.resmi_gazete.requests.get", return_value=fake):
        url = resmi_gazete._madde_url_bul("2026-09-01", "Bambaşka Bir Başlık", {})
    assert url is None


def test_madde_url_bul_uses_cache_and_fetches_fihrist_only_once():
    fake = Mock()
    fake.text = FIHRIST_HTML
    fake.raise_for_status = Mock()
    cache: dict = {}
    with patch("scrapers.resmi_gazete.requests.get", return_value=fake) as mock_get:
        resmi_gazete._madde_url_bul("2026-09-01", LISANSUSTU_BASLIK, cache)
        resmi_gazete._madde_url_bul("2026-09-01", ON_LISANS_BASLIK, cache)
    assert mock_get.call_count == 1
