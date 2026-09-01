import logging
from pathlib import Path
from unittest.mock import Mock, patch

from pypdf.errors import ParseError

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


def test_pdf_metni_cek_accepts_differently_cased_content_type():
    """Bir sunucu "Content-Type: Application/PDF" (farklı büyük/küçük harf)
    gönderse bile, ya da başlık PDF olduğunu doğru söylemese bile gerçek
    PDF imza baytları (%PDF-) varsa içerik kabul edilmeli."""
    with patch(
        "scrapers.tammetin.requests.get",
        return_value=_pdf_response(content_type="Application/PDF"),
    ):
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
    # _pdf_response()'ın varsayılan içeriği gerçek bir PDF'in baytlarıdır
    # (BDDK fixture) — Fix 5'in %PDF- imza kontrolü sayesinde bu artık
    # content_type ne olursa olsun kabul edilir. Bu testin iddia ettiği
    # senaryo (gerçekten PDF OLMAYAN bir yanıt) için içeriği de gerçek
    # dışı bir baytla değiştirmek gerekir, aksi halde imza kontrolü testi
    # geçersiz kılar.
    fake = _pdf_response(content_type="text/html")
    fake.content = b"<html><body>Bu bir PDF degil</body></html>"
    with patch("scrapers.tammetin.requests.get", return_value=fake):
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


def test_pdf_metni_cek_catches_parseerror_and_returns_none(caplog):
    fake = _pdf_response()
    with patch("scrapers.tammetin.requests.get", return_value=fake), \
         patch("scrapers.tammetin.PdfReader") as mock_reader:
        mock_reader.side_effect = ParseError("Malformed PDF structure")
        with caplog.at_level(logging.WARNING):
            metin = tammetin.pdf_metni_cek("https://example.com/malformed.pdf")
    assert metin is None
    assert "ayrıştırılamadı" in caplog.text


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


def test_kvkk_sayfa_metni_cek_falls_back_to_none_for_invisible_only_content(caplog):
    """BeautifulSoup'un get_text(strip=True) fonksiyonu görünmez Unicode
    karakterleri (ör. U+200B ZERO WIDTH SPACE) KALDIRMAZ, Python'ın
    str.strip()'i de bunları temizlemez ('​'.isspace() False döner).
    Eşleşen div SADECE görünmez karakterler içeriyorsa (KVKK'nın işaretlemesi
    ileride değişip boş-ama-var bir eleman verirse gerçekçi bir senaryo),
    eski davranış bu görünmez çöpü gerçek içerikmiş gibi döndürüyordu;
    doğrusu, tamamen boş string durumunda olduğu gibi, başlığa düşmek."""
    html = (
        '<html><body><div class="news__detail-article">'
        "​​‌﻿"
        "</div></body></html>"
    )
    fake = Mock()
    fake.text = html
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake):
        with caplog.at_level(logging.WARNING):
            metin = tammetin.kvkk_sayfa_metni_cek("https://www.kvkk.gov.tr/Icerik/1/1")
    assert metin is None
    assert "bulunamadı" in caplog.text


def test_kvkk_sayfa_metni_cek_truncates_to_max_length():
    uzun_metin = "a" * (tammetin.MAKS_METIN_KARAKTER + 500)
    html = f'<html><body><div class="news__detail-article">{uzun_metin}</div></body></html>'
    fake = Mock()
    fake.text = html
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake):
        metin = tammetin.kvkk_sayfa_metni_cek("https://www.kvkk.gov.tr/Icerik/1/1")
    assert len(metin) == tammetin.MAKS_METIN_KARAKTER


def test_guven_paketi_includes_all_committed_intermediate_certificates():
    yol = tammetin.guven_paketi()
    icerik = Path(yol).read_bytes()
    sertifikalar = list(tammetin._EK_SERTIFIKALAR_DIZINI.glob("*.pem"))
    assert len(sertifikalar) >= 2  # en az BDDK + Resmi Gazete
    for sertifika in sertifikalar:
        assert sertifika.read_bytes() in icerik


def test_guven_paketi_includes_certifi_default_bundle():
    import certifi

    yol = tammetin.guven_paketi()
    icerik = Path(yol).read_bytes()
    certifi_icerik = Path(certifi.where()).read_bytes()
    assert certifi_icerik in icerik


def test_guven_paketi_is_cached_across_calls():
    ilk = tammetin.guven_paketi()
    ikinci = tammetin.guven_paketi()
    assert ilk == ikinci


def test_pdf_metni_cek_passes_guven_paketi_to_requests():
    with patch("scrapers.tammetin.requests.get", return_value=_pdf_response()) as mock_get:
        tammetin.pdf_metni_cek("https://example.com/karar.pdf")
    _, kwargs = mock_get.call_args
    assert kwargs["verify"] == tammetin.guven_paketi()


def test_kvkk_sayfa_metni_cek_passes_guven_paketi_to_requests():
    fake = Mock()
    fake.text = KVKK_DETAY_FIXTURE.read_text(encoding="utf-8")
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake) as mock_get:
        tammetin.kvkk_sayfa_metni_cek("https://www.kvkk.gov.tr/Icerik/7791/2023-2135")
    _, kwargs = mock_get.call_args
    assert kwargs["verify"] == tammetin.guven_paketi()


