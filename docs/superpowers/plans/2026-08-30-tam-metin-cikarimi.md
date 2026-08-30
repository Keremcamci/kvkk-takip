# Karar Metninin Zenginleştirilmesi (Tam Metin Çıkarımı) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **PHASE GATES ARE MANDATORY.** Bu plan 3 faza bölünmüş (altyapı, BDDK
> entegrasyonu, KVKK entegrasyonu). Her fazın sonunda bir
> `🛑 FAZ KONTROL NOKTASI` bloğu var. Bu planı uygulayan DURMALI,
> belirtilen demoyu kullanıcıya göstermeli ve bir sonraki faza geçmeden
> önce açık onay almalıdır.

**Goal:** BDDK ve KVKK kararları için `ozet_ham`'ı (LLM'e giden ham girdi)
karar başlığının bir kopyası olmaktan çıkarıp, mümkün olduğunda gerçek
karar metniyle (PDF veya sayfa özeti) doldur.

**Architecture:** Yeni bir modül `scrapers/tammetin.py`, iki bağımsız
çıkarım fonksiyonu sağlar (`pdf_metni_cek`, `kvkk_sayfa_metni_cek`). Her
ikisi de her hata sınıfında `None` döner, hiçbir exception fırlatmaz.
`scrapers/bddk.py` ve `scrapers/kvkk.py`, yeni bir kararı DB'ye yazmadan
önce bu fonksiyonları çağırıp `ozet_ham`'ı zenginleştirir; başarısızsa
mevcut davranış (başlık) korunur. `classifier.py`'de HİÇBİR değişiklik
yok — `build_prompt()` zaten `ozet_ham`'ı olduğu gibi kullanıyor.

**Tech Stack:** Mevcutla aynı + yeni bağımlılık `pypdf` (PDF metin
çıkarımı için).

**Spec:** `docs/superpowers/specs/2026-08-30-tam-metin-cikarimi-design.md`

## Global Constraints

- Kapsam SADECE BDDK + KVKK. SPK (React SPA, düz HTTP ile içeriğe
  ulaşılamıyor) ve Resmi Gazete (`kaynak_url` tek maddeye değil günün
  fihrist sayfasına gidiyor) bu iterasyonda başlık-tabanlı KALIR —
  dokunulmuyor.
- `classifier.py`, DB şeması, API/UI — hiçbirine dokunulmuyor.
  `ozet_ham` sütunu zaten var; sadece scraper'ların ona ne yazdığı
  değişiyor.
- BDDK `kaynak_url` (`bddk.org.tr/Mevzuat/DokumanGetir/{id}`) canlı test
  edildi: düz GET, `Content-Type: application/pdf` döner.
- KVKK'da iki alt durum: `www.kvkk.gov.tr` host'lu linkler HTML detay
  sayfası (`div.news__detail-article` seçicisinde gerçek özet metni);
  diğer TÜM linkler (ör. `resmigazete.gov.tr`) doğrudan PDF.
- PDF boyutu üst sınırı: **5.000.000 bayt (5 MB)**. Üstü atlanır, metin
  çıkarımı denenmez.
- Çıkarılan metin **6000 karakterde** düz `metin[:6000]` ile kırpılır
  (kelime/cümle sınırı gözetilmez).
- Her hata sınıfı (ağ hatası, yanlış content-type, boş/taranmış metin,
  seçici bulunamadı, dosya çok büyük) `logging.warning` ile loglanır ve
  fonksiyon `None` döner — scraper'ın geri kalanını DURDURMAZ.
- Yeni `db.py` fonksiyonu: `karar_var_mi(conn, kaynak_url) -> bool` —
  zaten bilinen bir karar için gereksiz tam metin indirmesi yapılmasın
  diye, `insert_karar_if_new`'den ÖNCE çağrılır.
