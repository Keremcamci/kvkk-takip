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
    with patch("scrapers.kvkk.fetch_page", return_value=html), \
         patch("scrapers.kvkk.tammetin.pdf_metni_cek", return_value=None), \
         patch("scrapers.kvkk.tammetin.kvkk_sayfa_metni_cek", return_value=None):
        yeni_sayisi = kvkk.scrape_and_store(conn)
    assert yeni_sayisi == 3
    assert len(db.get_pending_kararlar(conn)) == 3


def test_parse_karar_listesi_resolves_relative_href_to_absolute_url():
    """BDDK ve SPK scraper'ları urljoin() kullanıyor, KVKK kullanmıyordu —
    KVKK sitesi relative bir href döndürürse veritabanına bozuk (site
    kökünden başlamayan, tarayıcıda kırık) bir URL yazılıyordu."""
    html = """
    <div class="members__item">
      <div class="members__item-meta">
        <h2>Relative Bağlantılı Bir Karar Hakkında Kişisel Verileri Koruma
        Kurulunun 05.03.2026 Tarihli ve 2026/9999 Sayılı Kararı</h2>
        <a class="read-more" href="/Icerik/9999/relative-karar">Devamını Gör</a>
      </div>
    </div>
    """
    (karar,) = kvkk.parse_karar_listesi(html)
    assert karar["kaynak_url"] == "https://www.kvkk.gov.tr/Icerik/9999/relative-karar"


def test_scrape_and_store_is_idempotent(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.kvkk.fetch_page", return_value=html), \
         patch("scrapers.kvkk.tammetin.pdf_metni_cek", return_value=None), \
         patch("scrapers.kvkk.tammetin.kvkk_sayfa_metni_cek", return_value=None):
        kvkk.scrape_and_store(conn)
        ikinci_calistirma = kvkk.scrape_and_store(conn)
    assert ikinci_calistirma == 0


def test_scrape_and_store_uses_kvkk_page_text_for_internal_kvkk_urls(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.kvkk.fetch_page", return_value=html), \
         patch("scrapers.kvkk.tammetin.pdf_metni_cek", return_value=None), \
         patch("scrapers.kvkk.tammetin.kvkk_sayfa_metni_cek", return_value="KVKK sayfasından gerçek özet."):
        kvkk.scrape_and_store(conn)
    koy_karari = next(
        k for k in db.get_pending_kararlar(conn) if "Köy Tüzel" in k["baslik"]
    )
    assert koy_karari["ozet_ham"] == "KVKK sayfasından gerçek özet."


def test_scrape_and_store_uses_pdf_text_for_external_urls(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.kvkk.fetch_page", return_value=html), \
         patch("scrapers.kvkk.tammetin.pdf_metni_cek", return_value="PDF'den gerçek metin."), \
         patch("scrapers.kvkk.tammetin.kvkk_sayfa_metni_cek", return_value=None):
        kvkk.scrape_and_store(conn)
    sadakat_karari = next(
        k for k in db.get_pending_kararlar(conn) if "Sadakat Kart" in k["baslik"]
    )
    assert sadakat_karari["ozet_ham"] == "PDF'den gerçek metin."


def test_scrape_and_store_falls_back_to_title_when_full_text_unavailable(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.kvkk.fetch_page", return_value=html), \
         patch("scrapers.kvkk.tammetin.pdf_metni_cek", return_value=None), \
         patch("scrapers.kvkk.tammetin.kvkk_sayfa_metni_cek", return_value=None):
        kvkk.scrape_and_store(conn)
    for karar in db.get_pending_kararlar(conn):
        assert karar["ozet_ham"] == karar["baslik"]


def test_scrape_and_store_does_not_refetch_full_text_for_known_kararlar(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.kvkk.fetch_page", return_value=html), \
         patch("scrapers.kvkk.tammetin.pdf_metni_cek", return_value=None) as mock_pdf, \
         patch("scrapers.kvkk.tammetin.kvkk_sayfa_metni_cek", return_value=None) as mock_sayfa:
        kvkk.scrape_and_store(conn)
        ilk_pdf, ilk_sayfa = mock_pdf.call_count, mock_sayfa.call_count
        kvkk.scrape_and_store(conn)
        ikinci_pdf, ikinci_sayfa = mock_pdf.call_count, mock_sayfa.call_count
    assert ilk_pdf == 2  # 2 dış (PDF) link
    assert ilk_sayfa == 1  # 1 dahili (kvkk.gov.tr) link
    assert ikinci_pdf == ilk_pdf
    assert ikinci_sayfa == ilk_sayfa
