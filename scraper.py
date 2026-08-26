import re

import requests
from bs4 import BeautifulSoup

import db

KVKK_LIST_URL = "https://www.kvkk.gov.tr/Icerik/5419/kurul-kararlari"
USER_AGENT = "kvkk-takip-bot/0.1"

_DATE_KARAR_NO_RE = re.compile(
    r"(?P<gun>\d{1,2})[./](?P<ay>\d{1,2})[./](?P<yil>\d{4})\s*Tarihli ve\s*(?P<karar_no>\d{4}/\d+)\s*Say"
)


def _parse_tarih(baslik: str) -> str | None:
    m = _DATE_KARAR_NO_RE.search(baslik)
    if not m:
        return None
    gun, ay, yil = m.group("gun"), m.group("ay"), m.group("yil")
    return f"{yil}-{int(ay):02d}-{int(gun):02d}"


def parse_karar_listesi(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    kararlar = []
    for item in soup.select("div.members__item"):
        h2 = item.select_one(".members__item-meta h2")
        link = item.select_one(".members__item-meta a.read-more")
        if h2 is None or link is None or not link.get("href"):
            continue
        baslik = h2.get_text(strip=True)
        kararlar.append({
            "baslik": baslik,
            "tarih": _parse_tarih(baslik),
            "kaynak_url": link["href"].strip(),
            "ozet_ham": baslik,
        })
    return kararlar
