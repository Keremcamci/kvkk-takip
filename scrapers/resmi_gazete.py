import hashlib
import logging
from datetime import date, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import db
from scrapers import tammetin
from scrapers.common import USER_AGENT

RESMI_GAZETE_FILTER_URL = "https://www.resmigazete.gov.tr/Home/Filter"
RESMI_GAZETE_BASE_URL = "https://www.resmigazete.gov.tr/"
YURUTME_VE_IDARE = "2"


def _filtre_govdesi(mevzuat_turu: str = YURUTME_VE_IDARE) -> dict:
    # date.today() sunucu yerel saatine göredir (Türkiye/UTC+3 değil); gece
    # yarısına yakın, Türkiye'nin batısındaki bir sunucuda bu bir gün geride
    # kalabilir — 7 günlük pencere sayesinde bir sonraki koşuda kendiliğinden
    # telafi olur.
    bugun = date.today()
    bir_hafta_once = bugun - timedelta(days=7)
    return {
        "draw": 1,
        "columns": [],
        "order": [],
        "start": 0,
        # "Yürütme ve İdare" günde ~10-40 kayıt alabiliyor; 7 günde 70-280'e
        # çıkabilir. "order": [] ile sunucu sıralaması belirsiz olsa da 300,
        # en yeni günlerin sessizce kırpılmasını önleyen güvenli üst sınır.
        "length": 300,
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
        baslik = item.get("konu")
        goreli_url = item.get("url")
        if not baslik or not goreli_url:
            logging.warning(
                "Resmi Gazete kaydı eksik alan(lar) içeriyor, atlanıyor: "
                "konu=%s url=%s",
                baslik, goreli_url,
            )
            continue
        konu_hash = hashlib.sha1(baslik.encode("utf-8")).hexdigest()[:10]
        kaynak_url = f"{urljoin(base_url, goreli_url)}#{konu_hash}"
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
        verify=tammetin.guven_paketi(),
    )
    response.raise_for_status()
    return response.json()


def _normalize_baslik(metin: str) -> str:
    kelimeler = metin.split()
    while kelimeler and set(kelimeler[0]) <= set("–—-"):
        kelimeler.pop(0)
    return " ".join(kelimeler)


def _fihrist_linkleri(tarih: str, timeout: int = 15) -> dict[str, str]:
    fihrist_url = urljoin(RESMI_GAZETE_BASE_URL, f"/fihrist?tarih={tarih}")
    try:
        response = requests.get(
            fihrist_url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            verify=tammetin.guven_paketi(),
        )
        response.raise_for_status()
    except (requests.RequestException, ConnectionError, OSError) as exc:
        logging.warning("Resmi Gazete fihrist sayfası indirilemedi (%s): %s", fihrist_url, exc)
        return {}

    soup = BeautifulSoup(response.text, "html.parser")
    linkler: dict[str, str] = {}
    for madde in soup.select("div.fihrist-item a"):
        href = madde.get("href")
        if not href:
            continue
        linkler[_normalize_baslik(madde.get_text())] = href
    return linkler


def _madde_url_bul(tarih: str, konu: str, fihrist_cache: dict) -> str | None:
    if tarih not in fihrist_cache:
        fihrist_cache[tarih] = _fihrist_linkleri(tarih)
    return fihrist_cache[tarih].get(_normalize_baslik(konu))


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
