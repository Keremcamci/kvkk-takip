import io
import logging

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from scrapers.common import USER_AGENT

MAKS_PDF_BAYT = 5_000_000
MAKS_METIN_KARAKTER = 6000


def pdf_metni_cek(url: str, timeout: int = 15) -> str | None:
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        response.raise_for_status()
    except (requests.RequestException, ConnectionError) as exc:
        logging.warning("Tam metin indirilemedi (%s): %s", url, exc)
        return None

    content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
    if content_type != "application/pdf":
        logging.warning("Beklenmeyen içerik tipi, PDF değil (%s): %s", url, content_type)
        return None

    if len(response.content) > MAKS_PDF_BAYT:
        logging.warning("PDF çok büyük, atlanıyor (%s): %d bayt", url, len(response.content))
        return None

    try:
        reader = PdfReader(io.BytesIO(response.content))
        metin = "\n".join(page.extract_text() or "" for page in reader.pages)
    except PdfReadError as exc:
        logging.warning("PDF ayrıştırılamadı (%s): %s", url, exc)
        return None

    metin = metin.strip()
    if not metin:
        logging.warning("PDF'ten metin çıkarılamadı (taranmış/görsel olabilir): %s", url)
        return None
    return metin[:MAKS_METIN_KARAKTER]


def kvkk_sayfa_metni_cek(url: str, timeout: int = 15) -> str | None:
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        response.raise_for_status()
    except (requests.RequestException, ConnectionError) as exc:
        logging.warning("KVKK detay sayfası indirilemedi (%s): %s", url, exc)
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    makale = soup.select_one("div.news__detail-article")
    if makale is None:
        logging.warning("KVKK detay sayfasında beklenen içerik bulunamadı: %s", url)
        return None

    metin = makale.get_text(separator=" ", strip=True)
    return metin[:MAKS_METIN_KARAKTER] if metin else None
