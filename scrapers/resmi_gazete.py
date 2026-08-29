import hashlib
from datetime import date, timedelta
from urllib.parse import urljoin

import requests

import db
from scrapers.common import USER_AGENT

RESMI_GAZETE_FILTER_URL = "https://www.resmigazete.gov.tr/Home/Filter"
RESMI_GAZETE_BASE_URL = "https://www.resmigazete.gov.tr/"
YURUTME_VE_IDARE = "2"


def _filtre_govdesi(mevzuat_turu: str = YURUTME_VE_IDARE) -> dict:
    bugun = date.today()
    bir_hafta_once = bugun - timedelta(days=7)
    return {
        "draw": 1,
        "columns": [],
        "order": [],
        "start": 0,
        "length": 50,
        "search": {"value": "", "regex": False},
        "parameters": {
            "genelBaslangicTarihi": bir_hafta_once.isoformat(),
            "genelBitisTarihi": bugun.isoformat(),
            "searchtype": 1,
            "mevzuatTuru": mevzuat_turu,
        },
    }


def parse_kararlar(veri: dict, base_url: str = RESMI_GAZETE_BASE_URL) -> list[dict]:
    kararlar = []
    for item in veri.get("data", []):
        tarih_iso = item.get("resmiGazeteTarihi")
        if not tarih_iso:
            continue
        baslik = item["konu"]
        konu_hash = hashlib.sha1(baslik.encode("utf-8")).hexdigest()[:10]
        kaynak_url = f"{urljoin(base_url, item['url'])}#{konu_hash}"
        kararlar.append({
            "baslik": baslik,
            "tarih": tarih_iso[:10],
            "kaynak_url": kaynak_url,
            "ozet_ham": baslik,
        })
    kararlar.sort(key=lambda k: k["tarih"], reverse=True)
    return kararlar


def fetch_veri(url: str = RESMI_GAZETE_FILTER_URL, timeout: int = 15) -> dict:
    response = requests.post(
        url,
        json=_filtre_govdesi(),
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def scrape_and_store(conn, url: str = RESMI_GAZETE_FILTER_URL, limit: int = 10) -> int:
    veri = fetch_veri(url)
    kararlar = parse_kararlar(veri)[:limit]
    yeni_sayisi = 0
    for karar in kararlar:
        if db.insert_karar_if_new(conn, kaynak="resmi_gazete", **karar):
            yeni_sayisi += 1
    return yeni_sayisi


if __name__ == "__main__":
    connection = db.get_connection()
    db.init_db(connection)
    yeni_sayisi = scrape_and_store(connection)
    print(f"{yeni_sayisi} yeni Resmi Gazete kararı bulundu.")
    rows = connection.execute(
        "SELECT tarih, baslik FROM kararlar WHERE kaynak = 'resmi_gazete' "
        "ORDER BY tarih DESC LIMIT 10"
    ).fetchall()
    for row in rows:
        print(f"- [{row['tarih']}] {row['baslik'][:100]}...")
    connection.close()
