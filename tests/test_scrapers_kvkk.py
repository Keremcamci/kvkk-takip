from pathlib import Path
from unittest.mock import Mock, patch

import db
from scrapers import kvkk

FIXTURE = Path(__file__).parent / "fixtures" / "kvkk_kararlari_sample.html"


def test_parse_karar_listesi_extracts_three_items():
    html = FIXTURE.read_text(encoding="utf-8")
    kararlar = kvkk.parse_karar_listesi(html)
    assert len(kararlar) == 3


def test_parse_karar_listesi_parses_dotted_date_and_external_url():
    html = FIXTURE.read_text(encoding="utf-8")
    kararlar = kvkk.parse_karar_listesi(html)
    ilk = kararlar[0]
    assert ilk["tarih"] == "2026-07-22"
    assert ilk["kaynak_url"] == "https://www.resmigazete.gov.tr/eskiler/2026/08/20260813-3.pdf"
    assert "2026/1491 Sayılı Kararı" in ilk["baslik"]
    assert ilk["ozet_ham"] == ilk["baslik"]


def test_parse_karar_listesi_parses_slash_date_and_internal_url():
    html = FIXTURE.read_text(encoding="utf-8")
    kararlar = kvkk.parse_karar_listesi(html)
    ucuncu = kararlar[2]
    assert ucuncu["tarih"] == "2023-12-14"
    assert ucuncu["kaynak_url"] == "https://www.kvkk.gov.tr/Icerik/7791/2023-2135"


def test_fetch_page_returns_response_text():
    fake_response = Mock()
    fake_response.text = "<html>ok</html>"
    fake_response.raise_for_status = Mock()
    with patch("scrapers.kvkk.requests.get", return_value=fake_response) as mock_get:
        html = kvkk.fetch_page("https://example.com/kararlar")
    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    assert "User-Agent" in kwargs["headers"]
    assert html == "<html>ok</html>"


def test_scrape_and_store_inserts_new_kararlar(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.kvkk.fetch_page", return_value=html):
        yeni_sayisi = kvkk.scrape_and_store(conn)
    assert yeni_sayisi == 3
    assert len(db.get_pending_kararlar(conn)) == 3


def test_scrape_and_store_is_idempotent(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.kvkk.fetch_page", return_value=html):
        kvkk.scrape_and_store(conn)
        ikinci_calistirma = kvkk.scrape_and_store(conn)
    assert ikinci_calistirma == 0