def test_pdf_metni_cek_returns_none_when_guven_paketi_raises_oserror(caplog):
    with patch("scrapers.tammetin.guven_paketi", side_effect=OSError("örnek hata")):
        with caplog.at_level(logging.WARNING):
            metin = tammetin.pdf_metni_cek("https://example.com/karar.pdf")
    assert metin is None
    assert "indirilemedi" in caplog.text


def test_guven_paketi_includes_resmi_gazete_intermediate_certificate():
    yol = tammetin.guven_paketi()
    icerik = Path(yol).read_bytes()
    ara_sertifika = (tammetin._EK_SERTIFIKALAR_DIZINI / "geotrust_tls_rsa_ca_g1.pem").read_bytes()
    assert ara_sertifika in icerik


def test_guven_paketi_uses_requests_ca_bundle_env_var_as_base_when_set(monkeypatch, tmp_path):
    """verify= açıkça verildiğinde requests REQUESTS_CA_BUNDLE'ı YOK SAYAR
    — bu yüzden guven_paketi() bu env değişkenini KENDİSİ okuyup temel
    paket olarak kullanmalı, aksi halde kurumsal proxy arkasındaki bir
    operatörün kendi CA paketi sessizce devre dışı kalır."""
    ozel_paket = tmp_path / "ozel_ca_bundle.pem"
    ozel_paket.write_bytes(b"-----BEGIN CERTIFICATE-----\nSAHTE\n-----END CERTIFICATE-----\n")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(ozel_paket))
    onceki_deger = tammetin.guven_paketi_yolu
    tammetin.guven_paketi_yolu = None
    try:
        yol = tammetin.guven_paketi()
        icerik = Path(yol).read_bytes()
        assert b"SAHTE" in icerik
    finally:
        tammetin.guven_paketi_yolu = onceki_deger


def test_guven_paketi_falls_back_to_certifi_when_no_env_var_set(monkeypatch):
    import certifi

    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    onceki_deger = tammetin.guven_paketi_yolu
    tammetin.guven_paketi_yolu = None
    try:
        yol = tammetin.guven_paketi()
        icerik = Path(yol).read_bytes()
        certifi_icerik = Path(certifi.where()).read_bytes()
        assert certifi_icerik in icerik
    finally:
        tammetin.guven_paketi_yolu = onceki_deger


def test_resmi_gazete_madde_metni_cek_extracts_and_decodes_windows1254():
    html = (
        "<html><body><div class=Section1>"
        "MADDE 1- Türkçe karakterler doğru gösterilmeli: ışığöüç"
        "</div></body></html>"
    )
    fake = Mock()
    fake.content = html.encode("windows-1254")
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake):
        metin = tammetin.resmi_gazete_madde_metni_cek(
            "https://www.resmigazete.gov.tr/eskiler/2026/09/20260901-1.htm"
        )
    assert metin is not None
    assert "ışığöüç" in metin


def test_resmi_gazete_madde_metni_cek_falls_back_to_body_when_section1_missing():
    html = "<html><body>MADDE 1- İçerik burada.</body></html>"
    fake = Mock()
    fake.content = html.encode("windows-1254")
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake):
        metin = tammetin.resmi_gazete_madde_metni_cek("https://example.com/madde.htm")
    assert metin == "MADDE 1- İçerik burada."


def test_resmi_gazete_madde_metni_cek_returns_none_on_network_error(caplog):
    with patch("scrapers.tammetin.requests.get", side_effect=ConnectionError("zaman aşımı")):
        with caplog.at_level(logging.WARNING):
            metin = tammetin.resmi_gazete_madde_metni_cek(
                "https://www.resmigazete.gov.tr/eskiler/2026/09/x.htm"
            )
    assert metin is None
    assert "indirilemedi" in caplog.text


def test_resmi_gazete_madde_metni_cek_returns_none_for_whitespace_only_content(caplog):
    # NOT: KVKK'nın "görünmez Unicode karakter" testinin eşi burada
    # uygulanamaz — bu sayfalar sabit tek baytlık windows-1254 kodlamalı
    # olduğu için U+200B gibi çok baytlı karakterleri hiç temsil edemez.
    # Windows-1254'te temsil edilebilen "boş içerik" senaryosu düz
    # boşluk/tab/newline'dır, bu test onu kapsıyor.
    html = "<html><body><div class=Section1>   \r\n\t  </div></body></html>"
    fake = Mock()
    fake.content = html.encode("windows-1254")
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake):
        with caplog.at_level(logging.WARNING):
            metin = tammetin.resmi_gazete_madde_metni_cek("https://example.com/x.htm")
    assert metin is None
    assert "bulunamadı" in caplog.text


def test_resmi_gazete_madde_metni_cek_truncates_to_max_length():
    uzun_metin = "a" * (tammetin.MAKS_METIN_KARAKTER + 500)
    html = f"<html><body><div class=Section1>{uzun_metin}</div></body></html>"
    fake = Mock()
    fake.content = html.encode("windows-1254")
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake):
        metin = tammetin.resmi_gazete_madde_metni_cek("https://example.com/x.htm")
    assert len(metin) == tammetin.MAKS_METIN_KARAKTER


def test_resmi_gazete_madde_metni_cek_passes_guven_paketi_to_requests():
    html = "<html><body><div class=Section1>MADDE 1- İçerik.</div></body></html>"
    fake = Mock()
    fake.content = html.encode("windows-1254")
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake) as mock_get:
        tammetin.resmi_gazete_madde_metni_cek("https://example.com/x.htm")
    _, kwargs = mock_get.call_args
    assert kwargs["verify"] == tammetin.guven_paketi()
