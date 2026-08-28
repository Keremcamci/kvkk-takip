import json
from pathlib import Path
from unittest.mock import Mock, patch

import db
from scrapers import spk

FIXTURE = Path(__file__).parent / "fixtures" / "spk_kararlar_sample.json"


def _fixture_veri() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_kararlar_filters_out_non_karar_types():
    kararlar = spk.parse_kararlar(_fixture_veri())
    # Fixture'da 3 kayıt var: İlke Kararı, Kurul Kararı, Tebliğ.
    # Tebliğ elenmeli, sadece 2 kalmalı.
    assert len(kararlar) == 2
    assert all("Tebliğ" not in k["baslik"] for k in kararlar)


def test_parse_kararlar_sorts_newest_first_and_maps_fields():
    kararlar = spk.parse_kararlar(_fixture_veri())
    ilk = kararlar[0]
    assert ilk["tarih"] == "2026-08-27"
    assert "i-SPK 128.30" in ilk["baslik"]
    assert ilk["ozet_ham"] == ilk["baslik"]
    assert ilk["kaynak_url"] == "https://mevzuat.spk.gov.tr/IlkeKarari/Dosya/377"

    ikinci = kararlar[1]
    assert ikinci["tarih"] == "2026-08-13"


def test_fetch_veri_returns_parsed_json():
    fake_response = Mock()
    fake_response.json.return_value = [{"tur": "Kurul Kararı"}]
    fake_response.raise_for_status = Mock()
    with patch("scrapers.spk.requests.get", return_value=fake_response) as mock_get:
        veri = spk.fetch_veri("https://example.com/api")
    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    assert "User-Agent" in kwargs["headers"]
    assert veri == [{"tur": "Kurul Kararı"}]


def test_scrape_and_store_inserts_new_kararlar(conn):
    with patch("scrapers.spk.fetch_veri", return_value=_fixture_veri()):
        yeni_sayisi = spk.scrape_and_store(conn)
    assert yeni_sayisi == 2  # Tebliğ elenmiş olmalı
    assert len(db.get_pending_kararlar(conn)) == 2


def test_scrape_and_store_is_idempotent(conn):
    with patch("scrapers.spk.fetch_veri", return_value=_fixture_veri()):
        spk.scrape_and_store(conn)
        ikinci_calistirma = spk.scrape_and_store(conn)
    assert ikinci_calistirma == 0


def test_scrape_and_store_respects_limit(conn):
    with patch("scrapers.spk.fetch_veri", return_value=_fixture_veri()):
        yeni_sayisi = spk.scrape_and_store(conn, limit=1)
    assert yeni_sayisi == 1