- Fixture'lar plan yazımı sırasında HAZIRLANDI ve commit edildi (bu
  planın kendisiyle aynı PR'da):
  - `tests/fixtures/bddk_karar_sample.pdf` — canlı BDDK sitesinden
    indirilen gerçek dosya (Karar No 11548, 136 KB, "BLG Varlık Yönetim
    A.Ş." metnini içeriyor).
  - `tests/fixtures/kvkk_karar_detay_sample.html` — gerçek KVKK detay
    sayfasının yapısını taklit eden, `div.news__detail-article` içeren
    ve yan panelde alakasız "Duyurular" içeriği taşıyan (seçicinin bunu
    doğru şekilde DIŞLADIĞINI kanıtlamak için) kırpılmış bir örnek.
  - `requirements.txt`'e `pypdf>=5.0` zaten eklendi.
- Her fazın sonunda kullanıcıya çalışan bir demo gösterilir, onay
  alınmadan sıradaki faza geçilmez.

---

## FAZ 1: Altyapı — `scrapers/tammetin.py` + `db.karar_var_mi`

### Task 1: `db.karar_var_mi`

**Files:**
- Modify: `db.py`
- Modify: `tests/test_db.py`

**Interfaces:**
- Consumes: yok (mevcut `conn.execute` deseni)
- Produces: `db.karar_var_mi(conn, kaynak_url: str) -> bool`

- [ ] **Step 1: Başarısız testleri yaz (`tests/test_db.py`'nin sonuna)**

```python
def test_karar_var_mi_returns_false_for_unknown_url(conn):
    assert db.karar_var_mi(conn, "https://example.com/hic-yok") is False


def test_karar_var_mi_returns_true_for_known_url(conn):
    db.insert_karar_if_new(
        conn, kaynak="kvkk", baslik="Karar", tarih="2026-01-01",
        kaynak_url="https://example.com/biliniyor", ozet_ham="x",
    )
    assert db.karar_var_mi(conn, "https://example.com/biliniyor") is True
```

- [ ] **Step 2: Testleri çalıştır, başarısız olduklarını doğrula**

Run: `pytest tests/test_db.py -k karar_var_mi -v`
Expected: FAIL — `AttributeError: module 'db' has no attribute 'karar_var_mi'`

- [ ] **Step 3: `db.py`'ye fonksiyonu ekle**

`get_kaynak_sayilari` fonksiyonundan hemen sonra ekle:

```python
def karar_var_mi(conn, kaynak_url) -> bool:
    row = conn.execute(
        "SELECT 1 FROM kararlar WHERE kaynak_url = ?", (kaynak_url,)
    ).fetchone()
    return row is not None
```

- [ ] **Step 4: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_db.py -v`
Expected: Tüm testler PASS (eski + 2 yeni)

- [ ] **Step 5: Tüm paketi çalıştır (regresyon yok)**

Run: `pytest -v`
Expected: 124/124 PASS (122 + 2 yeni)

- [ ] **Step 6: Commit et**

```bash
git add db.py tests/test_db.py
git commit -m "feat(db): add karar_var_mi existence check"
```

---

### Task 2: `scrapers/tammetin.py`

**Files:**
- Create: `scrapers/tammetin.py`
- Create: `tests/test_scrapers_tammetin.py`
- Fixture (zaten mevcut): `tests/fixtures/bddk_karar_sample.pdf`,
  `tests/fixtures/kvkk_karar_detay_sample.html`

**Interfaces:**
- Consumes: `scrapers.common.USER_AGENT` (mevcut)
- Produces:
  - `scrapers.tammetin.MAKS_PDF_BAYT: int` (5_000_000)
  - `scrapers.tammetin.MAKS_METIN_KARAKTER: int` (6000)
  - `scrapers.tammetin.pdf_metni_cek(url: str, timeout: int = 15) -> str | None`
  - `scrapers.tammetin.kvkk_sayfa_metni_cek(url: str, timeout: int = 15) -> str | None`

- [ ] **Step 1: Başarısız testleri yaz (`tests/test_scrapers_tammetin.py`)**

```python
import logging
from pathlib import Path
from unittest.mock import Mock, patch

from scrapers import tammetin

BDDK_PDF_FIXTURE = Path(__file__).parent / "fixtures" / "bddk_karar_sample.pdf"
KVKK_DETAY_FIXTURE = Path(__file__).parent / "fixtures" / "kvkk_karar_detay_sample.html"


def _pdf_response(content_type="application/pdf"):
    fake = Mock()
    fake.headers = {"Content-Type": content_type}
    fake.content = BDDK_PDF_FIXTURE.read_bytes()
    fake.raise_for_status = Mock()
    return fake


def test_pdf_metni_cek_extracts_real_text_from_pdf():
    with patch("scrapers.tammetin.requests.get", return_value=_pdf_response()):
        metin = tammetin.pdf_metni_cek("https://example.com/karar.pdf")
    assert metin is not None
    assert "BLG Varlık Yönetim" in metin
    assert "karar verilmiştir" in metin


def test_pdf_metni_cek_returns_none_on_network_error(caplog):
    with patch("scrapers.tammetin.requests.get", side_effect=ConnectionError("bağlantı koptu")):
        with caplog.at_level(logging.WARNING):
            metin = tammetin.pdf_metni_cek("https://example.com/karar.pdf")
    assert metin is None
    assert "indirilemedi" in caplog.text


def test_pdf_metni_cek_returns_none_for_non_pdf_content_type(caplog):
    with patch("scrapers.tammetin.requests.get", return_value=_pdf_response(content_type="text/html")):
        with caplog.at_level(logging.WARNING):
            metin = tammetin.pdf_metni_cek("https://example.com/sayfa")
    assert metin is None
    assert "PDF değil" in caplog.text


def test_pdf_metni_cek_returns_none_when_file_too_large(caplog):
    fake = _pdf_response()
    fake.content = b"x" * (tammetin.MAKS_PDF_BAYT + 1)
    with patch("scrapers.tammetin.requests.get", return_value=fake):
        with caplog.at_level(logging.WARNING):
            metin = tammetin.pdf_metni_cek("https://example.com/buyuk.pdf")
    assert metin is None
    assert "çok büyük" in caplog.text


def test_pdf_metni_cek_returns_none_when_no_extractable_text(caplog):
    fake = _pdf_response()
    with patch("scrapers.tammetin.requests.get", return_value=fake), \
         patch("scrapers.tammetin.PdfReader") as mock_reader:
        sahte_sayfa = Mock()
        sahte_sayfa.extract_text.return_value = ""
        mock_reader.return_value.pages = [sahte_sayfa]
        with caplog.at_level(logging.WARNING):
            metin = tammetin.pdf_metni_cek("https://example.com/taranmis.pdf")
    assert metin is None
    assert "çıkarılamadı" in caplog.text


def test_pdf_metni_cek_truncates_to_max_length():
    fake = _pdf_response()
    with patch("scrapers.tammetin.requests.get", return_value=fake), \
         patch("scrapers.tammetin.PdfReader") as mock_reader:
        uzun_metin = "a" * (tammetin.MAKS_METIN_KARAKTER + 500)
        sahte_sayfa = Mock()
        sahte_sayfa.extract_text.return_value = uzun_metin
        mock_reader.return_value.pages = [sahte_sayfa]
        metin = tammetin.pdf_metni_cek("https://example.com/uzun.pdf")
    assert len(metin) == tammetin.MAKS_METIN_KARAKTER


def test_kvkk_sayfa_metni_cek_extracts_article_text_and_excludes_sidebar():
    fake = Mock()
    fake.text = KVKK_DETAY_FIXTURE.read_text(encoding="utf-8")
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake):
        metin = tammetin.kvkk_sayfa_metni_cek("https://www.kvkk.gov.tr/Icerik/7791/2023-2135")
    assert metin is not None
    assert "oybirliği ile karar verilmiştir" in metin
    assert "Duyurular" not in metin  # yan panel içeriğe sızmamalı


def test_kvkk_sayfa_metni_cek_returns_none_when_selector_not_found(caplog):
    fake = Mock()
    fake.text = "<html><body><p>Beklenmeyen sayfa yapısı</p></body></html>"
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake):
        with caplog.at_level(logging.WARNING):
            metin = tammetin.kvkk_sayfa_metni_cek("https://www.kvkk.gov.tr/Icerik/9999/yok")
    assert metin is None
    assert "bulunamadı" in caplog.text


def test_kvkk_sayfa_metni_cek_returns_none_on_network_error(caplog):
    with patch("scrapers.tammetin.requests.get", side_effect=ConnectionError("zaman aşımı")):
        with caplog.at_level(logging.WARNING):
            metin = tammetin.kvkk_sayfa_metni_cek("https://www.kvkk.gov.tr/Icerik/1/1")
    assert metin is None
    assert "indirilemedi" in caplog.text
```

- [ ] **Step 2: Testleri çalıştır, `scrapers.tammetin` modülü olmadığı için
      başarısız olduğunu doğrula**

Run: `pytest tests/test_scrapers_tammetin.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapers.tammetin'`

- [ ] **Step 3: `scrapers/tammetin.py`'yi yaz**

```python
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
    except requests.RequestException as exc:
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
    except requests.RequestException as exc:
        logging.warning("KVKK detay sayfası indirilemedi (%s): %s", url, exc)
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    makale = soup.select_one("div.news__detail-article")
    if makale is None:
        logging.warning("KVKK detay sayfasında beklenen içerik bulunamadı: %s", url)
        return None

    metin = makale.get_text(separator=" ", strip=True)
    return metin[:MAKS_METIN_KARAKTER] if metin else None
```

