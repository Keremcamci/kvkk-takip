# KVKK Mevzuat Takip Aracı Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **PHASE GATES ARE MANDATORY.** This plan is split into 3 phases (Scraper,
> LLM Sınıflandırma, Frontend+Backend). At the end of each phase there is a
> `🛑 FAZ KONTROL NOKTASI` block. Whoever executes this plan (subagent
> orchestrator or inline executor) MUST stop there, show the user the
> specified demo/output, and get explicit approval before starting the next
> phase's tasks. This is a hard requirement from the user, not optional.

**Goal:** Türkiye'deki KOBİ'ler için, KVKK Kurulu Kararları'nı otomatik
tarayıp seçilen şirket profiline göre özetleyen bir web aracı (tek dosya
frontend + basit Python/Flask backend + SQLite).

**Architecture:** `scraper.py` KVKK liste sayfasını çekip parse eder ve
SQLite'a yazar. `classifier.py` bekleyen kararları Anthropic API ile
sınıflandırır (yapılandırılmış tool-use çıktısı). `backend.py` bir Flask
uygulaması olarak hem `index.html`'i serve eder hem `/api/kararlar` JSON
endpoint'ini sağlar; `--scrape` CLI bayrağı scrape+classify pipeline'ını
tetikler.

**Tech Stack:** Python 3.11+, Flask, requests, BeautifulSoup4, anthropic
(Python SDK), python-dotenv, sqlite3 (stdlib), pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-kvkk-takip-design.md`

## Global Constraints

- Tek dosya frontend: `index.html` (Flask tarafından serve edilir, ayrı JS/CSS dosyası yok).
- Depolama: SQLite (`kvkk.db`, tek dosya, stdlib `sqlite3`, ORM yok).
- Model adı asla kod içine sabit yazılmaz — `.env`'den `ANTHROPIC_MODEL` okunur.
- `deneme_sayisi >= 3` olan bir karar `islendi_mi = -1` (kalıcı hata) olur ve bir daha otomatik denenmez.
- LLM API çağrılarında retryable hata (HTTP 429/500/502/503/504) için exponential backoff (1s, 2s, 4s).
- Web'den scrape tetikleyen bir HTTP endpoint YOK — sadece CLI (`python backend.py --scrape`).
- KVKK kaynak URL'i: `https://www.kvkk.gov.tr/Icerik/5419/kurul-kararlari` — MVP sadece sayfa 1'i (en güncel ~10 karar) çeker, pagination kapsam dışı.
- Liste sayfasında ayrı bir özet metni yok — `ozet_ham` = `baslik` (aynı metin), `tarih` başlıktan regex ile parse edilir.
- Sabit uyarı metni (UI + README'de birebir aynı): "Bu araç hukuki tavsiye değildir, bilgi amaçlıdır. Kararlar için resmi kaynağı ve/veya bir avukatı kontrol edin."
- Lisans: MIT (`Copyright (c) 2026 [YOUR NAME/ORGANIZATION]` — kullanıcı kendi adını sonra dolduracak), README'de "AS IS, NO WARRANTY" ibaresi.
- Her fazın sonunda kullanıcıya çalışan bir demo gösterilir, onay alınmadan sıradaki faza geçilmez.

---

## FAZ 1: Scraper

### Task 1: Proje İskeleti (Bootstrap)

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `LICENSE`
- Create: `README.md`

**Interfaces:** Yok — bu görev kod üretmiyor, sonraki tüm görevlerin
bağımlı olduğu proje iskeletini kuruyor.

- [ ] **Step 1: `requirements.txt` yaz**

```
flask>=3.0
requests>=2.31
beautifulsoup4>=4.12
anthropic>=0.40
python-dotenv>=1.0
pytest>=8.0
```

- [ ] **Step 2: `.gitignore` yaz**

```
venv/
__pycache__/
*.pyc
kvkk.db
.env
.pytest_cache/
.DS_Store
```

- [ ] **Step 3: `.env.example` yaz**

```
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-5
```

- [ ] **Step 4: `LICENSE` yaz (MIT)**

```
MIT License

Copyright (c) 2026 [YOUR NAME/ORGANIZATION]

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 5: `README.md` yaz**

```markdown
# KVKK Mevzuat Takip Aracı

Türkiye'deki KOBİ'ler için KVKK Kurulu Kararları'nı otomatik tarayıp, seçilen
şirket profiline (e-ticaret / finans / sağlık / eğitim / genel) göre hangi
kararların ilgili olduğunu özetleyen basit bir araç.

**Bu araç hukuki tavsiye değildir, bilgi amaçlıdır. Kararlar için resmi
kaynağı ve/veya bir avukatı kontrol edin.**

## Kurulum

\`\`\`bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env dosyasını açıp ANTHROPIC_API_KEY değerini doldurun
\`\`\`

## Kullanım

\`\`\`bash
# 1. Kararları tara ve sınıflandır (SQLite'a yazar)
python backend.py --scrape

# 2. Web arayüzünü başlat
python backend.py
# http://localhost:5000 adresini aç
\`\`\`

## Test

\`\`\`bash
pytest
\`\`\`

## Kapsam

MVP sadece KVKK Kurulu Kararları'nı (son ~10 karar, liste sayfasının ilk
sayfası) tarar. BDDK, SPK ve Resmi Gazete kaynakları henüz desteklenmiyor.
PDF tam metin işlenmiyor — yalnızca liste sayfasındaki başlık kullanılıyor.

## Lisans

MIT License — bkz. [LICENSE](LICENSE).

**AS IS, NO WARRANTY.** Bu yazılım "olduğu gibi" sunulur, hiçbir garanti
verilmez. Kullanım sorumluluğu kullanıcıya aittir.
```

- [ ] **Step 6: Doğrula ve commit et**

Run: `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
Expected: Tüm paketler hatasız kurulur.

```bash
git add requirements.txt .gitignore .env.example LICENSE README.md
git commit -m "chore: project scaffolding (deps, license, disclaimer)"
```

---

### Task 2: `db.py` — SQLite Kalıcılık Katmanı

**Files:**
- Create: `db.py`
- Create: `tests/conftest.py`
- Create: `tests/test_db.py`

**Interfaces:**
- Produces:
  - `db.DB_PATH: Path` (module-level, monkeypatch edilebilir)
  - `db.get_connection(db_path: Path | str | None = None) -> sqlite3.Connection`
  - `db.init_db(conn: sqlite3.Connection) -> None`
  - `db.insert_karar_if_new(conn, kaynak: str, baslik: str, tarih: str | None, kaynak_url: str, ozet_ham: str) -> bool`
  - `db.get_pending_kararlar(conn) -> list[dict]` (her dict: `id, baslik, tarih, ozet_ham, deneme_sayisi`)
  - `db.update_karar_classification(conn, karar_id: int, sektorler: list[str], ozet: str, yapilmasi_gerekenler: list[str], aciliyet_var: bool, aciliyet_aciklama: str) -> None`
  - `db.mark_karar_failed(conn, karar_id: int) -> bool` (True = bu hata kararı kalıcı hataya düşürdü)
  - `db.get_kararlar_by_profil(conn, profil: str) -> list[dict]` (her dict: `id, baslik, tarih, ozet, sektorler, yapilmasi_gerekenler, aciliyet_var, aciliyet_aciklama, kaynak_url`, tarihe göre DESC sıralı)
  - `db.get_son_guncelleme(conn) -> str | None`
- `tests/conftest.py` bir `conn` pytest fixture'ı üretir (tmp SQLite dosyası, otomatik `init_db` + `close`) — sonraki tüm test dosyaları bunu kullanır.

- [ ] **Step 1: Başarısız testleri yaz (`tests/test_db.py`)**

```python
import db


def test_init_db_creates_table(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='kararlar'"
    ).fetchone()
    assert row is not None


def test_insert_karar_if_new_returns_true_for_new_row(conn):
    eklendi = db.insert_karar_if_new(
        conn, kaynak="kvkk", baslik="Test Karar", tarih="2026-01-01",
        kaynak_url="https://example.com/1", ozet_ham="Test Karar",
    )
    assert eklendi is True


def test_insert_karar_if_new_returns_false_for_duplicate(conn):
    db.insert_karar_if_new(
        conn, kaynak="kvkk", baslik="Test Karar", tarih="2026-01-01",
        kaynak_url="https://example.com/1", ozet_ham="Test Karar",
    )
    eklendi = db.insert_karar_if_new(
        conn, kaynak="kvkk", baslik="Değişik başlık", tarih="2026-01-02",
        kaynak_url="https://example.com/1", ozet_ham="Değişik başlık",
    )
    assert eklendi is False


def test_get_pending_kararlar_returns_unprocessed_rows(conn):
    db.insert_karar_if_new(
        conn, kaynak="kvkk", baslik="Bekleyen Karar", tarih="2026-01-01",
        kaynak_url="https://example.com/2", ozet_ham="Bekleyen Karar",
    )
    bekleyenler = db.get_pending_kararlar(conn)
    assert len(bekleyenler) == 1
    assert bekleyenler[0]["baslik"] == "Bekleyen Karar"
    assert bekleyenler[0]["deneme_sayisi"] == 0


def test_update_karar_classification_marks_processed(conn):
    db.insert_karar_if_new(
        conn, kaynak="kvkk", baslik="Karar", tarih="2026-01-01",
        kaynak_url="https://example.com/3", ozet_ham="Karar",
    )
    karar_id = db.get_pending_kararlar(conn)[0]["id"]
    db.update_karar_classification(
        conn, karar_id,
        sektorler=["e-ticaret", "genel"],
        ozet="Kısa özet.",
        yapilmasi_gerekenler=["Madde 1"],
        aciliyet_var=True,
        aciliyet_aciklama="Ceza riski var",
    )
    assert db.get_pending_kararlar(conn) == []
    sonuclar = db.get_kararlar_by_profil(conn, "e-ticaret")
    assert len(sonuclar) == 1
    assert sonuclar[0]["sektorler"] == ["e-ticaret", "genel"]
    assert sonuclar[0]["aciliyet_var"] is True


def test_mark_karar_failed_increments_and_caps_at_permanent_failure(conn):
    db.insert_karar_if_new(
        conn, kaynak="kvkk", baslik="Karar", tarih="2026-01-01",
        kaynak_url="https://example.com/4", ozet_ham="Karar",
    )
    karar_id = db.get_pending_kararlar(conn)[0]["id"]

    assert db.mark_karar_failed(conn, karar_id) is False
    assert db.mark_karar_failed(conn, karar_id) is False
    assert len(db.get_pending_kararlar(conn)) == 1

    assert db.mark_karar_failed(conn, karar_id) is True
    assert db.get_pending_kararlar(conn) == []
    row = conn.execute(
        "SELECT islendi_mi, deneme_sayisi FROM kararlar WHERE id = ?", (karar_id,)
    ).fetchone()
    assert row["islendi_mi"] == -1
    assert row["deneme_sayisi"] == 3


def test_get_kararlar_by_profil_includes_genel_and_matching_profile(conn):
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Genel Karar", tarih="2026-01-01", kaynak_url="https://example.com/5", ozet_ham="x")
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Finans Karar", tarih="2026-01-02", kaynak_url="https://example.com/6", ozet_ham="x")
    ids = {row["baslik"]: row["id"] for row in conn.execute("SELECT id, baslik FROM kararlar").fetchall()}

    db.update_karar_classification(conn, ids["Genel Karar"], ["genel"], "özet", [], False, "")
    db.update_karar_classification(conn, ids["Finans Karar"], ["finans"], "özet", [], False, "")

    e_ticaret_sonuc = db.get_kararlar_by_profil(conn, "e-ticaret")
    assert [k["baslik"] for k in e_ticaret_sonuc] == ["Genel Karar"]

    finans_sonuc = db.get_kararlar_by_profil(conn, "finans")
    assert sorted(k["baslik"] for k in finans_sonuc) == ["Finans Karar", "Genel Karar"]


def test_get_son_guncelleme_returns_none_when_empty(conn):
    assert db.get_son_guncelleme(conn) is None


def test_get_son_guncelleme_returns_timestamp_after_insert(conn):
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Karar", tarih="2026-01-01", kaynak_url="https://example.com/7", ozet_ham="x")
    assert db.get_son_guncelleme(conn) is not None
```

`tests/conftest.py`:

```python
import pytest

import db


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test_kvkk.db"
    connection = db.get_connection(db_path)
    db.init_db(connection)
    yield connection
    connection.close()
```

- [ ] **Step 2: Testleri çalıştır, `db` modülü henüz yok olduğu için import hatasıyla başarısız olduğunu doğrula**

Run: `pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 3: `db.py`'yi yaz**

```python
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "kvkk.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS kararlar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kaynak TEXT NOT NULL DEFAULT 'kvkk',
    baslik TEXT NOT NULL,
    tarih TEXT,
    kaynak_url TEXT UNIQUE NOT NULL,
    ozet_ham TEXT,
    sektorler TEXT,
    llm_ozet TEXT,
    yapilmasi_gerekenler TEXT,
    aciliyet_var INTEGER,
    aciliyet_aciklama TEXT,
    islendi_mi INTEGER NOT NULL DEFAULT 0,
    deneme_sayisi INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
"""


def get_connection(db_path=None) -> sqlite3.Connection:
    if db_path is None:
        db_path = DB_PATH
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(SCHEMA)
    conn.commit()


def insert_karar_if_new(conn, kaynak, baslik, tarih, kaynak_url, ozet_ham) -> bool:
    cur = conn.execute(
        "INSERT OR IGNORE INTO kararlar (kaynak, baslik, tarih, kaynak_url, ozet_ham) "
        "VALUES (?, ?, ?, ?, ?)",
        (kaynak, baslik, tarih, kaynak_url, ozet_ham),
    )
    conn.commit()
    return cur.rowcount > 0


def get_pending_kararlar(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT id, baslik, tarih, ozet_ham, deneme_sayisi FROM kararlar WHERE islendi_mi = 0"
    ).fetchall()
    return [dict(row) for row in rows]


def update_karar_classification(
    conn, karar_id, sektorler, ozet, yapilmasi_gerekenler, aciliyet_var, aciliyet_aciklama
) -> None:
    conn.execute(
        "UPDATE kararlar SET sektorler = ?, llm_ozet = ?, yapilmasi_gerekenler = ?, "
        "aciliyet_var = ?, aciliyet_aciklama = ?, islendi_mi = 1 WHERE id = ?",
        (
            json.dumps(sektorler, ensure_ascii=False),
            ozet,
            json.dumps(yapilmasi_gerekenler, ensure_ascii=False),
            1 if aciliyet_var else 0,
            aciliyet_aciklama,
            karar_id,
        ),
    )
    conn.commit()


def mark_karar_failed(conn, karar_id) -> bool:
    row = conn.execute(
        "SELECT deneme_sayisi FROM kararlar WHERE id = ?", (karar_id,)
    ).fetchone()
    yeni_deneme = row["deneme_sayisi"] + 1
    kalici_mi = yeni_deneme >= 3
    yeni_durum = -1 if kalici_mi else 0
    conn.execute(
        "UPDATE kararlar SET deneme_sayisi = ?, islendi_mi = ? WHERE id = ?",
        (yeni_deneme, yeni_durum, karar_id),
    )
    conn.commit()
    return kalici_mi


def get_kararlar_by_profil(conn, profil) -> list[dict]:
    rows = conn.execute(
        "SELECT id, baslik, tarih, llm_ozet, sektorler, yapilmasi_gerekenler, "
        "aciliyet_var, aciliyet_aciklama, kaynak_url FROM kararlar "
        "WHERE islendi_mi = 1 ORDER BY tarih DESC"
    ).fetchall()
    sonuc = []
    for row in rows:
        sektorler = json.loads(row["sektorler"]) if row["sektorler"] else []
        if profil == "genel" or profil in sektorler or "genel" in sektorler:
            sonuc.append({
                "id": row["id"],
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


def get_son_guncelleme(conn) -> str | None:
    row = conn.execute("SELECT MAX(created_at) AS son FROM kararlar").fetchone()
    return row["son"] if row and row["son"] else None
```

`get_connection`'ın `db_path=None` yapıp fonksiyon gövdesinde `DB_PATH`'i
okuması bilinçli bir tasarım: Python'da default parametre değerleri
tanım anında bağlanır, bu yüzden `db_path=DB_PATH` yazılsaydı testlerde
`monkeypatch.setattr(db, "DB_PATH", ...)` çağrısı `get_connection()`'ın
göreceği değeri değiştiremezdi (Task 9'daki backend testleri bu
monkeypatch'e dayanıyor).

- [ ] **Step 4: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_db.py -v`
Expected: 9 test PASS

- [ ] **Step 5: Commit et**

```bash
git add db.py tests/conftest.py tests/test_db.py
git commit -m "feat(db): add SQLite persistence layer with retry/backoff tracking"
```

---

### Task 3: `scraper.py` — HTML Parse (Liste Sayfası)

**Files:**
- Create: `scraper.py`
- Create: `tests/fixtures/kvkk_kararlari_sample.html` (zaten mevcut — plan yazımı sırasında canlı siteden alınan gerçek 3 karar örneği)
- Create: `tests/test_scraper.py` (bu görevde sadece parse testleri)

**Interfaces:**
- Consumes: yok (saf fonksiyon, dışa bağımlılığı yok)
- Produces:
  - `scraper.KVKK_LIST_URL: str`
  - `scraper.parse_karar_listesi(html: str) -> list[dict]` (her dict: `baslik, tarih, kaynak_url, ozet_ham`)

- [ ] **Step 1: Başarısız testi yaz (`tests/test_scraper.py`)**

```python
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
```

- [ ] **Step 2: Testi çalıştır, `scraper` modülü olmadığı için başarısız olduğunu doğrula**

Run: `pytest tests/test_scraper.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper'`

- [ ] **Step 3: `scraper.py`'yi yaz (bu adımda sadece parse kısmı)**

```python
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
```

(`requests`, `db` importları bu adımda kullanılmıyor ama Task 4'te aynı
dosyaya ekleneceği için üstte bırakıldı — Task 4'ü bitirmeden dosya
`flake`/`lint` çalıştırılmayacak.)

- [ ] **Step 4: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_scraper.py -v`
Expected: 3 test PASS

- [ ] **Step 5: Commit et**

```bash
git add scraper.py tests/fixtures/kvkk_kararlari_sample.html tests/test_scraper.py
git commit -m "feat(scraper): parse KVKK karar listesi HTML into structured records"
```

---

### Task 4: `scraper.py` — Fetch + SQLite'a Yazma

**Files:**
- Modify: `scraper.py`
- Modify: `tests/test_scraper.py`

**Interfaces:**
- Consumes: `db.insert_karar_if_new` (Task 2), `scraper.parse_karar_listesi` (Task 3)
- Produces:
  - `scraper.fetch_page(url: str = KVKK_LIST_URL, timeout: int = 15) -> str`
  - `scraper.scrape_and_store(conn, url: str = KVKK_LIST_URL) -> int` (dönen değer: yeni eklenen karar sayısı)

- [ ] **Step 1: Başarısız testleri ekle (`tests/test_scraper.py`'nin sonuna)**

```python
from unittest.mock import Mock, patch

import db


def test_fetch_page_returns_response_text():
    fake_response = Mock()
    fake_response.text = "<html>ok</html>"
    fake_response.raise_for_status = Mock()
    with patch("scraper.requests.get", return_value=fake_response) as mock_get:
        html = scraper.fetch_page("https://example.com/kararlar")
    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    assert "User-Agent" in kwargs["headers"]
    assert html == "<html>ok</html>"


def test_scrape_and_store_inserts_new_kararlar(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scraper.fetch_page", return_value=html):
        yeni_sayisi = scraper.scrape_and_store(conn)
    assert yeni_sayisi == 3
    assert len(db.get_pending_kararlar(conn)) == 3


def test_scrape_and_store_is_idempotent(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scraper.fetch_page", return_value=html):
        scraper.scrape_and_store(conn)
        ikinci_calistirma = scraper.scrape_and_store(conn)
    assert ikinci_calistirma == 0
```

- [ ] **Step 2: Testleri çalıştır, `fetch_page`/`scrape_and_store` olmadığı için başarısız olduğunu doğrula**

Run: `pytest tests/test_scraper.py -v`
Expected: FAIL — `AttributeError: module 'scraper' has no attribute 'fetch_page'`

- [ ] **Step 3: `scraper.py`'ye `fetch_page` ve `scrape_and_store`'u ekle**

`scraper.py`'nin sonuna ekle:

```python
def fetch_page(url: str = KVKK_LIST_URL, timeout: int = 15) -> str:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    return response.text


def scrape_and_store(conn, url: str = KVKK_LIST_URL) -> int:
    html = fetch_page(url)
    kararlar = parse_karar_listesi(html)
    yeni_sayisi = 0
    for karar in kararlar:
        if db.insert_karar_if_new(conn, kaynak="kvkk", **karar):
            yeni_sayisi += 1
    return yeni_sayisi


if __name__ == "__main__":
    connection = db.get_connection()
    db.init_db(connection)
    yeni_sayisi = scrape_and_store(connection)
    print(f"{yeni_sayisi} yeni karar bulundu.")
    for karar in db.get_pending_kararlar(connection):
        print(f"- [{karar['tarih']}] {karar['baslik'][:100]}...")
    connection.close()
```

- [ ] **Step 4: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_scraper.py -v`
Expected: 6 test PASS (3 parse + 3 fetch/store)

- [ ] **Step 5: Commit et**

```bash
git add scraper.py tests/test_scraper.py
git commit -m "feat(scraper): fetch live KVKK page and store new kararlar in SQLite"
```

---

### Task 5: Faz 1 Canlı Demo

**Files:** Yok (mevcut `scraper.py`'yi çalıştırıyoruz)

**Interfaces:** Yok

- [ ] **Step 1: Gerçek siteye karşı çalıştır**

Run: `python scraper.py`
Expected: `N yeni karar bulundu.` çıktısı + her biri için `- [tarih] başlık...`
formatında konsola basılmış en güncel ~10 KVKK kararı.

- [ ] **Step 2: `kvkk.db` dosyasının oluştuğunu doğrula**

Run: `sqlite3 kvkk.db "SELECT count(*), islendi_mi FROM kararlar GROUP BY islendi_mi"`
Expected: Tüm satırlar `islendi_mi = 0` (henüz sınıflandırılmadı).

- [ ] **Step 3: Kullanıcıya göster, onay al**

🛑 **FAZ 1 KONTROL NOKTASI** — Konsol çıktısını ve `kvkk.db`'deki satır
sayısını kullanıcıya göster. Kullanıcı onaylamadan **Faz 2'ye (Task 6)
geçme.**

---

## FAZ 2: LLM Sınıflandırma

### Task 6: `classifier.py` — Anthropic Sınıflandırma (Retry + Backoff)

**Files:**
- Create: `classifier.py`
- Create: `tests/test_classifier.py`

**Interfaces:**
- Consumes: `db.get_pending_kararlar`, `db.update_karar_classification`, `db.mark_karar_failed` (Task 2)
- Produces:
  - `classifier.KARAR_SINIFLANDIRMA_TOOL: dict` (Anthropic tool şeması)
  - `classifier.build_prompt(baslik: str, tarih: str | None, ozet_ham: str) -> str`
  - `classifier.classify_karar(client, baslik, tarih, ozet_ham, model, sleep_fn=time.sleep) -> dict` (dönen dict: `sektorler, ozet, yapilmasi_gerekenler, aciliyet_var, aciliyet_aciklama`)
  - `classifier.classify_pending(conn, client=None, model=None) -> dict` (dönen dict: `{"basarili": int, "basarisiz": int, "kalici_hata": int}`)

- [ ] **Step 1: Başarısız testleri yaz (`tests/test_classifier.py`)**

```python
import db
import classifier


class FakeAPIError(Exception):
    def __init__(self, status_code):
        super().__init__(f"fake api error {status_code}")
        self.status_code = status_code


class FakeToolUseBlock:
    def __init__(self, name, input_):
        self.type = "tool_use"
        self.name = name
        self.input = input_


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeMessages:
    def __init__(self, effects):
        self.effects = list(effects)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        effect = self.effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


class FakeClient:
    def __init__(self, effects):
        self.messages = FakeMessages(effects)


SUCCESS_INPUT = {
    "sektorler": ["e-ticaret", "genel"],
    "ozet": "Kısa özet.",
    "yapilmasi_gerekenler": ["Madde 1"],
    "aciliyet_var": False,
    "aciliyet_aciklama": "",
}


def _success_response():
    return FakeResponse([FakeToolUseBlock("karar_sinifla", SUCCESS_INPUT)])


def test_classify_karar_returns_tool_input_on_first_success():
    client = FakeClient([_success_response()])
    sonuc = classifier.classify_karar(client, "Başlık", "2026-01-01", "özet", "model", sleep_fn=lambda s: None)
    assert sonuc == SUCCESS_INPUT


def test_classify_karar_retries_on_retryable_error_then_succeeds():
    uyku_cagrilari = []
    client = FakeClient([FakeAPIError(429), FakeAPIError(503), _success_response()])
    sonuc = classifier.classify_karar(
        client, "Başlık", "2026-01-01", "özet", "model",
        sleep_fn=lambda s: uyku_cagrilari.append(s),
    )
    assert sonuc == SUCCESS_INPUT
    assert uyku_cagrilari == [1, 2]


def test_classify_karar_raises_after_max_attempts_exhausted():
    client = FakeClient([FakeAPIError(429), FakeAPIError(429), FakeAPIError(429)])
    try:
        classifier.classify_karar(client, "Başlık", "2026-01-01", "özet", "model", sleep_fn=lambda s: None)
        assert False, "RuntimeError bekleniyordu"
    except RuntimeError:
        pass


def test_classify_karar_does_not_retry_non_retryable_error():
    cagrildi_mi = []
    client = FakeClient([ValueError("kalıcı hata")])
    try:
        classifier.classify_karar(
            client, "Başlık", "2026-01-01", "özet", "model",
            sleep_fn=lambda s: cagrildi_mi.append(s),
        )
        assert False, "RuntimeError bekleniyordu"
    except RuntimeError:
        pass
    assert cagrildi_mi == []
    assert client.messages.calls == 1


def test_classify_pending_updates_db_on_success(conn):
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Karar", tarih="2026-01-01", kaynak_url="https://example.com/1", ozet_ham="Karar")
    client = FakeClient([_success_response()])
    sonuc = classifier.classify_pending(conn, client=client, model="model")
    assert sonuc == {"basarili": 1, "basarisiz": 0, "kalici_hata": 0}
    assert db.get_pending_kararlar(conn) == []


def test_classify_pending_marks_permanent_failure_after_max_deneme(conn):
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Karar", tarih="2026-01-01", kaynak_url="https://example.com/2", ozet_ham="Karar")

    for _ in range(3):
        client = FakeClient([FakeAPIError(429), FakeAPIError(429), FakeAPIError(429)])
        classifier.classify_pending(conn, client=client, model="model")

    assert db.get_pending_kararlar(conn) == []
    row = conn.execute("SELECT islendi_mi, deneme_sayisi FROM kararlar").fetchone()
    assert row["islendi_mi"] == -1
    assert row["deneme_sayisi"] == 3
```

(`conn` fixture'ı Task 2'de yazılan `tests/conftest.py`'den geliyor.)

- [ ] **Step 2: Testleri çalıştır, `classifier` modülü olmadığı için başarısız olduğunu doğrula**

Run: `pytest tests/test_classifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'classifier'`

- [ ] **Step 3: `classifier.py`'yi yaz**

```python
import os
import time

from anthropic import Anthropic

import db

MAX_BACKOFF_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1
MAX_KARAR_DENEME = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

KARAR_SINIFLANDIRMA_TOOL = {
    "name": "karar_sinifla",
    "description": "Bir KVKK Kurulu kararını şirket profillerine göre sınıflandırır.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sektorler": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["e-ticaret", "finans", "saglik", "egitim", "genel"],
                },
                "description": "Bu kararın ilgilendirdiği şirket profilleri.",
            },
            "ozet": {"type": "string", "description": "2-3 cümlelik özet."},
            "yapilmasi_gerekenler": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Şirketin yapması gereken somut adımlar.",
            },
            "aciliyet_var": {"type": "boolean"},
            "aciliyet_aciklama": {"type": "string"},
        },
        "required": [
            "sektorler", "ozet", "yapilmasi_gerekenler",
            "aciliyet_var", "aciliyet_aciklama",
        ],
    },
}


def build_prompt(baslik: str, tarih, ozet_ham: str) -> str:
    return (
        "Aşağıda bir KVKK (Kişisel Verilerin Korunması Kurumu) kurul kararının "
        "başlığı verilmiştir. Bu kararı karar_sinifla aracını kullanarak "
        "sınıflandır.\n\n"
        f"Tarih: {tarih or 'bilinmiyor'}\n"
        f"Başlık/Özet: {ozet_ham}\n"
    )


def _is_retryable(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) in RETRYABLE_STATUS_CODES


def _get_client() -> Anthropic:
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _get_model() -> str:
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")


def classify_karar(client, baslik, tarih, ozet_ham, model, sleep_fn=time.sleep) -> dict:
    prompt = build_prompt(baslik, tarih, ozet_ham)
    son_hata: Exception | None = None
    for deneme in range(MAX_BACKOFF_ATTEMPTS):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                tools=[KARAR_SINIFLANDIRMA_TOOL],
                tool_choice={"type": "tool", "name": "karar_sinifla"},
                messages=[{"role": "user", "content": prompt}],
            )
            for block in response.content:
                if getattr(block, "type", None) == "tool_use" and block.name == "karar_sinifla":
                    return block.input
            raise RuntimeError("Anthropic yanıtında tool_use bloğu bulunamadı")
        except Exception as exc:
            son_hata = exc
            son_deneme_mi = deneme == MAX_BACKOFF_ATTEMPTS - 1
            if not _is_retryable(exc) or son_deneme_mi:
                raise RuntimeError(f"Sınıflandırma başarısız: {son_hata}") from son_hata
            sleep_fn(BACKOFF_BASE_SECONDS * (2 ** deneme))
    raise RuntimeError(f"Sınıflandırma başarısız: {son_hata}")


def classify_pending(conn, client=None, model=None) -> dict:
    client = client or _get_client()
    model = model or _get_model()
    sonuc = {"basarili": 0, "basarisiz": 0, "kalici_hata": 0}
    for karar in db.get_pending_kararlar(conn):
        try:
            classification = classify_karar(
                client, karar["baslik"], karar["tarih"], karar["ozet_ham"], model,
            )
            db.update_karar_classification(
                conn,
                karar["id"],
                classification["sektorler"],
                classification["ozet"],
                classification["yapilmasi_gerekenler"],
                classification["aciliyet_var"],
                classification["aciliyet_aciklama"],
            )
            sonuc["basarili"] += 1
        except Exception:
            kalici_mi = db.mark_karar_failed(conn, karar["id"])
            if kalici_mi:
                sonuc["kalici_hata"] += 1
            else:
                sonuc["basarisiz"] += 1
    return sonuc


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    connection = db.get_connection()
    db.init_db(connection)
    sonuc = classify_pending(connection)
    print(f"Sınıflandırma sonucu: {sonuc}")
    for karar in db.get_kararlar_by_profil(connection, "genel"):
        print(f"- [{karar['tarih']}] {karar['baslik'][:80]}...")
        print(f"  Sektörler: {karar['sektorler']}")
        print(f"  Özet: {karar['ozet']}")
    connection.close()
```

- [ ] **Step 4: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_classifier.py -v`
Expected: 6 test PASS

- [ ] **Step 5: Commit et**

```bash
git add classifier.py tests/test_classifier.py
git commit -m "feat(classifier): Anthropic tool-use classification with exponential backoff"
```

---

### Task 7: Faz 2 Canlı Demo

**Files:** Yok (Task 5'te scrape edilmiş `kvkk.db` üzerinde çalışıyoruz)

**Interfaces:** Yok

- [ ] **Step 1: `.env` dosyasına gerçek `ANTHROPIC_API_KEY` gir**

Kullanıcıdan bir Anthropic API key isteyin (design'da kullanıcı "sonra
alacağım" demişti — bu adımdan önce alınmış olmalı), `.env` dosyasına
`ANTHROPIC_API_KEY=sk-ant-...` olarak yazın.

- [ ] **Step 2: Gerçek API'ye karşı çalıştır**

Run: `python classifier.py`
Expected: `Sınıflandırma sonucu: {'basarili': N, 'basarisiz': 0, 'kalici_hata': 0}`
çıktısı + her karar için sektör/özet konsola basılmış.

- [ ] **Step 3: SQLite'ta sonucu doğrula**

Run: `sqlite3 kvkk.db "SELECT baslik, sektorler, aciliyet_var FROM kararlar WHERE islendi_mi = 1 LIMIT 5"`
Expected: `sektorler` sütunu geçerli bir JSON array string (örn. `["e-ticaret","genel"]`).

- [ ] **Step 4: Kullanıcıya göster, onay al**

🛑 **FAZ 2 KONTROL NOKTASI** — Sınıflandırma çıktısını ve birkaç örnek
satırı kullanıcıya göster. Kullanıcı onaylamadan **Faz 3'e (Task 8)
geçme.**

---

## FAZ 3: Frontend + Backend Entegrasyonu

### Task 8: `index.html` + `backend.py` — Flask API ve Statik Sayfa

**Files:**
- Create: `index.html`
- Create: `backend.py`
- Create: `tests/test_backend.py`

**Interfaces:**
- Consumes: `db.get_connection`, `db.init_db`, `db.get_kararlar_by_profil`, `db.get_son_guncelleme` (Task 2), `scraper.scrape_and_store` (Task 4), `classifier.classify_pending` (Task 6)
- Produces:
  - `backend.app: Flask`
  - `backend.run_scrape() -> None`
  - `backend.main() -> None` (CLI giriş noktası, `--scrape` ve `--port` argümanları)

- [ ] **Step 1: Başarısız testleri yaz (`tests/test_backend.py`)**

```python
import db
import backend


def test_index_serves_html_with_disclaimer():
    client = backend.app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "hukuki tavsiye değildir" in body


def test_api_kararlar_returns_son_guncelleme_and_filtered_list(monkeypatch, tmp_path):
    db_path = tmp_path / "test_backend.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)

    conn = db.get_connection()
    db.init_db(conn)
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Genel Karar", tarih="2026-01-01", kaynak_url="https://example.com/1", ozet_ham="x")
    karar_id = db.get_pending_kararlar(conn)[0]["id"]
    db.update_karar_classification(conn, karar_id, ["genel"], "özet", ["madde"], False, "")
    conn.close()

    client = backend.app.test_client()
    response = client.get("/api/kararlar?profil=e-ticaret")
    veri = response.get_json()
    assert veri["son_guncelleme"] is not None
    assert len(veri["kararlar"]) == 1
    assert veri["kararlar"][0]["baslik"] == "Genel Karar"


def test_api_kararlar_defaults_to_genel_profile_when_empty(monkeypatch, tmp_path):
    db_path = tmp_path / "test_backend2.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    conn = db.get_connection()
    db.init_db(conn)
    conn.close()

    client = backend.app.test_client()
    response = client.get("/api/kararlar")
    veri = response.get_json()
    assert veri["kararlar"] == []
    assert veri["son_guncelleme"] is None
```

- [ ] **Step 2: Testleri çalıştır, `backend` modülü olmadığı için başarısız olduğunu doğrula**

Run: `pytest tests/test_backend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend'`

- [ ] **Step 3: `index.html`'i yaz**

```html
<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<title>KVKK Mevzuat Takip</title>
<style>
  body { font-family: -apple-system, "Segoe UI", Arial, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }
  h1 { font-size: 1.4rem; }
  .uyari { background: #fff3cd; border: 1px solid #ffe69c; padding: 0.75rem 1rem; border-radius: 4px; font-size: 0.9rem; margin-bottom: 1rem; }
  .ust-satir { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; gap: 0.5rem; }
  select { font-size: 1rem; padding: 0.3rem; }
  .son-guncelleme { font-size: 0.85rem; color: #555; }
  .karar { border: 1px solid #ddd; border-radius: 6px; padding: 1rem; margin-bottom: 1rem; }
  .karar h3 { margin: 0 0 0.4rem 0; font-size: 1.05rem; }
  .tarih { color: #666; font-size: 0.85rem; }
  .aciliyet { display: inline-block; background: #d32f2f; color: #fff; font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 3px; margin-left: 0.5rem; }
  .yapilmasi-gerekenler { margin: 0.5rem 0 0 0; padding-left: 1.2rem; }
  .bos { color: #666; font-style: italic; }
  a.kaynak-link { font-size: 0.85rem; }
</style>
</head>
<body>
  <div class="uyari">
    Bu araç hukuki tavsiye değildir, bilgi amaçlıdır. Kararlar için resmi kaynağı ve/veya bir avukatı kontrol edin.
  </div>
  <h1>KVKK Mevzuat Takip</h1>
  <div class="ust-satir">
    <label>
      Şirket profili:
      <select id="profil">
        <option value="genel">Genel</option>
        <option value="e-ticaret">E-ticaret</option>
        <option value="finans">Finans</option>
        <option value="saglik">Sağlık</option>
        <option value="egitim">Eğitim</option>
      </select>
    </label>
    <span class="son-guncelleme" id="son-guncelleme"></span>
  </div>
  <div id="liste"></div>

  <script>
    const profilSelect = document.getElementById("profil");
    const liste = document.getElementById("liste");
    const sonGuncellemeEl = document.getElementById("son-guncelleme");

    function esc(str) {
      const div = document.createElement("div");
      div.textContent = str ?? "";
      return div.innerHTML;
    }

    function formatTarih(iso) {
      if (!iso) return null;
      const d = new Date(iso);
      if (isNaN(d)) return iso;
      return d.toLocaleString("tr-TR");
    }

    function kararKart(karar) {
      const aciliyetHtml = karar.aciliyet_var
        ? `<span class="aciliyet" title="${esc(karar.aciliyet_aciklama)}">Aciliyet</span>`
        : "";
      const maddeler = (karar.yapilmasi_gerekenler || [])
        .map((m) => `<li>${esc(m)}</li>`)
        .join("");
      return `
        <div class="karar">
          <h3>${esc(karar.baslik)}${aciliyetHtml}</h3>
          <div class="tarih">${esc(karar.tarih)}</div>
          <p>${esc(karar.ozet)}</p>
          ${maddeler ? `<ul class="yapilmasi-gerekenler">${maddeler}</ul>` : ""}
          <a class="kaynak-link" href="${karar.kaynak_url}" target="_blank" rel="noopener">Kaynağı gör</a>
        </div>
      `;
    }

    async function yukle() {
      const profil = profilSelect.value;
      const res = await fetch(`/api/kararlar?profil=${encodeURIComponent(profil)}`);
      const veri = await res.json();
      const sonGuncelleme = formatTarih(veri.son_guncelleme);
      sonGuncellemeEl.textContent = sonGuncelleme
        ? `Son güncelleme: ${sonGuncelleme}`
        : "Henüz veri yok";
      if (!veri.kararlar || veri.kararlar.length === 0) {
        liste.innerHTML = '<p class="bos">Bu profil için henüz karar yok.</p>';
        return;
      }
      liste.innerHTML = veri.kararlar.map(kararKart).join("");
    }

    profilSelect.addEventListener("change", yukle);
    yukle();
  </script>
</body>
</html>
```

- [ ] **Step 4: `backend.py`'yi yaz**

```python
import argparse
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

import classifier
import db
import scraper

load_dotenv()

BASE_DIR = Path(__file__).parent
app = Flask(__name__, static_folder=None)


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/api/kararlar")
def api_kararlar():
    profil = request.args.get("profil", "genel")
    conn = db.get_connection()
    try:
        kararlar = db.get_kararlar_by_profil(conn, profil)
        son_guncelleme = db.get_son_guncelleme(conn)
    finally:
        conn.close()
    return jsonify({"son_guncelleme": son_guncelleme, "kararlar": kararlar})


def run_scrape() -> None:
    conn = db.get_connection()
    try:
        db.init_db(conn)
        yeni = scraper.scrape_and_store(conn)
        print(f"{yeni} yeni karar bulundu.")
        sonuc = classifier.classify_pending(conn)
        print(f"Sınıflandırma sonucu: {sonuc}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="KVKK Mevzuat Takip Aracı")
    parser.add_argument("--scrape", action="store_true", help="Scrape + sınıflandırma pipeline'ını çalıştır")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    if args.scrape:
        run_scrape()
        return

    conn = db.get_connection()
    db.init_db(conn)
    conn.close()
    app.run(port=args.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_backend.py -v`
Expected: 3 test PASS

- [ ] **Step 6: Tüm test paketini çalıştır**

Run: `pytest -v`
Expected: Tüm testler (db + scraper + classifier + backend) PASS.

- [ ] **Step 7: Commit et**

```bash
git add index.html backend.py tests/test_backend.py
git commit -m "feat(web): Flask API + single-file frontend serving classified kararlar"
```

---

### Task 9: Faz 3 Uçtan Uca Canlı Demo

**Files:** Yok

**Interfaces:** Yok

- [ ] **Step 1: Temiz baştan uçtan uca çalıştır**

Run: `rm -f kvkk.db && python backend.py --scrape`
Expected: Konsolda scrape + sınıflandırma çıktısı (`N yeni karar bulundu.`,
`Sınıflandırma sonucu: {...}`).

- [ ] **Step 2: Web sunucusunu başlat**

Run: `python backend.py`
Expected: `http://127.0.0.1:5000` üzerinde Flask sunucu ayağa kalkar.

- [ ] **Step 3: Tarayıcıda doğrula**

`http://localhost:5000` adresini aç, dropdown'dan farklı profiller seç,
her seçimde kart listesinin ve "Son güncelleme: ..." satırının
güncellendiğini, üstteki hukuki uyarının göründüğünü doğrula.

- [ ] **Step 4: Kullanıcıya göster, onay al**

🛑 **FAZ 3 KONTROL NOKTASI (son)** — Tarayıcıda çalışan uygulamayı
(ekran görüntüsü/canlı demo) kullanıcıya göster. Onay alındıktan sonra
proje MVP kapsamıyla tamamlanmış sayılır. BDDK/SPK/Resmi Gazete
kaynaklarının eklenmesi ayrı bir sonraki iterasyon konusudur (bu planın
kapsamında değil).

---

## Self-Review Notları (plan yazarı tarafından, uygulayıcı için referans)

- **Kapsam kontrolü:** Spec'teki her madde bir task'a karşılık geliyor:
  proje yapısı → Task 1, veri modeli → Task 2, scraper → Task 3-5,
  LLM sınıflandırma + retry/backoff/deneme_sayisi → Task 6-7, API +
  frontend + son_guncelleme → Task 8-9, lisans/uyarı → Task 1.
- **Tip/arayüz tutarlılığı:** `db.mark_karar_failed` bir `bool` (kalıcı
  hata mı) döner; `classifier.classify_pending` bu değeri doğrudan kullanır
  — eşik mantığı (`>= 3`) sadece `db.py` içinde bir yerde yaşıyor,
  tekrarlanmıyor. `db.get_connection(db_path=None)` bilinçli olarak
  `DB_PATH`'i çağrı anında okuyor (Task 9'daki monkeypatch testleri buna
  dayanıyor).
- **Canlı doğrulama:** Task 3'teki fixture ve CSS seçiciler
  (`div.members__item`, `.members__item-meta h2`, `a.read-more`) plan
  yazımı sırasında gerçek `https://www.kvkk.gov.tr/Icerik/5419/kurul-kararlari`
  sayfasına `curl` ile bakılarak doğrulandı — placeholder/varsayım değil.
