from urllib.parse import urljoin

import requests

import db
from scrapers.common import USER_AGENT

SPK_API_URL = "https://mevzuat.spk.gov.tr/api/Search/All"
SPK_BASE_URL = "https://mevzuat.spk.gov.tr/"
GECERLI_TURLER = {"Kurul Kararı", "İlke Kararı"}


def parse_kararlar(veri: list[dict], base_url: str = SPK_BASE_URL) -> list[dict]:
    kararlar = []
    for item in veri:
        if item.get("tur") not in GECERLI_TURLER:
            continue
        tarih_iso = item.get("kurulKararTarihi")
        if not tarih_iso:
            continue
        baslik = item["title"]
        kararlar.append({
            "baslik": baslik,
            "tarih": tarih_iso[:10],
            "kaynak_url": urljoin(base_url, item["link"]),
            "ozet_ham": baslik,
        })
    kararlar.sort(key=lambda k: k["tarih"], reverse=True)
    return kararlar


def fetch_veri(url: str = SPK_API_URL, timeout: int = 15) -> list[dict]:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    return response.json()


def scrape_and_store(conn, url: str = SPK_API_URL, limit: int = 10) -> int:
    veri = fetch_veri(url)
    kararlar = parse_kararlar(veri)[:limit]
    yeni_sayisi = 0
    for karar in kararlar:
        if db.insert_karar_if_new(conn, kaynak="spk", **karar):
            yeni_sayisi += 1
    return yeni_sayisi


if __name__ == "__main__":
    connection = db.get_connection()
    db.init_db(connection)
    yeni_sayisi = scrape_and_store(connection)
    print(f"{yeni_sayisi} yeni SPK kararı bulundu.")
    rows = connection.execute(
        "SELECT tarih, baslik FROM kararlar WHERE kaynak = 'spk' "
        "ORDER BY tarih DESC LIMIT 10"
    ).fetchall()
    for row in rows:
        print(f"- [{row['tarih']}] {row['baslik'][:100]}...")
    connection.close()
