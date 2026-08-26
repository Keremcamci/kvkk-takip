from pathlib import Path

import scraper

FIXTURE = Path(__file__).parent / "fixtures" / "kvkk_kararlari_sample.html"


def test_parse_karar_listesi_extracts_three_items():
    html = FIXTURE.read_text(encoding="utf-8")
    kararlar = scraper.parse_karar_listesi(html)
    assert len(kararlar) == 3


def test_parse_karar_listesi_parses_dotted_date_and_external_url():
    html = FIXTURE.read_text(encoding="utf-8")
    kararlar = scraper.parse_karar_listesi(html)
    ilk = kararlar[0]
    assert ilk["tarih"] == "2026-07-22"
    assert ilk["kaynak_url"] == "https://www.resmigazete.gov.tr/eskiler/2026/08/20260813-3.pdf"
    assert "2026/1491 Sayılı Kararı" in ilk["baslik"]
    assert ilk["ozet_ham"] == ilk["baslik"]


def test_parse_karar_listesi_parses_slash_date_and_internal_url():
    html = FIXTURE.read_text(encoding="utf-8")
    kararlar = scraper.parse_karar_listesi(html)
    ucuncu = kararlar[2]
    assert ucuncu["tarih"] == "2023-12-14"
    assert ucuncu["kaynak_url"] == "https://www.kvkk.gov.tr/Icerik/7791/2023-2135"
