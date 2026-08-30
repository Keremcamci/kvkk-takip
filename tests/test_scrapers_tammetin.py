import logging
from pathlib import Path
from unittest.mock import Mock, patch

from scrapers import tammetin

BDDK_PDF_FIXTURE = Path(__file__).parent / "fixtures" / "bddk_karar_sample.pdf"
KVKK_DETAY_FIXTURE = Path(__file__).parent / "fixtures" / "kvkk_karar_detay_sample.html"


def _pdf_response(content_type="application/pdf"):
    fake = Mock()
    fake.headers = {"Content-Type": content_type}
    fake.content = BDDK_PDF_FIXTURE.read_bytes()
    fake.raise_for_status = Mock()
    return fake


def test_pdf_metni_cek_extracts_real_text_from_pdf():
    with patch("scrapers.tammetin.requests.get", return_value=_pdf_response()):
        metin = tammetin.pdf_metni_cek("https://example.com/karar.pdf")
    assert metin is not None
    assert "BLG Varlık Yönetim" in metin
    assert "karar verilmiştir" in metin


def test_pdf_metni_cek_returns_none_on_network_error(caplog):
    with patch("scrapers.tammetin.requests.get", side_effect=ConnectionError("bağlantı koptu")):
        with caplog.at_level(logging.WARNING):
            metin = tammetin.pdf_metni_cek("https://example.com/karar.pdf")
    assert metin is None
    assert "indirilemedi" in caplog.text


def test_pdf_metni_cek_returns_none_for_non_pdf_content_type(caplog):
    with patch("scrapers.tammetin.requests.get", return_value=_pdf_response(content_type="text/html")):
        with caplog.at_level(logging.WARNING):
            metin = tammetin.pdf_metni_cek("https://example.com/sayfa")
    assert metin is None
    assert "PDF değil" in caplog.text


def test_pdf_metni_cek_returns_none_when_file_too_large(caplog):
    fake = _pdf_response()
    fake.content = b"x" * (tammetin.MAKS_PDF_BAYT + 1)
    with patch("scrapers.tammetin.requests.get", return_value=fake):
        with caplog.at_level(logging.WARNING):
            metin = tammetin.pdf_metni_cek("https://example.com/buyuk.pdf")
    assert metin is None
    assert "çok büyük" in caplog.text


def test_pdf_metni_cek_returns_none_when_no_extractable_text(caplog):
    fake = _pdf_response()
    with patch("scrapers.tammetin.requests.get", return_value=fake), \
         patch("scrapers.tammetin.PdfReader") as mock_reader:
        sahte_sayfa = Mock()
        sahte_sayfa.extract_text.return_value = ""
        mock_reader.return_value.pages = [sahte_sayfa]
        with caplog.at_level(logging.WARNING):
            metin = tammetin.pdf_metni_cek("https://example.com/taranmis.pdf")
    assert metin is None
    assert "çıkarılamadı" in caplog.text


def test_pdf_metni_cek_truncates_to_max_length():
    fake = _pdf_response()
    with patch("scrapers.tammetin.requests.get", return_value=fake), \
         patch("scrapers.tammetin.PdfReader") as mock_reader:
        uzun_metin = "a" * (tammetin.MAKS_METIN_KARAKTER + 500)
        sahte_sayfa = Mock()
        sahte_sayfa.extract_text.return_value = uzun_metin
        mock_reader.return_value.pages = [sahte_sayfa]
        metin = tammetin.pdf_metni_cek("https://example.com/uzun.pdf")
    assert len(metin) == tammetin.MAKS_METIN_KARAKTER


def test_kvkk_sayfa_metni_cek_extracts_article_text_and_excludes_sidebar():
    fake = Mock()
    fake.text = KVKK_DETAY_FIXTURE.read_text(encoding="utf-8")
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake):
        metin = tammetin.kvkk_sayfa_metni_cek("https://www.kvkk.gov.tr/Icerik/7791/2023-2135")
    assert metin is not None
    assert "oybirliği ile karar verilmiştir" in metin
    assert "Duyurular" not in metin  # yan panel içeriğe sızmamalı


def test_kvkk_sayfa_metni_cek_returns_none_when_selector_not_found(caplog):
    fake = Mock()
    fake.text = "<html><body><p>Beklenmeyen sayfa yapısı</p></body></html>"
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake):
        with caplog.at_level(logging.WARNING):
            metin = tammetin.kvkk_sayfa_metni_cek("https://www.kvkk.gov.tr/Icerik/9999/yok")
    assert metin is None
    assert "bulunamadı" in caplog.text


def test_kvkk_sayfa_metni_cek_returns_none_on_network_error(caplog):
    with patch("scrapers.tammetin.requests.get", side_effect=ConnectionError("zaman aşımı")):
        with caplog.at_level(logging.WARNING):
            metin = tammetin.kvkk_sayfa_metni_cek("https://www.kvkk.gov.tr/Icerik/1/1")
    assert metin is None
    assert "indirilemedi" in caplog.text
