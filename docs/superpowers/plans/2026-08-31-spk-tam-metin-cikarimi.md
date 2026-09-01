# SPK Tam Metin Çıkarımı Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SPK kararlarının `ozet_ham`'ını (LLM'e giden ham girdi), keşfedilen
gizli PDF API'si üzerinden gerçek karar metniyle doldur — headless
tarayıcı olmadan, mevcut `tammetin.pdf_metni_cek()` altyapısını yeniden
kullanarak.

**Architecture:** `scrapers/spk.py`'nin arama API yanıtındaki
`contentSource`/`contentID` alanlarından `api/{contentSource}/File/{id}`
yolu üretilir; bu, `kaynak_url` olarak kullanılır (hem "Kaynağı gör"
linki hem tam metin çekimi için — BDDK/KVKK ile aynı tek-URL deseni).
`scrape_and_store`, BDDK'nın (önceki iterasyon, Task 4) desenini birebir
tekrarlar: `db.karar_var_mi` ile önce varlık kontrolü, sonra
`tammetin.pdf_metni_cek()`. `classifier.py`'ye HİÇBİR değişiklik yok.

**Tech Stack:** Mevcutla aynı. Yeni bağımlılık YOK (headless tarayıcı
gerekmiyor — SPA'nın arkasındaki düz REST API doğrudan çağrılabiliyor).

**Spec:** `docs/superpowers/specs/2026-08-31-spk-tam-metin-cikarimi-design.md`

## Global Constraints

- SPK arama API'sinin (`api/Search/All`) her kaydı `contentSource` (ör.
  `"IlkeKarari"`) ve `contentID` (ör. `377`) alanlarını taşıyor. Gerçek
  PDF `api/{contentSource}/File/{contentID}` üzerinden düz bir GET ile
  geliyor — canlı doğrulandı (iki farklı ID, iki farklı tür: "İlke
  Kararı" ve "Kurul Kararı"), kimlik doğrulama/cookie GEREKMİYOR.
- `contentSource`/`contentID` eksikse `kaynak_url` ham `link` alanına
  (SPA sayfası) düşer — sessiz bozulma yok.
- SPK'nın sertifika zinciri TAM (BDDK/Resmi Gazete'nin aksine) — canlı
  doğrulandı. `fetch_veri`'ye (arama API'si) DOKUNULMUYOR, sadece
  `pdf_metni_cek()` (zaten `guven_paketi()` kullanıyor, süperset bir
  güven paketi olduğu için SPK'ya da zararsız) yeni `kaynak_url`'lere
  karşı çağrılıyor.
- `db.karar_var_mi(conn, kaynak_url)` `insert_karar_if_new`'den ÖNCE
  çağrılır — zaten bilinen bir karar için gereksiz PDF indirmesi
  yapılmaz.
- `scrape_and_store`'un public imzası (`scrape_and_store(conn, url=SPK_API_URL, limit=10) -> int`)
  DEĞİŞMİYOR.
- `fetch_veri`, `GECERLI_TURLER`, `__main__` bloğu — hiçbiri değişmiyor.
- `classifier.py`, DB şeması, API/UI — hiçbiri değişmiyor.
- Mevcut fixture (`tests/fixtures/spk_kararlar_sample.json`) zaten
  `contentSource`/`contentID` alanlarını içeriyor — değişiklik gerekmez.

---

## Task 1: `_dosya_api_yolu` — Gizli API Yolu Üretimi

**Files:**
- Modify: `scrapers/spk.py`
- Modify: `tests/test_scrapers_spk.py`

**Interfaces:**
- Consumes: yok
- Produces: `scrapers.spk._dosya_api_yolu(item: dict) -> str | None`

- [ ] **Step 1: Başarısız testleri yaz**

`tests/test_scrapers_spk.py`'nin başına (importlardan hemen sonra,
`FIXTURE` tanımından önce ya da sonra fark etmez, dosyanın üst kısmına)
ekle:

```python
def test_dosya_api_yolu_builds_url_from_content_source_and_id():
    item = {"contentSource": "IlkeKarari", "contentID": 377}
    assert spk._dosya_api_yolu(item) == "api/IlkeKarari/File/377"


def test_dosya_api_yolu_returns_none_when_content_source_missing():
    item = {"contentID": 377}
    assert spk._dosya_api_yolu(item) is None


def test_dosya_api_yolu_returns_none_when_content_id_missing():
    item = {"contentSource": "IlkeKarari"}
    assert spk._dosya_api_yolu(item) is None
```

`test_parse_kararlar_sorts_newest_first_and_maps_fields`'daki şu satırı:

```python
    assert ilk["kaynak_url"] == "https://mevzuat.spk.gov.tr/IlkeKarari/Dosya/377"
```

şununla DEĞİŞTİR:

```python
    assert ilk["kaynak_url"] == "https://mevzuat.spk.gov.tr/api/IlkeKarari/File/377"
```

Dosyanın sonuna yeni bir test ekle:

```python
def test_parse_kararlar_falls_back_to_raw_link_when_content_fields_missing():
    veri = _fixture_veri()
    del veri[0]["contentSource"]
    kararlar = spk.parse_kararlar(veri)
    ilk = next(k for k in kararlar if "i-SPK 128.30" in k["baslik"])
    assert ilk["kaynak_url"] == "https://mevzuat.spk.gov.tr/IlkeKarari/Dosya/377"
```

- [ ] **Step 2: Testleri çalıştır, başarısız olduklarını doğrula**

Run: `pytest tests/test_scrapers_spk.py -v`
Expected: 3 yeni test `AttributeError: <module 'scrapers.spk'> does not
have the attribute '_dosya_api_yolu'` ile FAIL; güncellenen
`maps_fields` testi eski URL'i beklediği için FAIL; yeni fallback testi
de aynı `AttributeError` ile FAIL.

- [ ] **Step 3: `scrapers/spk.py`'yi güncelle**

