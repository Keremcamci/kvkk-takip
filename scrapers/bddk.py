import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import db
from scrapers import tammetin
from scrapers.common import USER_AGENT

BDDK_LIST_URL = "https://www.bddk.org.tr/Mevzuat/Liste/55"

_TARIH_NO_RE = re.compile(
    r"^\((?P<gun>\d{2})\.(?P<ay>\d{2})\.(?P<yil>\d{4}) - (?P<no>\d+)\)"
)


def _parse_tarih(baslik: str) -> str | None:
    m = _TARIH_NO_RE.match(baslik)
    if not m:
        return None
    return f"{m.group('yil')}-{m.group('ay')}-{m.group('gun')}"


def parse_kararlar(html: str, base_url: str = BDDK_LIST_URL) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    kararlar = []
    for a in soup.select("a.mevzuatBaslik"):
        href = a.get("href")
        if not href:
            continue
        baslik = a.get_text(strip=True)
        kararlar.append({
            "baslik": baslik,
            "tarih": _parse_tarih(baslik),
            "kaynak_url": urljoin(base_url, href),
            "ozet_ham": baslik,
        })
    return kararlar


def fetch_page(url: str = BDDK_LIST_URL, timeout: int = 15) -> str:
    response = requests.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=timeout, verify=tammetin.guven_paketi()
    )
    response.raise_for_status()
    return response.text


def scrape_and_store(conn, url: str = BDDK_LIST_URL, limit: int = 10) -> int:
    html = fetch_page(url)
    kararlar = parse_kararlar(html, base_url=url)[:limit]
    yeni_sayisi = 0
    for karar in kararlar:
        if db.karar_var_mi(conn, karar["kaynak_url"]):
            continue
        tam_metin = tammetin.pdf_metni_cek(karar["kaynak_url"])
        if tam_metin:
            karar["ozet_ham"] = tam_metin
        if db.insert_karar_if_new(conn, kaynak="bddk", **karar):
            yeni_sayisi += 1
    return yeni_sayisi


if __name__ == "__main__":
    connection = db.get_connection()
    db.init_db(connection)
    yeni_sayisi = scrape_and_store(connection)
    print(f"{yeni_sayisi} yeni BDDK kararı bulundu.")
    rows = connection.execute(
        "SELECT tarih, baslik FROM kararlar WHERE kaynak = 'bddk' "
        "ORDER BY tarih DESC LIMIT 10"
    ).fetchall()
    for row in rows:
        print(f"- [{row['tarih']}] {row['baslik'][:100]}...")
    connection.close()
