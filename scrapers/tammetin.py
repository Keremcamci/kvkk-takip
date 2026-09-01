import atexit
import io
import logging
import os
import tempfile
from pathlib import Path

import certifi
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from scrapers.common import USER_AGENT

MAKS_PDF_BAYT = 5_000_000
MAKS_METIN_KARAKTER = 6000

_EK_SERTIFIKALAR_DIZINI = Path(__file__).parent / "certs"
guven_paketi_yolu: str | None = None


def guven_paketi() -> str:
    # Bazı TR kamu sitelerinin sunucusu TLS handshake'inde ara
    # sertifikayı GÖNDERMİYOR (BDDK: GlobalSign RSA OV SSL CA 2018,
    # Resmi Gazete: GeoTrust TLS RSA CA G1) — tarayıcılar bunu AIA ile
    # otomatik telafi eder, requests/certifi etmez. Kökleri zaten
    # certifi'de güvenilir; scrapers/certs/ altındaki HER .pem dosyası
    # temel pakete eklenir — yeni bir site aynı sorunu verirse tek
    # yapılması gereken oraya bir dosya daha eklemek.
    #
    # Temel paket normalde certifi'nin güncel kök listesi, ama operatör
    # TLS'i yeniden imzalayan bir kurumsal proxy arkasındaysa (requests
    # bunu REQUESTS_CA_BUNDLE/CURL_CA_BUNDLE ile onore eder — AMA SADECE
    # verify= AÇIKÇA VERİLMEDİĞİNDE; explicit verify= bu env
    # değişkenlerini görmezden gelir) operatörün kendi paketi esas
    # alınır, aksi halde bu modülün eklediği verify= parametreleri
    # operatörün proxy'sini sessizce devre dışı bırakırdı.
    global guven_paketi_yolu
    if guven_paketi_yolu is None:
        temel_yol = (
            os.environ.get("REQUESTS_CA_BUNDLE")
            or os.environ.get("CURL_CA_BUNDLE")
            or certifi.where()
        )
        parcalar = [Path(temel_yol).read_bytes()]
        for sertifika in sorted(_EK_SERTIFIKALAR_DIZINI.glob("*.pem")):
            parcalar.append(sertifika.read_bytes())
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as f:
            f.write(b"\n".join(parcalar))
            guven_paketi_yolu = f.name
        atexit.register(_gecici_dosyayi_sil, guven_paketi_yolu)
    return guven_paketi_yolu


def _gecici_dosyayi_sil(yol: str) -> None:
    """guven_paketi()'nin oluşturduğu geçici dosyayı process çıkışında
    temizler — her `python backend.py --scrape` çalıştırmasında ~240 KB
    (certifi paketi büyüklüğü) sızdırmamak için."""
    Path(yol).unlink(missing_ok=True)


def pdf_metni_cek(url: str, timeout: int = 15) -> str | None:
    try:
        response = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=timeout, verify=guven_paketi()
        )
        response.raise_for_status()
    except (requests.RequestException, ConnectionError, OSError) as exc:
        logging.warning("Tam metin indirilemedi (%s): %s", url, exc)
        return None

    content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    pdf_imzali = response.content[:5] == b"%PDF-"
    if content_type != "application/pdf" and not pdf_imzali:
        logging.warning("Beklenmeyen içerik tipi, PDF değil (%s): %s", url, content_type)
        return None

    if len(response.content) > MAKS_PDF_BAYT:
        logging.warning("PDF çok büyük, atlanıyor (%s): %d bayt", url, len(response.content))
        return None

    try:
        reader = PdfReader(io.BytesIO(response.content))
        metin = "\n".join(page.extract_text() or "" for page in reader.pages)
    except PyPdfError as exc:
        logging.warning("PDF ayrıştırılamadı (%s): %s", url, exc)
        return None

    metin = metin.strip()
    if not metin:
        logging.warning("PDF'ten metin çıkarılamadı (taranmış/görsel olabilir): %s", url)
        return None
    return metin[:MAKS_METIN_KARAKTER]


def kvkk_sayfa_metni_cek(url: str, timeout: int = 15) -> str | None:
    try:
        response = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=timeout, verify=guven_paketi()
        )
        response.raise_for_status()
    except (requests.RequestException, ConnectionError, OSError) as exc:
        logging.warning("KVKK detay sayfası indirilemedi (%s): %s", url, exc)
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    makale = soup.select_one("div.news__detail-article")
    if makale is None:
        logging.warning("KVKK detay sayfasında beklenen içerik bulunamadı: %s", url)
        return None

    metin = makale.get_text(separator=" ", strip=True)
    # str.strip() görünmez Unicode karakterleri (ör. U+200B ZERO WIDTH
    # SPACE) KALDIRMAZ — isspace() bunlar için False döner. Bu yüzden
    # boşluk kontrolü ayrıca bu karakterleri de çıkararak yapılır; asıl
    # döndürülen metin YİNE `metin` (aşırı temizlenmemiş) değişkeninden
    # gelir, yalnızca "gerçekten boş mu?" kontrolü daha sıkı.
    gorunmez_temizlenmis = metin.strip("​‌‍﻿ \t\n\r")
    if not gorunmez_temizlenmis:
        logging.warning("KVKK detay sayfasında metin bulunamadı (görünmez/boş içerik olabilir): %s", url)
        return None
    return metin[:MAKS_METIN_KARAKTER]


def resmi_gazete_madde_metni_cek(url: str, timeout: int = 15) -> str | None:
    try:
        response = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=timeout, verify=guven_paketi()
        )
        response.raise_for_status()
    except (requests.RequestException, ConnectionError, OSError) as exc:
        logging.warning("Resmi Gazete madde sayfası indirilemedi (%s): %s", url, exc)
        return None

    # Bu .htm sayfaları eski bir "MS Word'den web sayfası olarak kaydet"
    # çıktısı ve Windows-1254 (Türkçe) kodlamalı — HTTP Content-Type
    # header'ında charset yok, sadece HTML içindeki <meta>'da beyan
    # ediliyor. response.text (requests'in kendi tahmini) bu yüzden
    # Türkçe karakterleri bozuk decode eder; bayt içeriği elle
    # windows-1254 olarak decode edilir.
    html = response.content.decode("windows-1254", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    icerik = soup.select_one("div.Section1") or soup.body
    if icerik is None:
        logging.warning("Resmi Gazete madde sayfasında beklenen içerik bulunamadı: %s", url)
        return None

    metin = icerik.get_text(separator=" ", strip=True)
    gorunmez_temizlenmis = metin.strip("​‌‍﻿ \t\n\r")
    if not gorunmez_temizlenmis:
        logging.warning(
            "Resmi Gazete madde sayfasında metin bulunamadı (görünmez/boş içerik olabilir): %s",
            url,
        )
        return None
    return metin[:MAKS_METIN_KARAKTER]