`_dosya_api_yolu` fonksiyonunu ekle (dosyanın en üstüne, sabitlerden
hemen sonra, `parse_kararlar`'dan önce):

```python
def _dosya_api_yolu(item: dict) -> str | None:
    """SPK'nın liste API'sindeki `link` alanı bir React SPA kabuğuna gider
    (`IlkeKarari/Dosya/{id}`) — içerik JavaScript ile render ediliyor, düz
    bir HTTP GET ile ulaşılamıyor. Gerçek PDF ise sayfanın kendi arka plan
    çağrısı izlenerek bulunan `api/{contentSource}/File/{id}` üzerinden
    düz bir GET ile geliyor (canlı doğrulandı — kimlik doğrulama/cookie
    gerekmiyor, hem "İlke Kararı" hem "Kurul Kararı" türü için çalışıyor).
    contentSource/contentID eksikse None döner, çağıran ham `link`'e
    (SPA sayfası) düşer."""
    kaynak = item.get("contentSource")
    kimlik = item.get("contentID")
    if not kaynak or kimlik is None:
        return None
    return f"api/{kaynak}/File/{kimlik}"
```

`parse_kararlar` içindeki `kaynak_url` satırını değiştir:

```python
        kararlar.append({
            "baslik": baslik,
            "tarih": tarih_iso[:10],
            "kaynak_url": urljoin(base_url, _dosya_api_yolu(item) or link),
            "ozet_ham": baslik,
        })
```

(Fonksiyonun geri kalanı — tür/tarih/başlık/link kontrolü, uyarı loglama,
sıralama — AYNI kalır.)

- [ ] **Step 4: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_scrapers_spk.py -v`
Expected: Tüm testler PASS (8 mevcut + 4 yeni = 12)

- [ ] **Step 5: Tüm paketi çalıştır (regresyon yok)**

Run: `pytest -v`
Expected: 162/162 PASS (158 + 4 yeni)

- [ ] **Step 6: Commit et**

```bash
git add scrapers/spk.py tests/test_scrapers_spk.py
git commit -m "feat(spk): resolve kaynak_url to the discovered file API path"
```

---

## Task 2: `scrape_and_store` — Tam Metin Zenginleştirmesi

**Files:**
- Modify: `scrapers/spk.py`
- Modify: `tests/test_scrapers_spk.py`

**Interfaces:**
- Consumes: `scrapers.tammetin.pdf_metni_cek(url, timeout=15) -> str | None`,
  `db.karar_var_mi(conn, kaynak_url) -> bool`, `scrapers.spk._dosya_api_yolu`
  (Task 1)
- Produces: `scrapers.spk.scrape_and_store` davranış değişikliği (imza
  AYNI kalır)

**ÖNEMLİ**: `tests/test_scrapers_spk.py`'deki 3 MEVCUT test
(`test_scrape_and_store_inserts_new_kararlar`,
`test_scrape_and_store_is_idempotent`,
`test_scrape_and_store_respects_limit`) bu task'ta güncellenmezse,
`scrape_and_store` içine `tammetin.pdf_metni_cek` çağrısı eklenince
gerçek SPK sitesine (ağa) çıkmaya çalışıp yavaşlar/başarısız olur — bu
adımda hem `spk.py` hem bu 3 test birlikte güncelleniyor (BDDK'nın Task
4'ündeki ile aynı desen).

- [ ] **Step 1: Mevcut 3 testi güncelle + yeni başarısız testleri ekle**

`tests/test_scrapers_spk.py`'deki 3 mevcut testi şu üçüyle DEĞİŞTİR
(sadece `with patch(...)` bloğuna ikinci bir `patch` eklendi, gerisi
AYNI):

```python
def test_scrape_and_store_inserts_new_kararlar(conn):
    with patch("scrapers.spk.fetch_veri", return_value=_fixture_veri()), \
         patch("scrapers.spk.tammetin.pdf_metni_cek", return_value=None):
        yeni_sayisi = spk.scrape_and_store(conn)
    assert yeni_sayisi == 2  # Tebliğ elenmiş olmalı
    assert len(db.get_pending_kararlar(conn)) == 2


def test_scrape_and_store_is_idempotent(conn):
    with patch("scrapers.spk.fetch_veri", return_value=_fixture_veri()), \
         patch("scrapers.spk.tammetin.pdf_metni_cek", return_value=None):
        spk.scrape_and_store(conn)
        ikinci_calistirma = spk.scrape_and_store(conn)
    assert ikinci_calistirma == 0


def test_scrape_and_store_respects_limit(conn):
    with patch("scrapers.spk.fetch_veri", return_value=_fixture_veri()), \
         patch("scrapers.spk.tammetin.pdf_metni_cek", return_value=None):
        yeni_sayisi = spk.scrape_and_store(conn, limit=1)
    assert yeni_sayisi == 1
```

Dosyanın SONUNA yeni testleri ekle:

```python
def test_scrape_and_store_uses_full_text_when_pdf_extraction_succeeds(conn):
    with patch("scrapers.spk.fetch_veri", return_value=_fixture_veri()), \
         patch("scrapers.spk.tammetin.pdf_metni_cek", return_value="Gerçek karar metni burada."):
        spk.scrape_and_store(conn, limit=1)
    karar = db.get_pending_kararlar(conn)[0]
    assert karar["ozet_ham"] == "Gerçek karar metni burada."


def test_scrape_and_store_falls_back_to_title_when_pdf_extraction_fails(conn):
    with patch("scrapers.spk.fetch_veri", return_value=_fixture_veri()), \
         patch("scrapers.spk.tammetin.pdf_metni_cek", return_value=None):
        spk.scrape_and_store(conn, limit=1)
    karar = db.get_pending_kararlar(conn)[0]
    assert karar["ozet_ham"] == karar["baslik"]


def test_scrape_and_store_does_not_refetch_full_text_for_known_kararlar(conn):
    with patch("scrapers.spk.fetch_veri", return_value=_fixture_veri()), \
         patch("scrapers.spk.tammetin.pdf_metni_cek", return_value=None) as mock_pdf:
        spk.scrape_and_store(conn)
        ilk_cagri_sayisi = mock_pdf.call_count
        spk.scrape_and_store(conn)
        ikinci_cagri_sayisi = mock_pdf.call_count
    assert ilk_cagri_sayisi == 2  # fixture'da 2 geçerli tür var (Tebliğ elenir)
    assert ikinci_cagri_sayisi == ilk_cagri_sayisi  # ikinci koşuda yeni çağrı yok
```

- [ ] **Step 2: Testleri çalıştır, yeni 3 testin `AttributeError` ile
      başarısız olduğunu, güncellenen 3 testin (henüz `spk.py`
      değişmediği için) hâlâ PASS olduğunu doğrula**

Run: `pytest tests/test_scrapers_spk.py -v`
Expected: 9 PASS, 3 FAIL —
`AttributeError: <module 'scrapers.spk'> does not have the attribute 'tammetin'`

- [ ] **Step 3: `scrapers/spk.py`'yi güncelle**

Import satırlarını değiştir:

```python
import logging
from urllib.parse import urljoin

import requests

import db
from scrapers import tammetin
from scrapers.common import USER_AGENT
```

`scrape_and_store` fonksiyonunu değiştir:

```python
def scrape_and_store(conn, url: str = SPK_API_URL, limit: int = 10) -> int:
    veri = fetch_veri(url)
    kararlar = parse_kararlar(veri)[:limit]
    yeni_sayisi = 0
    for karar in kararlar:
        if db.karar_var_mi(conn, karar["kaynak_url"]):
            continue
        tam_metin = tammetin.pdf_metni_cek(karar["kaynak_url"])
        if tam_metin:
            karar["ozet_ham"] = tam_metin
        if db.insert_karar_if_new(conn, kaynak="spk", **karar):
            yeni_sayisi += 1
    return yeni_sayisi
```

(`_dosya_api_yolu`, `parse_kararlar`, `fetch_veri`, `__main__` bloğu
AYNI kalır.)

- [ ] **Step 4: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_scrapers_spk.py -v`
Expected: Tüm testler PASS (12/12)

- [ ] **Step 5: Tüm paketi çalıştır (regresyon yok)**

Run: `pytest -v`
Expected: 165/165 PASS (162 + 3 yeni)

- [ ] **Step 6: Commit et**

```bash
git add scrapers/spk.py tests/test_scrapers_spk.py
git commit -m "feat(spk): enrich ozet_ham with real PDF text when available"
```

---

## Task 3: Canlı Doğrulama + Dokümantasyon

**Files:**
- Modify: `README.md`

**Interfaces:** Yok

- [ ] **Step 1: Temiz bir DB'ye karşı gerçek SPK sitesinden tara**

Run: `rm -f kvkk.db kvkk.db-wal kvkk.db-shm && python -m scrapers.spk`
Expected: `N yeni SPK kararı bulundu.` çıktısı, SSL/ağ hatası YOK
(SPK'nın sertifika zinciri zaten tam, ama yine de doğrula).

- [ ] **Step 2: `ozet_ham`'ın gerçekten tam metin içerdiğini SQLite'ta
      doğrula**

Run:
```bash
sqlite3 kvkk.db "SELECT kaynak_url, length(ozet_ham), substr(ozet_ham,1,150) FROM kararlar WHERE kaynak = 'spk' LIMIT 3"
```
Expected: `kaynak_url` artık `api/.../File/...` içeriyor (SPA sayfası
DEĞİL); `ozet_ham`, karar BAŞLIĞINDAN görünüşte farklı, gerçek PDF
metninin ilk kısmı — yalnızca başlığın tekrarı DEĞİL. Tam metin
indirilemeyen bir kayıt varsa (nadiren olabilir) `ozet_ham == baslik`
olması beklenen davranıştır, hata değil.

- [ ] **Step 3: `README.md`'yi güncelle**

`README.md`'de üç ayrı paragraf var (aralarında sertifika bundle'ını
açıklayan bir paragraf daha olduğu için TEK bir blok halinde
değiştirmeye ÇALIŞMA — üçü de ayrı ayrı, aşağıdaki sırayla düzenlenir).

**Birinci paragrafı** (mevcut hâli — "BDDK ve KVKK kararları artık..."
ile başlar):
```markdown
BDDK ve KVKK kararları artık (mümkün olduğunda) gerçek karar metninden
sınıflandırılıyor — BDDK için doğrudan PDF, KVKK için (kaynağa göre)
kendi detay sayfasındaki özet veya PDF. Tam metin indirilemezse (ağ
hatası, taranmış/görsel PDF, vb.) sessizce başlığa düşülür.
```

şununla DEĞİŞTİR:

```markdown
BDDK, KVKK ve SPK kararları artık (mümkün olduğunda) gerçek karar
metninden sınıflandırılıyor — BDDK ve SPK için doğrudan PDF (SPK'nın
"Dosya" sayfası bir React SPA kabuğu, ama sayfanın kendi arka plan
çağrısı izlenerek bulunan düz bir REST API'den PDF doğrudan çekiliyor —
headless tarayıcı gerekmiyor), KVKK için (kaynağa göre) kendi detay
sayfasındaki özet veya PDF. Tam metin indirilemezse (ağ hatası,
taranmış/görsel PDF, vb.) sessizce başlığa düşülür.
```

**İkinci paragrafı** (sertifika bundle'ını açıklayan, "Bu tam metin
indirme, sertifika zincirini eksik gönderen bazı siteler..." ile
başlayan) DOKUNMA — SPK'nın sertifika zinciri zaten tam, bu paragraf
zaten sadece BDDK/Resmi Gazete'den bahsediyor ve bu doğru kalmaya devam
ediyor.

**Üçüncü paragrafı** (mevcut hâli — "SPK ve Resmi Gazete kararları
hâlâ..." ile başlar):
```markdown
SPK ve Resmi Gazete kararları hâlâ yalnızca başlıktan sınıflandırılıyor:
SPK'nın "Dosya" linki JavaScript ile render edilen bir sayfa (düz bir
HTTP isteğiyle içeriğe ulaşılamıyor); Resmi Gazete'nin linki tek bir
maddeye değil günün fihrist sayfasına gidiyor (bkz. aşağıdaki not).
```

şununla DEĞİŞTİR:

```markdown
Resmi Gazete kararları hâlâ yalnızca başlıktan sınıflandırılıyor:
linki tek bir maddeye değil günün fihrist sayfasına gidiyor (bkz.
aşağıdaki not).
```

- [ ] **Step 4: Tüm paketi çalıştır (regresyon yok)**

Run: `pytest -v`
Expected: 165/165 PASS (bu task yeni test eklemedi)

- [ ] **Step 5: Commit et**

```bash
git add README.md
git commit -m "docs: describe SPK full-text extraction via the discovered file API"
```

---

## Self-Review Notları (plan yazarı tarafından, uygulayıcı için referans)

- **Kapsam kontrolü:** Spec'teki her madde bir task'a karşılık geliyor:
  `_dosya_api_yolu` (URL çözümleme) → Task 1, tam metin entegrasyonu →
  Task 2, canlı doğrulama + dokümantasyon → Task 3.
- **`classifier.py`'ye hiç dokunulmuyor** — önceki iterasyonun (BDDK/KVKK)
  aynı mimari sınırının doğrudan devamı.
- **Tip/arayüz tutarlılığı:** `tammetin.pdf_metni_cek` BİREBİR aynı isim
  ve imzayla BDDK'daki gibi çağrılıyor — drift yok. `_dosya_api_yolu`
  yeni bir isim, mevcut hiçbir fonksiyonla çakışmıyor.
- **Kritik cross-task bağımlılık, plan içinde açıkça işaretlendi:** Task
  2, MEVCUT scraper testlerini güncellemeden `tammetin` çağrısı eklerse
  o testler gerçek ağa çıkmaya çalışır — Step 1 "önce mevcut testleri
  güncelle" ile başlıyor, yeni davranış eklenmeden ÖNCE (BDDK'nın Task
  4'ündeki ÖNEMLİ notla aynı desen).
- **Canlı doğrulama:** `api/{contentSource}/File/{id}` deseni, plan
  yazımı sırasında gerçek `mevzuat.spk.gov.tr` sitesine karşı tarayıcı
  ağ isteği incelemesi VE doğrudan `curl` ile iki farklı ID/tür için
  doğrulandı — placeholder/varsayım değil. Fixture zaten gerçek arama
  API yanıtından türetilmişti (önceki iterasyon), `contentSource`/
  `contentID` alanları orada zaten mevcuttu.
- **Test sayısı takibi:** 158 (başlangıç) → 162 (Task 1) → 165 (Task 2)
  → 165 (Task 3, saf dokümantasyon).
