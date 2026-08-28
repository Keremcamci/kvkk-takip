# BDDK ve SPK Kaynaklarının Eklenmesi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **PHASE GATES ARE MANDATORY.** Bu plan 3 faza bölünmüş (BDDK scraper, SPK
> scraper, entegrasyon). Her fazın sonunda bir `🛑 FAZ KONTROL NOKTASI`
> bloğu var. Bu planı uygulayan (subagent orkestratörü ya da inline
> uygulayıcı) orada DURMALI, belirtilen demoyu kullanıcıya göstermeli ve
> bir sonraki faza geçmeden önce açık onay almalıdır.

**Goal:** Mevcut KVKK-only MVP'ye BDDK ve SPK kaynaklarını aynı pipeline'a
(scrape → sınıflandır → SQLite → API → frontend) ekle.

**Architecture:** Scraper'lar `scrapers/` paketine taşınır/eklenir
(`kvkk.py` mevcuttan taşınır, `bddk.py` ve `spk.py` yeni). Her modül aynı
arayüzü sağlar: `scrape_and_store(conn, url=..., limit=10) -> int`.
`classifier.py` hangi kurumdan geldiğini bilecek şekilde genelleştirilir
(sınıflandırma kuralı değişmez, sadece prompt'a doğru kurum adı eklenir).
`db.py`/`backend.py`/`index.html` `kaynak` alanını uçtan uca taşır ve
gösterir.

**Tech Stack:** Mevcutla aynı — Python 3.11+, Flask, requests,
BeautifulSoup4, anthropic, pytest. Yeni bağımlılık YOK (SPK için stdlib
`json`/`requests.json()` yeterli).

**Spec:** `docs/superpowers/specs/2026-08-28-bddk-spk-kaynak-ekleme-design.md`

## Global Constraints

- BDDK kaynak URL: `https://www.bddk.org.tr/Mevzuat/Liste/55` — tek sayfada
  505 kayıt dönüyor (pagination yok), **en güncel 10 kaydı** al (liste
  zaten yeni→eski sıralı). Tarih+karar no başlığın BAŞINDA parantez içinde:
  `(DD.MM.YYYY - No) Başlık`.
- SPK kaynak URL: `https://mevzuat.spk.gov.tr/api/Search/All` — düz JSON
  API, HTML parse YOK. `tur` alanına göre filtrele:
  `tur in ("Kurul Kararı", "İlke Kararı")`. `kurulKararTarihi` zaten ISO
  datetime string. Filtrelenmiş liste tarihe göre yeni→eski sıralanıp
  **en güncel 10 kaydı** alınır.
- Üç scraper modülü de aynı arayüzü sağlar:
  `scrape_and_store(conn, url=<VARSAYILAN>, limit=10) -> int`.
- `classifier.py`'nin `SEKTOR_ETIKETLEME_KURALI`'ı DEĞİŞMİYOR — sadece
  hangi kurumdan geldiği prompt'a eklenir, sabit bir "BDDK=finans" kısayolu
  YOK.
- Kaynak bazlı bir UI filtresi (dropdown/sekme) EKLENMİYOR — sadece her
  kartta bir rozet (`KVKK`/`BDDK`/`SPK`) gösterilir.
- Bir kaynağın scrape'i başarısız olursa (`backend.py`'nin `run_scrape()`'i)
  diğer kaynakları ENGELLEMEZ — her kaynak kendi `try/except` bloğunda.
- Kod tabanını minimal tut, over-engineering yapma (spec'in kendi kuralı).
- Her fazın sonunda kullanıcıya çalışan bir demo gösterilir, onay
  alınmadan sıradaki faza geçilmez.

---

## FAZ 1: scrapers/ Paketine Geçiş + BDDK

### Task 1: `scraper.py` → `scrapers/kvkk.py` Taşıma (Refactor)

**Files:**
- Move: `scraper.py` → `scrapers/kvkk.py`
- Create: `scrapers/__init__.py`
- Create: `scrapers/common.py`
- Move: `tests/test_scraper.py` → `tests/test_scrapers_kvkk.py`
- Modify: `backend.py`
- Modify: `tests/test_integration.py`

**Interfaces:**
- Consumes: yok (saf refactor, davranış değişmiyor)
- Produces: `scrapers.common.USER_AGENT: str`, `scrapers.kvkk.*` (tüm
  isimler aynı kalıyor, sadece modül yolu değişiyor:
  `scrapers.kvkk.KVKK_LIST_URL`, `scrapers.kvkk.parse_karar_listesi`,
  `scrapers.kvkk.fetch_page`, `scrapers.kvkk.scrape_and_store`)

- [ ] **Step 1: Paketi ve ortak sabiti oluştur**

```bash
mkdir -p scrapers
touch scrapers/__init__.py
```

`scrapers/common.py`:

```python
USER_AGENT = "kvkk-takip-bot/0.1"
```

- [ ] **Step 2: `scraper.py`'yi taşı ve `USER_AGENT` importunu güncelle**

```bash
git mv scraper.py scrapers/kvkk.py
```

`scrapers/kvkk.py`'de tek değişiklik: yerel `USER_AGENT = "kvkk-takip-bot/0.1"`
satırını sil, dosyanın en üstündeki importlara şunu ekle:

```python
from scrapers.common import USER_AGENT
```

Dosyanın geri kalanı (`KVKK_LIST_URL`, `_parse_tarih`, `parse_karar_listesi`,
`fetch_page`, `scrape_and_store`, `__main__` bloğu) **birebir aynı kalır.**

- [ ] **Step 3: Test dosyasını taşı ve modül referanslarını güncelle**

```bash
git mv tests/test_scraper.py tests/test_scrapers_kvkk.py
```

`tests/test_scrapers_kvkk.py`'nin tam içeriği (import ve her `scraper.`
referansı `kvkk.` olacak şekilde, patch hedefleri `scrapers.kvkk.` olacak
şekilde):

```python
from pathlib import Path
from unittest.mock import Mock, patch

import db
from scrapers import kvkk

FIXTURE = Path(__file__).parent / "fixtures" / "kvkk_kararlari_sample.html"


def test_parse_karar_listesi_extracts_three_items():
    html = FIXTURE.read_text(encoding="utf-8")
    kararlar = kvkk.parse_karar_listesi(html)
    assert len(kararlar) == 3


def test_parse_karar_listesi_parses_dotted_date_and_external_url():
    html = FIXTURE.read_text(encoding="utf-8")
    kararlar = kvkk.parse_karar_listesi(html)
    ilk = kararlar[0]
    assert ilk["tarih"] == "2026-07-22"
    assert ilk["kaynak_url"] == "https://www.resmigazete.gov.tr/eskiler/2026/08/20260813-3.pdf"
    assert "2026/1491 Sayılı Kararı" in ilk["baslik"]
    assert ilk["ozet_ham"] == ilk["baslik"]


def test_parse_karar_listesi_parses_slash_date_and_internal_url():
    html = FIXTURE.read_text(encoding="utf-8")
    kararlar = kvkk.parse_karar_listesi(html)
    ucuncu = kararlar[2]
    assert ucuncu["tarih"] == "2023-12-14"
    assert ucuncu["kaynak_url"] == "https://www.kvkk.gov.tr/Icerik/7791/2023-2135"


def test_fetch_page_returns_response_text():
    fake_response = Mock()
    fake_response.text = "<html>ok</html>"
    fake_response.raise_for_status = Mock()
    with patch("scrapers.kvkk.requests.get", return_value=fake_response) as mock_get:
        html = kvkk.fetch_page("https://example.com/kararlar")
    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    assert "User-Agent" in kwargs["headers"]
    assert html == "<html>ok</html>"


def test_scrape_and_store_inserts_new_kararlar(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.kvkk.fetch_page", return_value=html):
        yeni_sayisi = kvkk.scrape_and_store(conn)
    assert yeni_sayisi == 3
    assert len(db.get_pending_kararlar(conn)) == 3


def test_scrape_and_store_is_idempotent(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.kvkk.fetch_page", return_value=html):
        kvkk.scrape_and_store(conn)
        ikinci_calistirma = kvkk.scrape_and_store(conn)
    assert ikinci_calistirma == 0
```

- [ ] **Step 4: `backend.py`'nin importunu güncelle**

`backend.py`'de:
- `import scraper` satırını `from scrapers import kvkk` yap.
- `run_scrape()` içindeki `yeni = scraper.scrape_and_store(conn)` satırını
  `yeni = kvkk.scrape_and_store(conn)` yap (bu satır Task 7'de tekrar
  değişecek, şimdilik sadece isim güncelleniyor).

- [ ] **Step 5: `tests/test_integration.py`'nin referanslarını güncelle**

Dosyada:
- `import scraper` → `from scrapers import kvkk`
- İki adet `patch("scraper.fetch_page", return_value=html)` →
  `patch("scrapers.kvkk.fetch_page", return_value=html)`
- İki adet `scraper.scrape_and_store(conn)` → `kvkk.scrape_and_store(conn)`

(Bu dosyadaki `_pipeline_calistir` fonksiyonu ve
`test_reset_failed_unsticks_kararlar_and_pipeline_recovers` testi bu
referansları kullanıyor — başka hiçbir şey değişmiyor.)

- [ ] **Step 6: Tüm test paketini çalıştır, hiçbir şeyin bozulmadığını doğrula**

Run: `pytest -v`
Expected: 52/52 PASS (sadece dosya/modül isimleri değişti, davranış aynı)

- [ ] **Step 7: Commit et**

```bash
git add scraper.py scrapers/ tests/test_scraper.py tests/test_scrapers_kvkk.py backend.py tests/test_integration.py
git commit -m "refactor: move scraper.py to scrapers/kvkk.py, prep for multi-source"
```

(`git add scraper.py` git mv'nin sildiğini kaydeder; `git status` ile
`renamed:` olarak göründüğünü doğrulayabilirsin.)

---

### Task 2: `scrapers/bddk.py` — BDDK Scraper

**Files:**
- Create: `scrapers/bddk.py`
- Create: `tests/test_scrapers_bddk.py`
- Fixture (zaten mevcut, plan yazımı sırasında gerçek siteden alındı):
  `tests/fixtures/bddk_kararlar_sample.html`

**Interfaces:**
- Consumes: `db.insert_karar_if_new` (mevcut), `scrapers.common.USER_AGENT`
- Produces:
  - `scrapers.bddk.BDDK_LIST_URL: str`
  - `scrapers.bddk.parse_kararlar(html: str, base_url: str = BDDK_LIST_URL) -> list[dict]`
  - `scrapers.bddk.fetch_page(url: str = BDDK_LIST_URL, timeout: int = 15) -> str`
  - `scrapers.bddk.scrape_and_store(conn, url: str = BDDK_LIST_URL, limit: int = 10) -> int`

- [ ] **Step 1: Başarısız testleri yaz (`tests/test_scrapers_bddk.py`)**

```python
from pathlib import Path
from unittest.mock import Mock, patch

import db
from scrapers import bddk

FIXTURE = Path(__file__).parent / "fixtures" / "bddk_kararlar_sample.html"
BASE_URL = "https://www.bddk.org.tr/Mevzuat/Liste/55"


def test_parse_kararlar_extracts_three_items():
    html = FIXTURE.read_text(encoding="utf-8")
    kararlar = bddk.parse_kararlar(html, base_url=BASE_URL)
    assert len(kararlar) == 3


def test_parse_kararlar_parses_date_from_prefix_and_absolute_url():
    html = FIXTURE.read_text(encoding="utf-8")
    kararlar = bddk.parse_kararlar(html, base_url=BASE_URL)
    ilk = kararlar[0]
    assert ilk["tarih"] == "2026-08-06"
    assert ilk["kaynak_url"] == "https://www.bddk.org.tr/Mevzuat/DokumanGetir/1345"
    assert "BLG Varlık Yönetim A.Ş." in ilk["baslik"]
    assert ilk["ozet_ham"] == ilk["baslik"]


def test_parse_kararlar_parses_second_item():
    html = FIXTURE.read_text(encoding="utf-8")
    kararlar = bddk.parse_kararlar(html, base_url=BASE_URL)
    ikinci = kararlar[1]
    assert ikinci["tarih"] == "2026-06-11"
    assert "Dost Katılım Bankası" in ikinci["baslik"]
    assert ikinci["kaynak_url"] == "https://www.bddk.org.tr/Mevzuat/DokumanGetir/1338"


def test_fetch_page_returns_response_text():
    fake_response = Mock()
    fake_response.text = "<html>ok</html>"
    fake_response.raise_for_status = Mock()
    with patch("scrapers.bddk.requests.get", return_value=fake_response) as mock_get:
        html = bddk.fetch_page("https://example.com/kararlar")
    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    assert "User-Agent" in kwargs["headers"]
    assert html == "<html>ok</html>"


def test_scrape_and_store_inserts_new_kararlar(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.bddk.fetch_page", return_value=html):
        yeni_sayisi = bddk.scrape_and_store(conn)
    assert yeni_sayisi == 3
    assert len(db.get_pending_kararlar(conn)) == 3


def test_scrape_and_store_is_idempotent(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.bddk.fetch_page", return_value=html):
        bddk.scrape_and_store(conn)
        ikinci_calistirma = bddk.scrape_and_store(conn)
    assert ikinci_calistirma == 0


def test_scrape_and_store_respects_limit(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.bddk.fetch_page", return_value=html):
        yeni_sayisi = bddk.scrape_and_store(conn, limit=2)
    assert yeni_sayisi == 2
```

- [ ] **Step 2: Testleri çalıştır, `scrapers.bddk` modülü olmadığı için
      başarısız olduğunu doğrula**

Run: `pytest tests/test_scrapers_bddk.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapers.bddk'`

- [ ] **Step 3: `scrapers/bddk.py`'yi yaz**

```python
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import db
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
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    return response.text


def scrape_and_store(conn, url: str = BDDK_LIST_URL, limit: int = 10) -> int:
    html = fetch_page(url)
    kararlar = parse_kararlar(html, base_url=url)[:limit]
    yeni_sayisi = 0
    for karar in kararlar:
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
```

- [ ] **Step 4: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_scrapers_bddk.py -v`
Expected: 7 test PASS

- [ ] **Step 5: Tüm paketi çalıştır (regresyon yok)**

Run: `pytest -v`
Expected: 59/59 PASS (52 + 7 yeni)

- [ ] **Step 6: Commit et**

```bash
git add scrapers/bddk.py tests/test_scrapers_bddk.py tests/fixtures/bddk_kararlar_sample.html
git commit -m "feat(scrapers): add BDDK Kurul Kararları scraper"
```

(`tests/fixtures/bddk_kararlar_sample.html` zaten repoda mevcutsa —
plan/spec commit'inde eklenmiş olabilir — sadece `git status` ile kontrol
et, gerekirse `git add` sessizce no-op olur.)

---

### Task 3: Faz 1 Canlı Demo

**Files:** Yok

**Interfaces:** Yok

- [ ] **Step 1: Gerçek BDDK sitesine karşı çalıştır**

Run: `python -m scrapers.bddk` (repo kökünden, venv aktifken)
Expected: `N yeni BDDK kararı bulundu.` çıktısı + en güncel 10 kararın
tarih+başlık listesi.

- [ ] **Step 2: SQLite'ta doğrula**

Run: `sqlite3 kvkk.db "SELECT kaynak, count(*) FROM kararlar GROUP BY kaynak"`
Expected: `kvkk` ve `bddk` için ayrı satırlar, ikisi de `islendi_mi` her ne
ise (henüz sınıflandırılmamışsa 0).

- [ ] **Step 3: Kullanıcıya göster, onay al**

🛑 **FAZ 1 KONTROL NOKTASI** — Konsol çıktısını ve DB durumunu kullanıcıya
göster. Kullanıcı onaylamadan **Faz 2'ye (Task 4) geçme.**

---

## FAZ 2: SPK Scraper

### Task 4: `scrapers/spk.py` — SPK Scraper

**Files:**
- Create: `scrapers/spk.py`
- Create: `tests/test_scrapers_spk.py`
- Fixture (zaten mevcut, plan yazımı sırasında gerçek API'den alındı):
  `tests/fixtures/spk_kararlar_sample.json`

**Interfaces:**
- Consumes: `db.insert_karar_if_new` (mevcut), `scrapers.common.USER_AGENT`
- Produces:
  - `scrapers.spk.SPK_API_URL: str`
  - `scrapers.spk.SPK_BASE_URL: str`
  - `scrapers.spk.GECERLI_TURLER: set[str]`
  - `scrapers.spk.parse_kararlar(veri: list[dict], base_url: str = SPK_BASE_URL) -> list[dict]`
  - `scrapers.spk.fetch_veri(url: str = SPK_API_URL, timeout: int = 15) -> list[dict]`
  - `scrapers.spk.scrape_and_store(conn, url: str = SPK_API_URL, limit: int = 10) -> int`

- [ ] **Step 1: Başarısız testleri yaz (`tests/test_scrapers_spk.py`)**

```python
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
```

- [ ] **Step 2: Testleri çalıştır, `scrapers.spk` modülü olmadığı için
      başarısız olduğunu doğrula**

Run: `pytest tests/test_scrapers_spk.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapers.spk'`

- [ ] **Step 3: `scrapers/spk.py`'yi yaz**

```python
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
```

- [ ] **Step 4: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_scrapers_spk.py -v`
Expected: 6 test PASS

- [ ] **Step 5: Tüm paketi çalıştır (regresyon yok)**

Run: `pytest -v`
Expected: 65/65 PASS (59 + 6 yeni)

- [ ] **Step 6: Commit et**

```bash
git add scrapers/spk.py tests/test_scrapers_spk.py tests/fixtures/spk_kararlar_sample.json
git commit -m "feat(scrapers): add SPK Kurul/İlke Kararları scraper (JSON API)"
```

---

### Task 5: Faz 2 Canlı Demo

**Files:** Yok

**Interfaces:** Yok

- [ ] **Step 1: Gerçek SPK API'sine karşı çalıştır**

Run: `python -m scrapers.spk` (repo kökünden, venv aktifken)
Expected: `N yeni SPK kararı bulundu.` çıktısı + en güncel 10 kararın
tarih+başlık listesi (Tebliğ/Yönetmelik gibi türler görünmemeli).

- [ ] **Step 2: SQLite'ta doğrula**

Run: `sqlite3 kvkk.db "SELECT kaynak, count(*) FROM kararlar GROUP BY kaynak"`
Expected: `kvkk`, `bddk`, `spk` için üç ayrı satır.

- [ ] **Step 3: Kullanıcıya göster, onay al**

🛑 **FAZ 2 KONTROL NOKTASI** — Konsol çıktısını ve DB durumunu kullanıcıya
göster. Kullanıcı onaylamadan **Faz 3'e (Task 6) geçme.**

---

## FAZ 3: Entegrasyon

### Task 6: Sınıflandırmayı Kaynak-Farkındalıklı Yap

**Files:**
- Modify: `classifier.py`
- Modify: `db.py`
- Modify: `tests/test_classifier.py`
- Modify: `tests/test_db.py`

**Interfaces:**
- Consumes: `scrapers.kvkk/bddk/spk`'nin `kaynak` değerleri (`"kvkk"`,
  `"bddk"`, `"spk"` — sabit string'ler, Task 1/2/4'te zaten
  `db.insert_karar_if_new(conn, kaynak=...)` çağrılarında kullanılıyor)
- Produces:
  - `classifier.KURUM_ADLARI: dict[str, str]`
  - `classifier.build_prompt(baslik, tarih, ozet_ham, kaynak="kvkk") -> str`
    (yeni `kaynak` parametresi, varsayılan `"kvkk"` — mevcut çağrı
    yerlerini bozmaz)
  - `classifier.classify_karar(client, baslik, tarih, ozet_ham, model, kaynak="kvkk", sleep_fn=time.sleep) -> dict`
    (yeni `kaynak` parametresi, varsayılan `"kvkk"`)
  - `classifier.classify_pending(conn, client=None, model=None, sleep_fn=time.sleep) -> dict`
    (imza DEĞİŞMİYOR — `kaynak`'ı artık `db.get_pending_kararlar`'ın
    döndürdüğü satırdan okuyup `classify_karar`'a iletiyor)
  - `db.get_pending_kararlar(conn) -> list[dict]` (her dict'e `kaynak`
    eklendi, diğer alanlar aynı)

- [ ] **Step 1: `db.py`'ye kaynak SELECT'i için başarısız test ekle
      (`tests/test_db.py`'nin sonuna)**

```python
def test_get_pending_kararlar_includes_kaynak(conn):
    db.insert_karar_if_new(
        conn, kaynak="bddk", baslik="BDDK Kararı", tarih="2026-01-01",
        kaynak_url="https://example.com/b1", ozet_ham="x",
    )
    bekleyenler = db.get_pending_kararlar(conn)
    assert bekleyenler[0]["kaynak"] == "bddk"
```

- [ ] **Step 2: Testi çalıştır, `KeyError: 'kaynak'` ile başarısız
      olduğunu doğrula**

Run: `pytest tests/test_db.py::test_get_pending_kararlar_includes_kaynak -v`
Expected: FAIL — `KeyError: 'kaynak'`

- [ ] **Step 3: `db.py`'de `get_pending_kararlar`'ı güncelle**

`db.py`'de mevcut fonksiyonu şununla değiştir:

```python
def get_pending_kararlar(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT id, kaynak, baslik, tarih, ozet_ham, deneme_sayisi "
        "FROM kararlar WHERE islendi_mi = 0"
    ).fetchall()
    return [dict(row) for row in rows]
```

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_db.py -v`
Expected: Tüm `test_db.py` testleri PASS (yeni test dahil)

- [ ] **Step 5: `classifier.py`'ye kaynak-farkındalıklı prompt için
      başarısız testler ekle (`tests/test_classifier.py`'nin sonuna)**

```python
def test_build_prompt_uses_correct_institution_name_per_kaynak():
    assert "KVKK (Kişisel Verilerin Korunması Kurumu)" in classifier.build_prompt(
        "Başlık", "2026-01-01", "özet"
    )
    assert "BDDK (Bankacılık Düzenleme ve Denetleme Kurumu)" in classifier.build_prompt(
        "Başlık", "2026-01-01", "özet", kaynak="bddk"
    )
    assert "SPK (Sermaye Piyasası Kurulu)" in classifier.build_prompt(
        "Başlık", "2026-01-01", "özet", kaynak="spk"
    )


class RecordingMessages:
    def __init__(self, response):
        self.response = response
        self.captured_prompts = []

    def create(self, **kwargs):
        self.captured_prompts.append(kwargs["messages"][0]["content"])
        return self.response


class RecordingClient:
    def __init__(self, response):
        self.messages = RecordingMessages(response)


def test_classify_pending_passes_kaynak_from_db_row_to_prompt(conn):
    db.insert_karar_if_new(
        conn, kaynak="bddk", baslik="BDDK Kararı", tarih="2026-01-01",
        kaynak_url="https://example.com/bddk1", ozet_ham="BDDK Kararı",
    )
    client = RecordingClient(_success_response())
    classifier.classify_pending(conn, client=client, model="model", sleep_fn=lambda s: None)
    assert len(client.messages.captured_prompts) == 1
    assert "BDDK (Bankacılık Düzenleme ve Denetleme Kurumu)" in client.messages.captured_prompts[0]
```

(`RecordingMessages`/`RecordingClient` bu dosyaya yeni ekleniyor;
`_success_response()` dosyada zaten tanımlı, aynen kullanılıyor.)

- [ ] **Step 6: Testleri çalıştır, başarısız olduklarını doğrula**

Run: `pytest tests/test_classifier.py -k "kaynak or institution" -v`
Expected: FAIL — `build_prompt() got an unexpected keyword argument 'kaynak'`

- [ ] **Step 7: `classifier.py`'yi güncelle**

`KARAR_SINIFLANDIRMA_TOOL`'un tanımından hemen ÖNCE ekle:

```python
KURUM_ADLARI = {
    "kvkk": "KVKK (Kişisel Verilerin Korunması Kurumu)",
    "bddk": "BDDK (Bankacılık Düzenleme ve Denetleme Kurumu)",
    "spk": "SPK (Sermaye Piyasası Kurulu)",
}
```

`KARAR_SINIFLANDIRMA_TOOL["description"]` değerini değiştir:

```python
    "description": "Bir düzenleyici kurum kararını şirket profillerine göre sınıflandırır.",
```

`build_prompt` fonksiyonunu şununla değiştir:

```python
def build_prompt(baslik: str, tarih, ozet_ham: str, kaynak: str = "kvkk") -> str:
    kurum_adi = KURUM_ADLARI.get(kaynak, kaynak)
    return (
        f"Aşağıda bir {kurum_adi} kararının "
        "başlığı verilmiştir. Bu kararı karar_sinifla aracını kullanarak "
        "sınıflandır.\n\n"
        "Sektör etiketleme kuralı (ÖNEMLİ): "
        f"{SEKTOR_ETIKETLEME_KURALI}\n\n"
        f"Tarih: {tarih or 'bilinmiyor'}\n"
        f"Başlık/Özet: {ozet_ham}\n"
    )
```

`classify_karar`'ın imzasını ve `build_prompt` çağrısını güncelle:

```python
def classify_karar(client, baslik, tarih, ozet_ham, model, kaynak: str = "kvkk", sleep_fn=time.sleep) -> dict:
    prompt = build_prompt(baslik, tarih, ozet_ham, kaynak)
    ...  # geri kalan fonksiyon gövdesi AYNI kalır
```

`classify_pending`'in içindeki `classify_karar` çağrısını güncelle
(fonksiyonun geri kalanı aynı kalır):

```python
            classification = classify_karar(
                client, karar["baslik"], karar["tarih"], karar["ozet_ham"], model,
                kaynak=karar["kaynak"], sleep_fn=sleep_fn,
            )
```

- [ ] **Step 8: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_classifier.py -v`
Expected: Tüm testler PASS (eski + 2 yeni)

- [ ] **Step 9: Tüm paketi çalıştır (regresyon yok)**

Run: `pytest -v`
Expected: 68/68 PASS (65 + 1 db testi + 2 classifier testi)

- [ ] **Step 10: Commit et**

```bash
git add classifier.py db.py tests/test_classifier.py tests/test_db.py
git commit -m "feat(classifier): make classification institution-aware (KVKK/BDDK/SPK)"
```

---

### Task 7: DB/Backend/Frontend Entegrasyonu (kaynak rozeti + çoklu-kaynak scrape)

**Files:**
- Modify: `db.py`
- Modify: `backend.py`
- Modify: `index.html`
- Modify: `tests/test_db.py`
- Modify: `tests/test_backend.py`
- Modify: `tests/test_frontend.py`

**Interfaces:**
- Consumes: `scrapers.kvkk.scrape_and_store`, `scrapers.bddk.scrape_and_store`,
  `scrapers.spk.scrape_and_store` (hepsi `(conn) -> int` imzasıyla, Task
  1/2/4'te üretildi), `classifier.classify_pending` (değişmedi)
- Produces:
  - `db.get_kararlar_by_profil(conn, profil) -> list[dict]` (her dict'e
    `"kaynak"` eklendi)
  - `backend.run_scrape() -> None` (artık 3 kaynağı da çalıştırıyor, bir
    kaynağın hatası diğerlerini engellemiyor)
  - `index.html`'in `kararKart(karar)` fonksiyonu artık `karar.kaynak`
    varsa bir rozet render ediyor

- [ ] **Step 1: `db.get_kararlar_by_profil` için başarısız test ekle
      (`tests/test_db.py`'nin sonuna)**

```python
def test_get_kararlar_by_profil_includes_kaynak(conn):
    db.insert_karar_if_new(
        conn, kaynak="spk", baslik="SPK Kararı", tarih="2026-01-01",
        kaynak_url="https://example.com/spk1", ozet_ham="x",
    )
    karar_id = db.get_pending_kararlar(conn)[0]["id"]
    db.update_karar_classification(conn, karar_id, ["genel"], "özet", [], False, "")
    sonuc = db.get_kararlar_by_profil(conn, "genel")
    assert sonuc[0]["kaynak"] == "spk"
```

- [ ] **Step 2: Testi çalıştır, `KeyError` ile başarısız olduğunu doğrula**

Run: `pytest tests/test_db.py::test_get_kararlar_by_profil_includes_kaynak -v`
Expected: FAIL — `KeyError: 'kaynak'`

- [ ] **Step 3: `db.py`'de `get_kararlar_by_profil`'i güncelle**

Mevcut fonksiyonu şununla değiştir (SELECT'e `kaynak` eklendi, dönen
dict'e `"kaynak": row["kaynak"]` eklendi, geri kalan mantık AYNI):

```python
def get_kararlar_by_profil(conn, profil) -> list[dict]:
    rows = conn.execute(
        "SELECT id, kaynak, baslik, tarih, llm_ozet, sektorler, yapilmasi_gerekenler, "
        "aciliyet_var, aciliyet_aciklama, kaynak_url FROM kararlar "
        "WHERE islendi_mi = 1 ORDER BY tarih DESC"
    ).fetchall()
    sonuc = []
    for row in rows:
        sektorler = json.loads(row["sektorler"]) if row["sektorler"] else []
        if profil in sektorler or "genel" in sektorler:
            sonuc.append({
                "id": row["id"],
                "kaynak": row["kaynak"],
                "baslik": row["baslik"],
                "tarih": row["tarih"],
                "ozet": row["llm_ozet"],
                "sektorler": sektorler,
                "yapilmasi_gerekenler": json.loads(row["yapilmasi_gerekenler"]) if row["yapilmasi_gerekenler"] else [],
                "aciliyet_var": bool(row["aciliyet_var"]),
                "aciliyet_aciklama": row["aciliyet_aciklama"],
                "kaynak_url": row["kaynak_url"],
            })
    return sonuc
```

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_db.py -v`
Expected: Tüm testler PASS

- [ ] **Step 5: `backend.py`'nin çoklu-kaynak `run_scrape()`'i için
      başarısız test ekle (`tests/test_backend.py`'nin sonuna)**

```python
def test_run_scrape_continues_when_one_source_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_run_scrape.db")

    calls = []

    monkeypatch.setattr(backend.kvkk, "scrape_and_store", lambda conn: calls.append("kvkk") or 1)
    monkeypatch.setattr(
        backend.bddk, "scrape_and_store",
        lambda conn: (_ for _ in ()).throw(RuntimeError("BDDK sitesi erişilemedi")),
    )
    monkeypatch.setattr(backend.spk, "scrape_and_store", lambda conn: calls.append("spk") or 2)
    monkeypatch.setattr(
        backend.classifier, "classify_pending",
        lambda conn: {"basarili": 0, "basarisiz": 0, "kalici_hata": 0},
    )

    backend.run_scrape()

    assert calls == ["kvkk", "spk"]
    cikti = capsys.readouterr().out
    assert "kvkk: 1 yeni karar" in cikti
    assert "spk: 2 yeni karar" in cikti
    # bddk başarısız olduğu için "bddk: ... yeni karar" satırı YOK — bu
    # kaynağın hatası, print edilen özet çıktısına hiç girmemeli.
    assert "bddk:" not in cikti


def test_run_scrape_logs_warning_for_failed_source(monkeypatch, tmp_path, caplog):
    import logging

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_run_scrape2.db")
    monkeypatch.setattr(backend.kvkk, "scrape_and_store", lambda conn: 0)
    monkeypatch.setattr(
        backend.bddk, "scrape_and_store",
        lambda conn: (_ for _ in ()).throw(RuntimeError("BDDK sitesi erişilemedi")),
    )
    monkeypatch.setattr(backend.spk, "scrape_and_store", lambda conn: 0)
    monkeypatch.setattr(backend.classifier, "classify_pending", lambda conn: {"basarili": 0, "basarisiz": 0, "kalici_hata": 0})

    with caplog.at_level(logging.WARNING):
        backend.run_scrape()

    assert "bddk" in caplog.text
    assert "BDDK sitesi erişilemedi" in caplog.text
```

- [ ] **Step 6: Testleri çalıştır, başarısız olduklarını doğrula**

Run: `pytest tests/test_backend.py -k run_scrape -v`
Expected: FAIL — `AttributeError: module 'backend' has no attribute 'kvkk'`
(henüz `from scrapers import kvkk, bddk, spk` yok)

- [ ] **Step 7: `backend.py`'yi güncelle**

`import` bloğunu güncelle (en üstte):

```python
import argparse
import logging
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

import classifier
import db
from scrapers import bddk, kvkk, spk
```

`run_scrape` fonksiyonunu şununla değiştir:

```python
def run_scrape() -> None:
    conn = db.get_connection()
    try:
        db.init_db(conn)
        for isim, modul in [("kvkk", kvkk), ("bddk", bddk), ("spk", spk)]:
            try:
                yeni = modul.scrape_and_store(conn)
                print(f"{isim}: {yeni} yeni karar bulundu.")
            except Exception as exc:
                logging.warning("%s scrape başarısız: %s", isim, exc)
        sonuc = classifier.classify_pending(conn)
        print(f"Sınıflandırma sonucu: {sonuc}")
    finally:
        conn.close()
```

- [ ] **Step 8: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_backend.py -v`
Expected: Tüm testler PASS (eski + 2 yeni)

- [ ] **Step 9: `index.html`'e kaynak rozeti için başarısız test ekle
      (`tests/test_frontend.py`'nin sonuna)**

```python
@node_gerekli
def test_kararKart_renders_kaynak_rozeti():
    karar = {
        "baslik": "Karar",
        "tarih": "2026-01-01",
        "ozet": "özet",
        "yapilmasi_gerekenler": [],
        "aciliyet_var": False,
        "aciliyet_aciklama": "",
        "kaynak_url": "https://example.com/1",
        "kaynak": "bddk",
    }
    (html,) = _node_calistir(
        ["esc", "escAttr", "guvenliUrl", "kararKart"], f"[kararKart({json.dumps(karar)})]"
    )
    span = BeautifulSoup(html, "html.parser").select_one("span.kaynak-rozet")
    assert span is not None
    assert span.get_text(strip=True) == "BDDK"


@node_gerekli
def test_kararKart_omits_kaynak_rozeti_when_kaynak_missing():
    karar = {
        "baslik": "Karar",
        "tarih": "2026-01-01",
        "ozet": "özet",
        "yapilmasi_gerekenler": [],
        "aciliyet_var": False,
        "aciliyet_aciklama": "",
        "kaynak_url": "https://example.com/1",
    }
    (html,) = _node_calistir(
        ["esc", "escAttr", "guvenliUrl", "kararKart"], f"[kararKart({json.dumps(karar)})]"
    )
    assert BeautifulSoup(html, "html.parser").select_one("span.kaynak-rozet") is None
```

- [ ] **Step 10: Testleri çalıştır, başarısız olduklarını doğrula**

Run: `pytest tests/test_frontend.py -k kaynak_rozeti -v`
Expected: FAIL — ilk test `span is not None` assertion'ında başarısız
(henüz rozet yok), ikinci test zaten geçer (rozet olmadığı için) ama
tutarlılık için birlikte yazıldı.

- [ ] **Step 11: `index.html`'i güncelle**

`<style>` bloğuna ekle (`.tarih` kuralından sonra):

```css
  .kaynak-rozet { display: inline-block; background: #666; color: #fff; font-size: 0.7rem; padding: 0.1rem 0.4rem; border-radius: 3px; margin-right: 0.4rem; vertical-align: middle; }
```

`kararKart` fonksiyonunu şununla değiştir:

```javascript
    function kararKart(karar) {
      const kaynakRozetiHtml = karar.kaynak
        ? `<span class="kaynak-rozet">${esc(karar.kaynak.toUpperCase())}</span>`
        : "";
      const aciliyetHtml = karar.aciliyet_var
        ? `<span class="aciliyet" title="${escAttr(karar.aciliyet_aciklama)}">Aciliyet</span>`
        : "";
      const maddeler = (karar.yapilmasi_gerekenler || [])
        .map((m) => `<li>${esc(m)}</li>`)
        .join("");
      const url = guvenliUrl(karar.kaynak_url);
      const kaynakHtml = url
        ? `<a class="kaynak-link" href="${escAttr(url)}" target="_blank" rel="noopener">Kaynağı gör</a>`
        : "";
      return `
        <div class="karar">
          <h3>${kaynakRozetiHtml}${esc(karar.baslik)}${aciliyetHtml}</h3>
          <div class="tarih">${esc(karar.tarih)}</div>
          <p>${esc(karar.ozet)}</p>
          ${maddeler ? `<ul class="yapilmasi-gerekenler">${maddeler}</ul>` : ""}
          ${kaynakHtml}
        </div>
      `;
    }
```

- [ ] **Step 12: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_frontend.py -v`
Expected: Tüm testler PASS (eski + 2 yeni)

- [ ] **Step 13: Tüm paketi çalıştır (regresyon yok)**

Run: `pytest -v`
Expected: 73/73 PASS (68 + 1 db + 2 backend + 2 frontend)

- [ ] **Step 14: Commit et**

```bash
git add db.py backend.py index.html tests/test_db.py tests/test_backend.py tests/test_frontend.py
git commit -m "feat(web): show kaynak (KVKK/BDDK/SPK) badge, multi-source run_scrape"
```

---

### Task 8: Faz 3 Uçtan Uca Canlı Demo

**Files:** Yok

**Interfaces:** Yok

- [ ] **Step 1: Temiz baştan uçtan uca çalıştır (3 kaynak birden)**

Run: `rm -f kvkk.db && python backend.py --scrape`
Expected: Konsolda üç ayrı satır (`kvkk: N yeni karar bulundu.`,
`bddk: N yeni karar bulundu.`, `spk: N yeni karar bulundu.`), ardından
`Sınıflandırma sonucu: {...}`.

- [ ] **Step 2: SQLite'ta doğrula**

Run: `sqlite3 kvkk.db "SELECT kaynak, count(*) FROM kararlar WHERE islendi_mi = 1 GROUP BY kaynak"`
Expected: `kvkk`, `bddk`, `spk` için üç ayrı satır, hepsi `islendi_mi = 1`.

- [ ] **Step 3: Web sunucusunu başlat, tarayıcıda doğrula**

Run: `python backend.py`
`http://localhost:5001` adresini aç. Farklı profiller seç, her kartın
üstünde doğru kaynak rozetini (KVKK/BDDK/SPK) gördüğünü, profil
filtresinin hâlâ doğru çalıştığını, "Son güncelleme" satırının
güncellendiğini doğrula.

- [ ] **Step 4: Kullanıcıya göster, onay al**

🛑 **FAZ 3 KONTROL NOKTASI (son)** — Tarayıcıda çalışan uygulamayı
(3 kaynaktan gelen kararlar, rozetler, profil filtresi) kullanıcıya
göster. Onay alındıktan sonra bu iterasyon tamamlanmış sayılır.

---

## Self-Review Notları (plan yazarı tarafından, uygulayıcı için referans)

- **Kapsam kontrolü:** Spec'teki her madde bir task'a karşılık geliyor:
  scrapers/ paketi → Task 1, BDDK → Task 2-3, SPK → Task 4-5, kaynak-
  farkındalıklı sınıflandırma → Task 6, db/backend/frontend entegrasyonu →
  Task 7, uçtan uca doğrulama → Task 8.
- **Tip/arayüz tutarlılığı:** Üç scraper modülü de birebir aynı
  `scrape_and_store(conn, url=..., limit=10) -> int` imzasını paylaşıyor —
  `backend.py`'nin `run_scrape()`'i bu simetriye güveniyor. `build_prompt`
  ve `classify_karar`'a eklenen `kaynak` parametresi varsayılan değerle
  (`"kvkk"`) geriye dönük uyumlu — mevcut testlerin hiçbiri bozulmuyor,
  sadece yeni davranış için yeni testler ekleniyor.
  `classify_pending`'in imzası hiç değişmiyor (kaynak'ı DB satırından
  okuyor) — bu yüzden `test_integration.py`'deki mevcut
  `classify_pending(conn, client=..., model=..., sleep_fn=...)` çağrıları
  hiç dokunulmadan çalışmaya devam ediyor.
- **Canlı doğrulama:** Task 2 ve Task 4'teki CSS seçiciler
  (`a.mevzuatBaslik` için BDDK, `tur`/`kurulKararTarihi`/`link` alanları
  için SPK) ve fixture'lar plan yazımı sırasında gerçek
  `https://www.bddk.org.tr/Mevzuat/Liste/55` ve
  `https://mevzuat.spk.gov.tr/api/Search/All` kaynaklarına bakılarak
  doğrulandı — placeholder/varsayım değil.
