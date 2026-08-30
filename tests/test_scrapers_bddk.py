from pathlib import Path
from unittest.mock import Mock, patch

import db
from scrapers import bddk
from scrapers import tammetin

FIXTURE = Path(__file__).parent / "fixtures" / "bddk_kararlar_sample.html"
BASE_URL = "https://www.bddk.org.tr/Mevzuat/Liste/55"


def test_parse_kararlar_extracts_three_items():
    html = FIXTURE.read_text(encoding="utf-8")
    kararlar = bddk.parse_kararlar(html, base_url=BASE_URL)
    assert len(kararlar) == 3


def test_parse_kararlar_parses_date_from_prefix_and_absolute_url():
    html = FIXTURE.read_text(encoding="utf-8")
    kararlar = bddk.parse_kararlar(html, base_url=BASE_URL)
    ilk = kararlar[0]
    assert ilk["tarih"] == "2026-08-06"
    assert ilk["kaynak_url"] == "https://www.bddk.org.tr/Mevzuat/DokumanGetir/1345"
    assert "BLG Varlık Yönetim A.Ş." in ilk["baslik"]
    assert ilk["ozet_ham"] == ilk["baslik"]


def test_parse_kararlar_parses_second_item():
    html = FIXTURE.read_text(encoding="utf-8")
    kararlar = bddk.parse_kararlar(html, base_url=BASE_URL)
    ikinci = kararlar[1]
    assert ikinci["tarih"] == "2026-06-11"
    assert "Dost Katılım Bankası" in ikinci["baslik"]
    assert ikinci["kaynak_url"] == "https://www.bddk.org.tr/Mevzuat/DokumanGetir/1338"


def test_fetch_page_returns_response_text():
    fake_response = Mock()
    fake_response.text = "<html>ok</html>"
    fake_response.raise_for_status = Mock()
    with patch("scrapers.bddk.requests.get", return_value=fake_response) as mock_get:
        html = bddk.fetch_page("https://example.com/kararlar")
    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    assert "User-Agent" in kwargs["headers"]
    assert html == "<html>ok</html>"


def test_scrape_and_store_inserts_new_kararlar(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.bddk.fetch_page", return_value=html), \
         patch("scrapers.bddk.tammetin.pdf_metni_cek", return_value=None):
        yeni_sayisi = bddk.scrape_and_store(conn)
    assert yeni_sayisi == 3
    assert len(db.get_pending_kararlar(conn)) == 3


def test_scrape_and_store_is_idempotent(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.bddk.fetch_page", return_value=html), \
         patch("scrapers.bddk.tammetin.pdf_metni_cek", return_value=None):
        bddk.scrape_and_store(conn)
        ikinci_calistirma = bddk.scrape_and_store(conn)
    assert ikinci_calistirma == 0


def test_scrape_and_store_respects_limit(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.bddk.fetch_page", return_value=html), \
         patch("scrapers.bddk.tammetin.pdf_metni_cek", return_value=None):
        yeni_sayisi = bddk.scrape_and_store(conn, limit=2)
    assert yeni_sayisi == 2


def test_scrape_and_store_uses_full_text_when_pdf_extraction_succeeds(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.bddk.fetch_page", return_value=html), \
         patch("scrapers.bddk.tammetin.pdf_metni_cek", return_value="Gerçek karar metni burada."):
        bddk.scrape_and_store(conn, limit=1)
    karar = db.get_pending_kararlar(conn)[0]
    assert karar["ozet_ham"] == "Gerçek karar metni burada."


def test_scrape_and_store_falls_back_to_title_when_pdf_extraction_fails(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.bddk.fetch_page", return_value=html), \
         patch("scrapers.bddk.tammetin.pdf_metni_cek", return_value=None):
        bddk.scrape_and_store(conn, limit=1)
    karar = db.get_pending_kararlar(conn)[0]
    assert karar["ozet_ham"] == karar["baslik"]


def test_scrape_and_store_does_not_refetch_full_text_for_known_kararlar(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.bddk.fetch_page", return_value=html), \
         patch("scrapers.bddk.tammetin.pdf_metni_cek", return_value=None) as mock_pdf:
        bddk.scrape_and_store(conn)
        ilk_cagri_sayisi = mock_pdf.call_count
        bddk.scrape_and_store(conn)
        ikinci_cagri_sayisi = mock_pdf.call_count
    assert ilk_cagri_sayisi == 3  # fixture'da 3 karar var
    assert ikinci_cagri_sayisi == ilk_cagri_sayisi  # ikinci koşuda yeni çağrı yok


def test_fetch_page_passes_guven_paketi_to_requests():
    fake_response = Mock()
    fake_response.text = "<html>ok</html>"
    fake_response.raise_for_status = Mock()
    with patch("scrapers.bddk.requests.get", return_value=fake_response) as mock_get:
        bddk.fetch_page("https://example.com/kararlar")
    _, kwargs = mock_get.call_args
    assert kwargs["verify"] == tammetin.guven_paketi()