- [ ] **Step 4: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_scrapers_tammetin.py -v`
Expected: 9 test PASS

- [ ] **Step 5: Tüm paketi çalıştır (regresyon yok)**

Run: `pytest -v`
Expected: 133/133 PASS (124 + 9 yeni)

- [ ] **Step 6: Commit et**

```bash
git add scrapers/tammetin.py tests/test_scrapers_tammetin.py
git commit -m "feat(scrapers): add tammetin module for PDF and KVKK page text extraction"
```

---

### Task 3: Faz 1 Doğrulama

**Files:** Yok

**Interfaces:** Yok

- [ ] **Step 1: Gerçek BDDK PDF'ine karşı manuel doğrula**

Run:
```bash
python3 -c "
from scrapers.tammetin import pdf_metni_cek
print(pdf_metni_cek('https://www.bddk.org.tr/Mevzuat/DokumanGetir/1345'))
"
```
Expected: Gerçek karar metni konsola basılır (Karar Sayısı, Karar Tarihi,
kararın gerekçesi) — `None` DEĞİL.

- [ ] **Step 2: Gerçek KVKK detay sayfasına karşı manuel doğrula**

Run:
```bash
python3 -c "
from scrapers.tammetin import kvkk_sayfa_metni_cek
print(kvkk_sayfa_metni_cek('https://www.kvkk.gov.tr/Icerik/7791/2023-2135'))
"
```
Expected: "Konu Özeti" ve gerekçe paragrafı konsola basılır — `None` DEĞİL.

- [ ] **Step 3: Kullanıcıya göster, onay al**

🛑 **FAZ 1 KONTROL NOKTASI** — İki manuel doğrulamanın çıktısını
kullanıcıya göster. Kullanıcı onaylamadan **Faz 2'ye (Task 4) geçme.**

**GÜNCELLEME (bu faz sırasında keşfedildi):** Step 1'de gerçek BDDK
sitesine karşı çalıştırıldığında `pdf_metni_cek` bir `SSLCertVerificationError`
ile `None` döndü — BDDK'nın sunucusu TLS handshake'inde ara sertifikayı
(GlobalSign RSA OV SSL CA 2018) göndermiyor; tarayıcılar bunu AIA ile
otomatik telafi eder, `requests`/`certifi` etmez. Kod doğru davrandı
(hata yakalandı, `None` + uyarı), ama bu haliyle BDDK için tam metin
özelliği canlıda HİÇBİR ZAMAN çalışmayacaktı. Kullanıcı onayıyla eksik
ara sertifika pakete gömülüp güven zincirine eklendi — bkz. **Task 9**
(bu task, Faz 2 canlı demosundan (Task 5) ÖNCE tamamlanmalı).

---

## FAZ 2: BDDK Entegrasyonu

### Task 4: `scrapers/bddk.py` — Tam Metin Zenginleştirmesi

**Files:**
- Modify: `scrapers/bddk.py`
- Modify: `tests/test_scrapers_bddk.py`

**Interfaces:**
- Consumes: `scrapers.tammetin.pdf_metni_cek` (Task 2), `db.karar_var_mi`
  (Task 1)
- Produces: `scrapers.bddk.scrape_and_store` davranış değişikliği
  (imza AYNI kalır)

**ÖNEMLİ**: `tests/test_scrapers_bddk.py`'de zaten `scrape_and_store`'u
çağıran 3 MEVCUT test var
(`test_scrape_and_store_inserts_new_kararlar`,
`test_scrape_and_store_is_idempotent`,
`test_scrape_and_store_respects_limit`). Bu task'ta `scrape_and_store`
içine `tammetin.pdf_metni_cek` çağrısı eklenince bu 3 test
GÜNCELLENMEZSE, gerçek BDDK sitesine (ağa) çıkmaya çalışıp
yavaşlar/başarısız olur — bu adımda hem `bddk.py` hem bu 3 test birlikte
güncelleniyor.

- [ ] **Step 1: Mevcut 3 testi güncelle + yeni başarısız testleri ekle**

`tests/test_scrapers_bddk.py`'deki 3 mevcut testi şu üçüyle DEĞİŞTİR
(sadece `with patch(...)` bloğuna ikinci bir `patch` eklendi, gerisi
AYNI):

```python
def test_scrape_and_store_inserts_new_kararlar(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.bddk.fetch_page", return_value=html), \
         patch("scrapers.bddk.tammetin.pdf_metni_cek", return_value=None):
        yeni_sayisi = bddk.scrape_and_store(conn)
    assert yeni_sayisi == 3
    assert len(db.get_pending_kararlar(conn)) == 3


def test_scrape_and_store_is_idempotent(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.bddk.fetch_page", return_value=html), \
         patch("scrapers.bddk.tammetin.pdf_metni_cek", return_value=None):
        bddk.scrape_and_store(conn)
        ikinci_calistirma = bddk.scrape_and_store(conn)
    assert ikinci_calistirma == 0


def test_scrape_and_store_respects_limit(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.bddk.fetch_page", return_value=html), \
         patch("scrapers.bddk.tammetin.pdf_metni_cek", return_value=None):
        yeni_sayisi = bddk.scrape_and_store(conn, limit=2)
    assert yeni_sayisi == 2
```

Dosyanın SONUNA yeni testleri ekle:

```python
def test_scrape_and_store_uses_full_text_when_pdf_extraction_succeeds(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.bddk.fetch_page", return_value=html), \
         patch("scrapers.bddk.tammetin.pdf_metni_cek", return_value="Gerçek karar metni burada."):
        bddk.scrape_and_store(conn, limit=1)
    karar = db.get_pending_kararlar(conn)[0]
    assert karar["ozet_ham"] == "Gerçek karar metni burada."


def test_scrape_and_store_falls_back_to_title_when_pdf_extraction_fails(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.bddk.fetch_page", return_value=html), \
         patch("scrapers.bddk.tammetin.pdf_metni_cek", return_value=None):
        bddk.scrape_and_store(conn, limit=1)
    karar = db.get_pending_kararlar(conn)[0]
    assert karar["ozet_ham"] == karar["baslik"]


def test_scrape_and_store_does_not_refetch_full_text_for_known_kararlar(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.bddk.fetch_page", return_value=html), \
         patch("scrapers.bddk.tammetin.pdf_metni_cek", return_value=None) as mock_pdf:
        bddk.scrape_and_store(conn)
        ilk_cagri_sayisi = mock_pdf.call_count
        bddk.scrape_and_store(conn)
        ikinci_cagri_sayisi = mock_pdf.call_count
    assert ilk_cagri_sayisi == 3  # fixture'da 3 karar var
    assert ikinci_cagri_sayisi == ilk_cagri_sayisi  # ikinci koşuda yeni çağrı yok
```

- [ ] **Step 2: Testleri çalıştır, yeni 3 testin `AttributeError` ile
      başarısız olduğunu, güncellenen 3 testin (henüz `bddk.py`
      değişmediği için) hâlâ PASS olduğunu doğrula**

Run: `pytest tests/test_scrapers_bddk.py -v`
Expected: 6 PASS, 3 FAIL —
`AttributeError: <module 'scrapers.bddk'> does not have the attribute 'tammetin'`

- [ ] **Step 3: `scrapers/bddk.py`'yi güncelle**

Import satırlarını değiştir:

```python
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import db
from scrapers import tammetin
from scrapers.common import USER_AGENT
```

`scrape_and_store` fonksiyonunu değiştir:

```python
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
```

(`_parse_tarih`, `parse_kararlar`, `fetch_page`, `__main__` bloğu AYNI
kalır.)

- [ ] **Step 4: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_scrapers_bddk.py -v`
Expected: Tüm testler PASS (9/9)

- [ ] **Step 5: Tüm paketi çalıştır (regresyon yok)**

Run: `pytest -v`
Expected: 142/142 PASS (139 + 3 yeni — Task 2 fix round +1 ve Task 9 +5
bu task'tan önce zaten eklendi)

- [ ] **Step 6: Commit et**

```bash
git add scrapers/bddk.py tests/test_scrapers_bddk.py
git commit -m "feat(bddk): enrich ozet_ham with real PDF text when available"
```

---

### Task 5: Faz 2 Canlı Demo

**GÜNCELLEME (bu faz sırasında keşfedildi):** Step 1'i çalıştırırken
`scrapers/bddk.py`'nin KENDİ `fetch_page()`'i (liste sayfasını çeken)
de aynı SSL hatasıyla patladı — Task 9'daki düzeltme yalnızca
`scrapers/tammetin.py`'nin iki fonksiyonuna uygulanmıştı, `bddk.py`'nin
liste sayfası isteğine değil. Canlı doğrulandı: aynı eksik ara sertifika
sorunu `www.bddk.org.tr/Mevzuat/Liste/55` için de geçerli, aynı
`_guven_paketi()` düzeltmesi burayı da çözüyor (certifi-only → `SSLError`,
`_guven_paketi()` ile → `200`, 637234 bayt). Bu **Task 10** olarak plana
eklendi; bu task'ın adımları Task 10 TAMAMLANDIKTAN SONRA çalıştırılmalı.

**Files:** Yok

**Interfaces:** Yok

- [ ] **Step 1: Temiz bir DB'ye karşı gerçek BDDK sitesinden tara**

Run: `rm -f kvkk.db kvkk.db-wal kvkk.db-shm && python -m scrapers.bddk`
Expected: `N yeni BDDK kararı bulundu.` çıktısı.

- [ ] **Step 2: `ozet_ham`'ın gerçekten tam metin içerdiğini SQLite'ta
      doğrula**

Run:
```bash
sqlite3 kvkk.db "SELECT substr(ozet_ham, 1, 200) FROM kararlar WHERE kaynak = 'bddk' LIMIT 3"
```
Expected: Her satır, karar BAŞLIĞINDAN görünüşte farklı, gerçek karar
metninin ilk 200 karakteri (ör. "Bankacılık Düzenleme ve Denetleme
Kurumundan: ... BANKACILIK DÜZENLEME VE DENETLEME KURULU KARARI ..." gibi)
— yalnızca başlığın tekrarı DEĞİL.

- [ ] **Step 3: Kullanıcıya göster, onay al**

🛑 **FAZ 2 KONTROL NOKTASI** — SQLite sorgusunun çıktısını kullanıcıya
göster (BDDK kararlarının artık gerçek metin içerdiğinin kanıtı).
Kullanıcı onaylamadan **Faz 3'e (Task 6) geçme.**

---

## FAZ 3: KVKK Entegrasyonu + Dokümantasyon

### Task 6: `scrapers/kvkk.py` — Tam Metin Zenginleştirmesi (İki Alt Durum)

**Files:**
- Modify: `scrapers/kvkk.py`
- Modify: `tests/test_scrapers_kvkk.py`

**Interfaces:**
- Consumes: `scrapers.tammetin.pdf_metni_cek`,
  `scrapers.tammetin.kvkk_sayfa_metni_cek` (Task 2), `db.karar_var_mi`
  (Task 1)
- Produces: `scrapers.kvkk.scrape_and_store` davranış değişikliği
  (imza AYNI kalır)

**Hatırlatma — fixture'daki 3 karar**: `tests/fixtures/kvkk_kararlari_sample.html`
şunları içeriyor: "Sadakat Kart..." (dış link,
`resmigazete.gov.tr/eskiler/2026/08/20260813-3.pdf`), "Ana Faaliyet
Konusu..." (dış link, `resmigazete.gov.tr/eskiler/2025/10/20251001-4.pdf`),
"Köy Tüzel Kişiliklerinin..." (dahili link, `kvkk.gov.tr/Icerik/7791/...`).
Yani 2 dış (PDF), 1 dahili (sayfa).

**ÖNEMLİ**: `tests/test_scrapers_kvkk.py`'deki 2 MEVCUT test
(`test_scrape_and_store_inserts_new_kararlar`,
`test_scrape_and_store_is_idempotent`) bu task'ta güncellenmezse gerçek
ağa çıkmaya çalışır.

- [ ] **Step 1: Mevcut 2 testi güncelle + yeni başarısız testleri ekle**

`tests/test_scrapers_kvkk.py`'deki 2 mevcut testi şu ikisiyle DEĞİŞTİR:

```python
def test_scrape_and_store_inserts_new_kararlar(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.kvkk.fetch_page", return_value=html), \
         patch("scrapers.kvkk.tammetin.pdf_metni_cek", return_value=None), \
         patch("scrapers.kvkk.tammetin.kvkk_sayfa_metni_cek", return_value=None):
        yeni_sayisi = kvkk.scrape_and_store(conn)
    assert yeni_sayisi == 3
    assert len(db.get_pending_kararlar(conn)) == 3


def test_scrape_and_store_is_idempotent(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.kvkk.fetch_page", return_value=html), \
         patch("scrapers.kvkk.tammetin.pdf_metni_cek", return_value=None), \
         patch("scrapers.kvkk.tammetin.kvkk_sayfa_metni_cek", return_value=None):
        kvkk.scrape_and_store(conn)
        ikinci_calistirma = kvkk.scrape_and_store(conn)
    assert ikinci_calistirma == 0
```

Dosyanın SONUNA yeni testleri ekle:

```python
def test_scrape_and_store_uses_kvkk_page_text_for_internal_kvkk_urls(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.kvkk.fetch_page", return_value=html), \
         patch("scrapers.kvkk.tammetin.pdf_metni_cek", return_value=None), \
         patch("scrapers.kvkk.tammetin.kvkk_sayfa_metni_cek", return_value="KVKK sayfasından gerçek özet."):
        kvkk.scrape_and_store(conn)
    koy_karari = next(
        k for k in db.get_pending_kararlar(conn) if "Köy Tüzel" in k["baslik"]
    )
    assert koy_karari["ozet_ham"] == "KVKK sayfasından gerçek özet."


def test_scrape_and_store_uses_pdf_text_for_external_urls(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.kvkk.fetch_page", return_value=html), \
         patch("scrapers.kvkk.tammetin.pdf_metni_cek", return_value="PDF'den gerçek metin."), \
         patch("scrapers.kvkk.tammetin.kvkk_sayfa_metni_cek", return_value=None):
        kvkk.scrape_and_store(conn)
    sadakat_karari = next(
        k for k in db.get_pending_kararlar(conn) if "Sadakat Kart" in k["baslik"]
    )
    assert sadakat_karari["ozet_ham"] == "PDF'den gerçek metin."


def test_scrape_and_store_falls_back_to_title_when_full_text_unavailable(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.kvkk.fetch_page", return_value=html), \
         patch("scrapers.kvkk.tammetin.pdf_metni_cek", return_value=None), \
         patch("scrapers.kvkk.tammetin.kvkk_sayfa_metni_cek", return_value=None):
        kvkk.scrape_and_store(conn)
    for karar in db.get_pending_kararlar(conn):
        assert karar["ozet_ham"] == karar["baslik"]


def test_scrape_and_store_does_not_refetch_full_text_for_known_kararlar(conn):
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.kvkk.fetch_page", return_value=html), \
         patch("scrapers.kvkk.tammetin.pdf_metni_cek", return_value=None) as mock_pdf, \
         patch("scrapers.kvkk.tammetin.kvkk_sayfa_metni_cek", return_value=None) as mock_sayfa:
        kvkk.scrape_and_store(conn)
        ilk_pdf, ilk_sayfa = mock_pdf.call_count, mock_sayfa.call_count
        kvkk.scrape_and_store(conn)
        ikinci_pdf, ikinci_sayfa = mock_pdf.call_count, mock_sayfa.call_count
    assert ilk_pdf == 2  # 2 dış (PDF) link
    assert ilk_sayfa == 1  # 1 dahili (kvkk.gov.tr) link
    assert ikinci_pdf == ilk_pdf
    assert ikinci_sayfa == ilk_sayfa
```

- [ ] **Step 2: Testleri çalıştır, yeni 4 testin `AttributeError` ile
      başarısız olduğunu doğrula**

Run: `pytest tests/test_scrapers_kvkk.py -v`
Expected: 5 PASS, 4 FAIL —
`AttributeError: <module 'scrapers.kvkk'> does not have the attribute 'tammetin'`

- [ ] **Step 3: `scrapers/kvkk.py`'yi güncelle**

Import satırlarını değiştir:

```python
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import db
from scrapers import tammetin
from scrapers.common import USER_AGENT
```

`scrape_and_store` fonksiyonunu değiştir:

```python
def scrape_and_store(conn, url: str = KVKK_LIST_URL) -> int:
    html = fetch_page(url)
    kararlar = parse_karar_listesi(html, base_url=url)
    yeni_sayisi = 0
    for karar in kararlar:
        if db.karar_var_mi(conn, karar["kaynak_url"]):
            continue
        if urlparse(karar["kaynak_url"]).netloc == "www.kvkk.gov.tr":
            tam_metin = tammetin.kvkk_sayfa_metni_cek(karar["kaynak_url"])
        else:
            tam_metin = tammetin.pdf_metni_cek(karar["kaynak_url"])
        if tam_metin:
            karar["ozet_ham"] = tam_metin
        if db.insert_karar_if_new(conn, kaynak="kvkk", **karar):
            yeni_sayisi += 1
    return yeni_sayisi
```

(`_parse_tarih`, `parse_karar_listesi`, `fetch_page`, `__main__` bloğu
AYNI kalır.)

- [ ] **Step 4: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_scrapers_kvkk.py -v`
Expected: Tüm testler PASS (9/9)

- [ ] **Step 5: Tüm paketi çalıştır (regresyon yok)**

Run: `pytest -v`
Expected: 148/148 PASS (144 + 4 yeni)

- [ ] **Step 6: Commit et**

```bash
git add scrapers/kvkk.py tests/test_scrapers_kvkk.py
git commit -m "feat(kvkk): enrich ozet_ham with real page/PDF text when available"
```

---

### Task 7: `README.md` Güncellemesi

**Files:**
- Modify: `README.md`

**Interfaces:** Yok (saf dokümantasyon)

- [ ] **Step 1: "Kapsam dışı" paragrafını değiştir**

`README.md`'deki şu paragrafı:

```markdown
Kapsam dışı (ileriye dönük): PDF tam metin çıkarımı (yalnızca liste
sayfasındaki başlık kullanılıyor) ve sayfalama — yani her kaynağın ilk
sayfasından öteye gidilmiyor.
```

şununla DEĞİŞTİR:

```markdown
BDDK ve KVKK kararları artık (mümkün olduğunda) gerçek karar metninden
sınıflandırılıyor — BDDK için doğrudan PDF, KVKK için (kaynağa göre)
kendi detay sayfasındaki özet veya PDF. Tam metin indirilemezse (ağ
hatası, taranmış/görsel PDF, vb.) sessizce başlığa düşülür.

SPK ve Resmi Gazete kararları hâlâ yalnızca başlıktan sınıflandırılıyor:
SPK'nın "Dosya" linki JavaScript ile render edilen bir sayfa (düz bir
HTTP isteğiyle içeriğe ulaşılamıyor); Resmi Gazete'nin linki tek bir
maddeye değil günün fihrist sayfasına gidiyor (bkz. aşağıdaki not).

Kapsam dışı (ileriye dönük): SPK/Resmi Gazete için tam metin çıkarımı ve
sayfalama — yani her kaynağın ilk sayfasından öteye gidilmiyor.
```

- [ ] **Step 2: Tüm paketi çalıştır (regresyon yok — saf dokümantasyon
      değişikliği ama alışkanlık olarak doğrula)**

Run: `pytest -v`
Expected: 148/148 PASS (bu task yeni test eklemedi)

- [ ] **Step 3: Commit et**

```bash
git add README.md
git commit -m "docs: describe BDDK/KVKK full-text extraction, SPK/Resmi Gazete limitation"
```

---

### Task 8: Faz 3 Uçtan Uca Canlı Demo (son)

**Files:** Yok

**Interfaces:** Yok

- [ ] **Step 1: Temiz bir DB'ye karşı gerçek KVKK sitesinden tara**

Run: `rm -f kvkk.db kvkk.db-wal kvkk.db-shm && python -m scrapers.kvkk`

- [ ] **Step 2: Her iki alt durumun da çalıştığını SQLite'ta doğrula**

Run:
```bash
sqlite3 kvkk.db "SELECT kaynak_url, length(ozet_ham), substr(ozet_ham,1,120) FROM kararlar WHERE kaynak = 'kvkk'"
```
Expected: `kvkk.gov.tr` host'lu satırların `ozet_ham`'ı "Konu Özeti"/
gerekçe metni içerir; `resmigazete.gov.tr` (PDF) host'lu satırların
`ozet_ham`'ı PDF'in gerçek metnini içerir (PDF taranmışsa/metin
katmanı yoksa o satırda başlığa düşülmüş olabilir — bu beklenen
davranış, hata değil).

- [ ] **Step 3: Uçtan uca tam pipeline'ı çalıştır (scrape + sınıflandırma)**

Run: `python backend.py --scrape`
Expected: 4 kaynak da (kvkk, bddk, spk, resmi_gazete) taranır,
`Sınıflandırma sonucu: {...}` ile biter. Hata YOK.

- [ ] **Step 4: Kullanıcıya göster, onay al**

🛑 **FAZ 3 KONTROL NOKTASI (son)** — Task 6'daki SQLite sorgusunun
çıktısını (iki alt durumun da gerçek metin ürettiğinin kanıtı) ve
`--scrape`'in temiz çalıştığını kullanıcıya göster. Onay alındıktan
sonra bu iterasyon tamamlanmış sayılır.

---

### Task 9: BDDK Ara Sertifika Güven Paketi

**Bağlam (Task 3'ün canlı doğrulaması sırasında keşfedildi):** Gerçek
`https://www.bddk.org.tr/Mevzuat/DokumanGetir/1345` isteği
`SSLCertVerificationError` ile başarısız oluyor. Kanıtlandı (`openssl
s_client -showcerts`): BDDK sunucusu TLS handshake'inde SADECE kendi
yaprak sertifikasını gönderiyor, ara sertifikayı (issuer: `GlobalSign
RSA OV SSL CA 2018`) GÖNDERMİYOR. Tarayıcılar eksik ara sertifikaları
AIA (Authority Information Access) ile otomatik indirir; Python'un
`requests`/`certifi`'si bunu YAPMAZ — sunucunun tam zinciri göndermesini
bekler. Kök sertifika (`GlobalSign Root CA - R3`) zaten `certifi`'de
güvenilir (canlı doğrulandı); eksik olan yalnızca bu TEK ara sertifika.

Ara sertifika, BDDK'nın kendi yaprak sertifikasındaki AIA "CA Issuers"
alanından (`http://secure.globalsign.com/cacert/gsrsaovsslca2018.crt`
— resmi GlobalSign deposu) indirilip doğrulandı ve DER'den PEM'e
çevrilip `scrapers/certs/globalsign_rsa_ov_ssl_ca_2018.pem` olarak
**zaten repoya eklendi** (bu planla aynı PR'da). `certifi`'nin
varsayılan paketiyle birleştirilip gerçek siteye karşı test edildi:
düzeltmeden önce `SSLError`, düzeltmeden sonra `200 OK` +
`Content-Type: application/pdf` + 136875 bayt (fixture'daki dosyayla
BİREBİR aynı boyut).

**Files:**
- Modify: `scrapers/tammetin.py`
- Modify: `tests/test_scrapers_tammetin.py`
- Sertifika (zaten mevcut): `scrapers/certs/globalsign_rsa_ov_ssl_ca_2018.pem`

**Interfaces:**
- Consumes: yok (yalnızca `requests.get` çağrılarına `verify=` parametresi
  eklenir)
- Produces: `scrapers.tammetin._guven_paketi() -> str` (birleşik CA
  paketinin dosya yolunu döner, ilk çağrıda hesaplanıp önbelleğe alınır)

- [ ] **Step 1: Başarısız testleri yaz (`tests/test_scrapers_tammetin.py`'nin
      sonuna)**

```python
def test_guven_paketi_includes_bddk_intermediate_certificate():
    yol = tammetin._guven_paketi()
    icerik = Path(yol).read_bytes()
    ara_sertifika = tammetin._BDDK_ARA_SERTIFIKA.read_bytes()
    assert ara_sertifika in icerik


def test_guven_paketi_includes_certifi_default_bundle():
    import certifi

    yol = tammetin._guven_paketi()
    icerik = Path(yol).read_bytes()
    certifi_icerik = Path(certifi.where()).read_bytes()
    assert certifi_icerik in icerik


def test_guven_paketi_is_cached_across_calls():
    ilk = tammetin._guven_paketi()
    ikinci = tammetin._guven_paketi()
    assert ilk == ikinci


def test_pdf_metni_cek_passes_guven_paketi_to_requests():
    with patch("scrapers.tammetin.requests.get", return_value=_pdf_response()) as mock_get:
        tammetin.pdf_metni_cek("https://example.com/karar.pdf")
    _, kwargs = mock_get.call_args
    assert kwargs["verify"] == tammetin._guven_paketi()


def test_kvkk_sayfa_metni_cek_passes_guven_paketi_to_requests():
    fake = Mock()
    fake.text = KVKK_DETAY_FIXTURE.read_text(encoding="utf-8")
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake) as mock_get:
        tammetin.kvkk_sayfa_metni_cek("https://www.kvkk.gov.tr/Icerik/7791/2023-2135")
    _, kwargs = mock_get.call_args
    assert kwargs["verify"] == tammetin._guven_paketi()
```

- [ ] **Step 2: Testleri çalıştır, `_guven_paketi`/`_BDDK_ARA_SERTIFIKA`
      henüz yok olduğu için başarısız olduklarını doğrula**

Run: `pytest tests/test_scrapers_tammetin.py -k "guven_paketi" -v`
Expected: FAIL — `AttributeError: module 'scrapers.tammetin' has no
attribute '_guven_paketi'`

- [ ] **Step 3: `scrapers/tammetin.py`'yi güncelle**

Import satırlarını değiştir:

```python
import io
import logging
import tempfile
from pathlib import Path

import certifi
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from scrapers.common import USER_AGENT

MAKS_PDF_BAYT = 5_000_000
MAKS_METIN_KARAKTER = 6000

_BDDK_ARA_SERTIFIKA = Path(__file__).parent / "certs" / "globalsign_rsa_ov_ssl_ca_2018.pem"
_guven_paketi_yolu: str | None = None


def _guven_paketi() -> str:
    # BDDK'nın sunucusu TLS handshake'inde ara sertifikayı (GlobalSign RSA
    # OV SSL CA 2018) GÖNDERMİYOR — tarayıcılar bunu AIA ile otomatik
    # telafi eder, requests/certifi etmez. Kök (GlobalSign Root CA - R3)
    # zaten certifi'de güvenilir; eksik olan yalnızca bu tek ara sertifika.
    # certifi.where() paketi pip güncellemesiyle güncel kalır — burada
    # dondurulan tek şey ek ara sertifika, tüm kök listesi değil.
    global _guven_paketi_yolu
    if _guven_paketi_yolu is None:
        birlesik = Path(certifi.where()).read_bytes() + b"\n" + _BDDK_ARA_SERTIFIKA.read_bytes()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as f:
            f.write(birlesik)
            _guven_paketi_yolu = f.name
    return _guven_paketi_yolu
```

`pdf_metni_cek` içindeki `requests.get` çağrısını değiştir:

```python
        response = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=timeout, verify=_guven_paketi()
        )
```

`kvkk_sayfa_metni_cek` içindeki `requests.get` çağrısını da AYNI şekilde
değiştir (üçüncü parametre olarak `verify=_guven_paketi()` eklenir).

(Fonksiyonların geri kalanı — content-type kontrolü, boyut sınırı, PDF
ayrıştırma, seçici kontrolü — AYNI kalır.)

- [ ] **Step 4: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_scrapers_tammetin.py -v`
Expected: Tüm testler PASS (10 + 5 yeni = 15)

- [ ] **Step 5: Tüm paketi çalıştır (regresyon yok)**

Run: `pytest -v`
Expected: 139/139 PASS (134 + 5 yeni)

- [ ] **Step 6: Gerçek BDDK sitesine karşı manuel doğrula**

Run:
```bash
python3 -c "
from scrapers.tammetin import pdf_metni_cek
print(pdf_metni_cek('https://www.bddk.org.tr/Mevzuat/DokumanGetir/1345'))
"
```
Expected: Gerçek karar metni konsola basılır (Karar Sayısı, Karar Tarihi,
"BLG Varlık Yönetim A.Ş.'nin faaliyet izninin ... iptal edilmesine karar
verilmiştir.") — SSL hatası YOK, `None` DEĞİL.

- [ ] **Step 7: Commit et**

```bash
git add scrapers/tammetin.py tests/test_scrapers_tammetin.py scrapers/certs/globalsign_rsa_ov_ssl_ca_2018.pem
git commit -m "fix(tammetin): trust BDDK's missing intermediate certificate"
```

(`scrapers/certs/globalsign_rsa_ov_ssl_ca_2018.pem` zaten repoda mevcutsa
— bu planla aynı PR'da eklenmiş olabilir — `git add` sessizce no-op olur.)

---

### Task 10: BDDK Liste Sayfası İçin de Güven Paketi

**Bağlam (Task 5'in canlı demosu sırasında keşfedildi):** Task 9,
BDDK'nın eksik ara sertifikasını yalnızca `scrapers/tammetin.py`'nin iki
fonksiyonu için düzeltti (`pdf_metni_cek`, `kvkk_sayfa_metni_cek`).
Ama `scrapers/bddk.py`'nin KENDİ `fetch_page()`'i — liste sayfasını
(`https://www.bddk.org.tr/Mevzuat/Liste/55`) çeken fonksiyon — de AYNI
`www.bddk.org.tr` host'una bağlanıyor ve dokunulmadığı için hâlâ
`SSLCertVerificationError` veriyor. Canlı doğrulandı: `_guven_paketi()`
ile aynı düzeltme liste sayfası için de çalışıyor (`200`, 637234 bayt).

`_guven_paketi()` artık `tammetin.py` dışından (bddk.py'den) da
çağrılacağı için, alt çizgili "private" adı yanıltıcı olur — bu task
onu **`guven_paketi()`** (alt çizgisiz, public) olarak yeniden
adlandırır. Bu, `tammetin.py` içindeki 2 kullanım yerini VE
`tests/test_scrapers_tammetin.py`'deki 9 referansı da (fonksiyon/test
adları DEĞİL, yalnızca `tammetin._guven_paketi` çağrıları) etkiler —
mantık değişmiyor, sadece isim.

**Files:**
- Modify: `scrapers/tammetin.py`
- Modify: `tests/test_scrapers_tammetin.py`
- Modify: `scrapers/bddk.py`
- Modify: `tests/test_scrapers_bddk.py`

**Interfaces:**
- Consumes: yok
- Produces: `scrapers.tammetin.guven_paketi() -> str` (Task 9'daki
  `_guven_paketi()`'nin yeniden adlandırılmış hâli — davranış AYNI)

- [ ] **Step 1: `tests/test_scrapers_tammetin.py`'de TÜM
      `tammetin._guven_paketi` referanslarını `tammetin.guven_paketi`
      ile değiştir (fonksiyon/test İSİMLERİ aynı kalır, yalnızca
      çağrılar değişir)**

Şu satırlardaki `_guven_paketi` → `guven_paketi` (alt çizgisiz):
- `test_guven_paketi_includes_bddk_intermediate_certificate` içindeki
  `tammetin._guven_paketi()` çağrısı
- `test_guven_paketi_includes_certifi_default_bundle` içindeki
  `tammetin._guven_paketi()` çağrısı
- `test_guven_paketi_is_cached_across_calls` içindeki İKİ
  `tammetin._guven_paketi()` çağrısı
- `test_pdf_metni_cek_passes_guven_paketi_to_requests` içindeki
  `tammetin._guven_paketi()` çağrısı
- `test_kvkk_sayfa_metni_cek_passes_guven_paketi_to_requests` içindeki
  `tammetin._guven_paketi()` çağrısı
- `test_pdf_metni_cek_returns_none_when_guven_paketi_raises_oserror`
  içindeki `patch("scrapers.tammetin._guven_paketi", ...)` →
  `patch("scrapers.tammetin.guven_paketi", ...)`

(Test fonksiyonlarının İSİMLERİ — `test_guven_paketi_...` gibi —
DEĞİŞMEZ; yalnızca içeride `tammetin.` üzerinden yapılan çağrılar/patch
hedefleri değişir.)

`tests/test_scrapers_bddk.py`'nin SONUNA yeni bir test ekle:

```python
def test_fetch_page_passes_guven_paketi_to_requests():
    fake_response = Mock()
    fake_response.text = "<html>ok</html>"
    fake_response.raise_for_status = Mock()
    with patch("scrapers.bddk.requests.get", return_value=fake_response) as mock_get:
        bddk.fetch_page("https://example.com/kararlar")
    _, kwargs = mock_get.call_args
    assert kwargs["verify"] == tammetin.guven_paketi()
```

(Bu test için `tests/test_scrapers_bddk.py`'nin en üstüne
`from scrapers import tammetin` import satırı eklenmesi gerekir.)

- [ ] **Step 2: Testleri çalıştır, yeni testin `AttributeError`/`KeyError`
      ile başarısız olduğunu doğrula**

Run: `pytest tests/test_scrapers_bddk.py -k fetch_page_passes -v`
Expected: FAIL — `fetch_page`'in `requests.get` çağrısında henüz
`verify` anahtarı yok (`KeyError: 'verify'`)

- [ ] **Step 3: `scrapers/tammetin.py`'de fonksiyonu yeniden adlandır**

`_guven_paketi_yolu` değişkeni ve `_guven_paketi()` fonksiyonunun TÜM
tanım ve kullanımlarında `_guven_paketi` → `guven_paketi` (alt çizgisiz)
yap: değişken adı (`_guven_paketi_yolu` → `guven_paketi_yolu`),
fonksiyon tanımı (`def _guven_paketi()` → `def guven_paketi()`),
fonksiyon içindeki `global` bildirimi, ve HER İKİ `requests.get`
çağrısındaki `verify=_guven_paketi()` → `verify=guven_paketi()`.
(Fonksiyonun gövdesi — certifi + ara sertifika birleştirme mantığı,
tempfile oluşturma — DEĞİŞMEZ, sadece isimler.)

- [ ] **Step 4: `scrapers/bddk.py`'yi güncelle**

`fetch_page` fonksiyonundaki `requests.get` çağrısını değiştir:

```python
def fetch_page(url: str = BDDK_LIST_URL, timeout: int = 15) -> str:
    response = requests.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=timeout, verify=tammetin.guven_paketi()
    )
    response.raise_for_status()
    return response.text
```

(`tammetin` importu Task 4'ten beri zaten mevcut.)

- [ ] **Step 5: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_scrapers_tammetin.py tests/test_scrapers_bddk.py -v`
Expected: Tüm testler PASS (Task 9'daki 6 test + Task 4'teki 10 test +
bu task'ın 1 yeni testi = isim değişikliği hiçbir testi bozmaz, +1 net
yeni test)

- [ ] **Step 6: Tüm paketi çalıştır (regresyon yok)**

Run: `pytest -v`
Expected: 144/144 PASS (143 + 1 yeni)

- [ ] **Step 7: Gerçek BDDK liste sayfasına karşı manuel doğrula**

Run:
```bash
python3 -c "
from scrapers.bddk import fetch_page
html = fetch_page()
print(len(html), 'bayt indirildi')
"
```
Expected: SSL hatası YOK, binlerce baytlık gerçek HTML konsola boyut
olarak basılır (liste sayfası).

- [ ] **Step 8: Commit et**

```bash
git add scrapers/tammetin.py tests/test_scrapers_tammetin.py scrapers/bddk.py tests/test_scrapers_bddk.py
git commit -m "fix(bddk): trust BDDK's certificate chain for the listing page fetch too"
```

---

## Self-Review Notları (plan yazarı tarafından, uygulayıcı için referans)

- **Kapsam kontrolü:** Spec'teki her madde bir task'a karşılık geliyor:
  `db.karar_var_mi` → Task 1, `scrapers/tammetin.py` → Task 2, altyapı
  doğrulaması → Task 3, BDDK entegrasyonu → Task 4-5, KVKK entegrasyonu
  → Task 6, dokümantasyon → Task 7, uçtan uca doğrulama → Task 8.
- **`classifier.py`'ye hiç dokunulmuyor** — spec'in temel iddiasının
  doğrudan sonucu: `build_prompt()` zaten `ozet_ham`'ı olduğu gibi
  kullanıyor, sınır scraper seviyesinde.
- **Kritik cross-task bağımlılık, plan içinde açıkça işaretlendi:**
  Task 4 ve Task 6, her ikisi de MEVCUT scraper testlerini
  güncellemeden `tammetin` çağrısı eklerse o testler gerçek ağa çıkmaya
  çalışır (BDDK: 3 test, KVKK: 2 test) — bu yüzden her iki task'ın
  Step 1'i "önce mevcut testleri güncelle" ile başlıyor, yeni davranış
  eklenmeden ÖNCE.
- **Tip/arayüz tutarlılığı:** `pdf_metni_cek` ve `kvkk_sayfa_metni_cek`
  aynı imzayı paylaşıyor (`(url: str, timeout: int = 15) -> str | None`)
  ve her ikisi de Task 4/6'da BİREBİR bu isimlerle çağrılıyor —
  drift yok.
- **Canlı doğrulama:** BDDK PDF içeriği (Content-Type, gerçek metin) ve
  KVKK detay sayfasının DOM yapısı (`div.news__detail-article`), spec
  yazımı sırasında gerçek sitelere karşı `curl`/Python ile doğrudan test
  edilip doğrulandı — placeholder/varsayım değil. Fixture'lar bu gerçek
  yanıtlardan türetildi.
- **Test sayısı takibi:** 122 (başlangıç) → 124 (Task 1) → 133 (Task 2)
  → 134 (Task 2 fix round 1: pypdf `ParseError` kapsamı) → 139 (Task 9)
  → 140 (Task 9 fix round 1: `OSError` kapsamı) → 143 (Task 4) → 144
  (Task 10) → 148 (Task 6) → 148 (Task 7, saf dokümantasyon).
- **Task 9 ve Task 10, plan sonrası eklendi:** Task 3'ün canlı
  doğrulaması BDDK'nın TLS ara sertifikasını göndermediğini ortaya
  çıkardı (kod hatası değil, hedef sunucunun yapılandırma eksikliği).
  Kullanıcı onayıyla düzeltme Task 9 olarak plana eklendi. Task 5'in
  canlı demosu sırasında AYNI sorunun `bddk.py`'nin kendi liste sayfası
  isteğini de etkilediği görüldü (Task 9 sadece `tammetin.py`'yi
  kapsıyordu) — bu da Task 10 olarak eklendi. İkisi de Faz 2'nin canlı
  demosundan (Task 5) önce tamamlanmalı, aksi halde BDDK için tam metin
  özelliği canlıda hiçbir zaman çalışmayacaktı.
