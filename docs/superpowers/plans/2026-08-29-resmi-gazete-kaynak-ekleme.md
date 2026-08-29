# Resmi Gazete Kaynağının Eklenmesi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **PHASE GATES ARE MANDATORY.** Bu plan 2 faza bölünmüş (scraper,
> sınıflandırma+entegrasyon). Her fazın sonunda bir
> `🛑 FAZ KONTROL NOKTASI` bloğu var. Bu planı uygulayan DURMALI,
> belirtilen demoyu kullanıcıya göstermeli ve bir sonraki faza geçmeden
> önce açık onay almalıdır.

**Goal:** Mevcut KVKK+BDDK+SPK pipeline'ına dördüncü bir kaynak ekle:
Resmi Gazete (Yürütme ve İdare bölümü).

**Architecture:** `scrapers/resmi_gazete.py`, SPK'daki gibi düz bir JSON
API'ye (`POST /Home/Filter`) karşı çalışır — HTML parse yok. Diğer üç
scraper'la aynı `scrape_and_store(conn, url=..., limit=10) -> int`
arayüzünü paylaşır. Resmi Gazete diğer kaynaklardan farklı olarak
işletmeleri hiç ilgilendirmeyen kararlar da içerdiği için `classifier.py`
"boş dizi = hiçbir profilde gösterme" kuralıyla genişletilir — bu, mevcut
`db.get_kararlar_by_profil` filtresiyle **kod değişikliği gerektirmeden**
zaten doğru çalışır.

**Tech Stack:** Mevcutla aynı — Python 3.11+, Flask, requests, anthropic,
pytest. Yeni bağımlılık YOK (JSON API, HTML parse yok).

**Spec:** `docs/superpowers/specs/2026-08-29-resmi-gazete-kaynak-ekleme-design.md`

## Global Constraints

- Resmi Gazete kaynak URL'i: `https://www.resmigazete.gov.tr/Home/Filter`
  (`POST`, `Content-Type: application/json`). Body:
  `{"draw":1,"columns":[],"order":[],"start":0,"length":50,"search":{"value":"","regex":false},"parameters":{"genelBaslangicTarihi":"<7 gün önce>","genelBitisTarihi":"<bugün>","searchtype":1,"mevzuatTuru":"2"}}`
  (`mevzuatTuru="2"` = Yürütme ve İdare). Plan yazımı sırasında `curl` ile
  doğrudan test edilip çalıştığı doğrulandı.
- Yanıttaki her kayıt: `konu` (başlık), `resmiGazeteTarihi` (ISO datetime,
  regex YOK, `[:10]` yeterli), `url` (**günün fihrist sayfasına** gider,
  tek maddeye değil — kabul edilmiş sınırlama).
- En güncel `limit` (varsayılan 10) kayıt alınır (diğer kaynaklarla
  tutarlı desen).
- `db.insert_karar_if_new(conn, kaynak="resmi_gazete", **karar)` — DB
  şemasında/`db.py`'de **hiçbir değişiklik gerekmiyor**
  (`get_kararlar_by_profil` ve `get_kaynak_sayilari` zaten `kaynak`'a göre
  tamamen genelleştirilmiş).
- `classifier.py`'nin `SEKTOR_ETIKETLEME_KURALI`'ına şu eklenir: karar
  hiçbir işletme sektörünü ilgilendirmiyorsa (hatta "genel" bile değilse)
  `sektorler` boş dizi `[]` döner. Bu, mevcut filtre mantığıyla otomatik
  uyumlu — kod değişikliği YOK, sadece prompt/tool açıklaması.
- `KURUM_ADLARI`'na `"resmi_gazete": "Resmi Gazete (T.C. Cumhurbaşkanlığı)"`
  eklenir.
- `backend.py`'nin `run_scrape()`'indeki kaynak listesine
  `("resmi_gazete", resmi_gazete)` eklenir — sıra: kvkk, bddk, spk,
  resmi_gazete. Mevcut per-source try/except mekanizması DEĞİŞMİYOR.
- `index.html`'de kaynak rozeti/özeti artık `.toUpperCase()` yerine
  fonksiyon içine gömülü bir etiket haritası (`kaynakEtiketi()`) kullanır
  — `"resmi_gazete"` → `"Resmi Gazete"` (çirkin `"RESMI_GAZETE"` yerine).
  **Önemli**: bu harita `kaynakEtiketi` fonksiyonunun İÇİNE gömülü olmalı
  (üst seviye bir `const` DEĞİL) — testler `_node_calistir` ile fonksiyon
  gövdelerini tek tek çıkarıp çalıştırıyor, üst seviye bir sabite referans
  fonksiyon dışında tanımlıysa testte `undefined` hatası verir.
- Kaynak bazlı UI filtresi (dropdown/sekme) EKLENMİYOR — sadece rozet ve
  özet satırı.
- Her fazın sonunda kullanıcıya çalışan bir demo gösterilir, onay
  alınmadan sıradaki faza geçilmez.

---

## FAZ 1: Resmi Gazete Scraper

### Task 1: `scrapers/resmi_gazete.py`

**Files:**
- Create: `scrapers/resmi_gazete.py`
- Create: `tests/test_scrapers_resmi_gazete.py`
- Fixture (zaten mevcut, plan yazımı sırasında gerçek API'den alındı):
  `tests/fixtures/resmi_gazete_kararlar_sample.json`

**Interfaces:**
- Consumes: `db.insert_karar_if_new` (mevcut), `scrapers.common.USER_AGENT`
- Produces:
  - `scrapers.resmi_gazete.RESMI_GAZETE_FILTER_URL: str`
  - `scrapers.resmi_gazete.parse_kararlar(veri: dict, base_url: str = RESMI_GAZETE_BASE_URL) -> list[dict]`
  - `scrapers.resmi_gazete.fetch_veri(url: str = RESMI_GAZETE_FILTER_URL, timeout: int = 15) -> dict`
  - `scrapers.resmi_gazete.scrape_and_store(conn, url: str = RESMI_GAZETE_FILTER_URL, limit: int = 10) -> int`

- [ ] **Step 1: Başarısız testleri yaz (`tests/test_scrapers_resmi_gazete.py`)**

```python
import json
from pathlib import Path
from unittest.mock import Mock, patch

import db
from scrapers import resmi_gazete

FIXTURE = Path(__file__).parent / "fixtures" / "resmi_gazete_kararlar_sample.json"


def _fixture_veri() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_kararlar_maps_fields_and_sorts_newest_first():
    kararlar = resmi_gazete.parse_kararlar(_fixture_veri())
    assert len(kararlar) == 3
    assert kararlar[0]["tarih"] == "2026-08-29"
    assert "Özel Hastaneler" in kararlar[0]["baslik"]
    assert kararlar[1]["tarih"] == "2026-08-29"
    assert "Askeri Yasak Bölge" in kararlar[1]["baslik"]
    assert kararlar[2]["tarih"] == "2026-08-28"
    assert "İstihdamı Koruma" in kararlar[2]["baslik"]
    assert kararlar[0]["ozet_ham"] == kararlar[0]["baslik"]


def test_parse_kararlar_builds_absolute_fihrist_url():
    kararlar = resmi_gazete.parse_kararlar(
        _fixture_veri(), base_url="https://www.resmigazete.gov.tr/"
    )
    for karar in kararlar:
        assert karar["kaynak_url"].startswith(
            "https://www.resmigazete.gov.tr/fihrist?tarih="
        )


def test_fetch_veri_posts_json_body_and_returns_parsed_response():
    fake_response = Mock()
    fake_response.json.return_value = {"data": []}
    fake_response.raise_for_status = Mock()
    with patch(
        "scrapers.resmi_gazete.requests.post", return_value=fake_response
    ) as mock_post:
        veri = resmi_gazete.fetch_veri("https://example.com/api")
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert "User-Agent" in kwargs["headers"]
    assert kwargs["json"]["parameters"]["mevzuatTuru"] == "2"
    assert kwargs["json"]["parameters"]["searchtype"] == 1
    assert veri == {"data": []}


def test_scrape_and_store_inserts_new_kararlar(conn):
    with patch(
        "scrapers.resmi_gazete.fetch_veri", return_value=_fixture_veri()
    ):
        yeni_sayisi = resmi_gazete.scrape_and_store(conn)
    assert yeni_sayisi == 3
    assert len(db.get_pending_kararlar(conn)) == 3


def test_scrape_and_store_is_idempotent(conn):
    with patch(
        "scrapers.resmi_gazete.fetch_veri", return_value=_fixture_veri()
    ):
        resmi_gazete.scrape_and_store(conn)
        ikinci_calistirma = resmi_gazete.scrape_and_store(conn)
    assert ikinci_calistirma == 0


def test_scrape_and_store_respects_limit(conn):
    with patch(
        "scrapers.resmi_gazete.fetch_veri", return_value=_fixture_veri()
    ):
        yeni_sayisi = resmi_gazete.scrape_and_store(conn, limit=1)
    assert yeni_sayisi == 1
```

- [ ] **Step 2: Testleri çalıştır, `scrapers.resmi_gazete` modülü olmadığı
      için başarısız olduğunu doğrula**

Run: `pytest tests/test_scrapers_resmi_gazete.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapers.resmi_gazete'`

- [ ] **Step 3: `scrapers/resmi_gazete.py`'yi yaz**

```python
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
        kararlar.append({
            "baslik": baslik,
            "tarih": tarih_iso[:10],
            "kaynak_url": urljoin(base_url, item["url"]),
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
```

- [ ] **Step 4: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_scrapers_resmi_gazete.py -v`
Expected: 6 test PASS

- [ ] **Step 5: Tüm paketi çalıştır (regresyon yok)**

Run: `pytest -v`
Expected: 94/94 PASS (88 mevcut + 6 yeni)

- [ ] **Step 6: Commit et**

```bash
git add scrapers/resmi_gazete.py tests/test_scrapers_resmi_gazete.py tests/fixtures/resmi_gazete_kararlar_sample.json
git commit -m "feat(scrapers): add Resmi Gazete scraper (Yürütme ve İdare, JSON API)"
```

(`tests/fixtures/resmi_gazete_kararlar_sample.json` zaten repoda mevcutsa
— spec commit'inde eklenmiş olabilir — `git add` sessizce no-op olur.)

---

### Task 2: Faz 1 Canlı Demo

**Files:** Yok

**Interfaces:** Yok

- [ ] **Step 1: Gerçek Resmi Gazete API'sine karşı çalıştır**

Run: `python -m scrapers.resmi_gazete` (repo kökünden, venv aktifken)
Expected: `N yeni Resmi Gazete kararı bulundu.` çıktısı + en güncel 10
kararın tarih+başlık listesi (Yürütme ve İdare bölümüne ait
yönetmelik/tebliğ/CB kararı/kurul kararı türünde başlıklar).

- [ ] **Step 2: SQLite'ta doğrula**

Run: `sqlite3 kvkk.db "SELECT kaynak, count(*) FROM kararlar GROUP BY kaynak"`
Expected: `kvkk`/`bddk`/`spk` (varsa) yanında bir de `resmi_gazete` satırı.

- [ ] **Step 3: Kullanıcıya göster, onay al**

🛑 **FAZ 1 KONTROL NOKTASI** — Konsol çıktısını ve DB durumunu kullanıcıya
göster. Kullanıcı onaylamadan **Faz 2'ye (Task 3) geçme.**

---

## FAZ 2: Sınıflandırma ve Entegrasyon

### Task 3: `classifier.py` — Boş Dizi Kuralı ve Kurum Adı

**Files:**
- Modify: `classifier.py`
- Modify: `tests/test_classifier.py`

**Interfaces:**
- Consumes: yok (mevcut `classify_karar`/`classify_pending`/`build_prompt`
  imzaları DEĞİŞMİYOR — bu task sadece sabit metinleri günceller)
- Produces: `classifier.KURUM_ADLARI` sözlüğüne yeni bir anahtar eklenir
  (`"resmi_gazete"`); `classifier.SEKTOR_ETIKETLEME_KURALI` metni genişler.
  Fonksiyon imzaları ve davranışları (retry/backoff, hata yönetimi) AYNI
  kalır.

- [ ] **Step 1: Başarısız testleri yaz (`tests/test_classifier.py`'nin
      sonuna)**

```python
def test_kurum_adlari_includes_resmi_gazete():
    prompt = classifier.build_prompt(
        "Başlık", "2026-01-01", "özet", kaynak="resmi_gazete"
    )
    assert "Resmi Gazete (T.C. Cumhurbaşkanlığı)" in prompt


def test_sektor_etiketleme_kurali_allows_empty_array_for_irrelevant_kararlar():
    aciklama = classifier.KARAR_SINIFLANDIRMA_TOOL["input_schema"]["properties"]["sektorler"]["description"]
    assert classifier.SEKTOR_ETIKETLEME_KURALI in aciklama
    assert "boş dizi" in classifier.SEKTOR_ETIKETLEME_KURALI
    assert "[]" in classifier.SEKTOR_ETIKETLEME_KURALI


def test_classify_pending_stores_empty_sektorler_and_excludes_from_all_profiles(conn):
    db.insert_karar_if_new(
        conn, kaynak="resmi_gazete", baslik="Askeri Yasak Bölge Kararı",
        tarih="2026-01-01", kaynak_url="https://example.com/rg1", ozet_ham="x",
    )
    bos_dizi_input = dict(SUCCESS_INPUT)
    bos_dizi_input["sektorler"] = []
    client = FakeClient([FakeResponse([FakeToolUseBlock("karar_sinifla", bos_dizi_input)])])
    sonuc = classifier.classify_pending(conn, client=client, model="model", sleep_fn=lambda s: None)
    assert sonuc == {"basarili": 1, "basarisiz": 0, "kalici_hata": 0}
    for profil in ["genel", "e-ticaret", "finans", "saglik", "egitim"]:
        assert db.get_kararlar_by_profil(conn, profil) == []
```

(`SUCCESS_INPUT`, `FakeClient`, `FakeResponse`, `FakeToolUseBlock` bu
dosyada zaten tanımlı, aynen kullanılıyor.)

- [ ] **Step 2: Testleri çalıştır, başarısız olduklarını doğrula**

Run: `pytest tests/test_classifier.py -k "resmi_gazete or bos_dizi or empty" -v`
Expected: FAIL — ilk test "Resmi Gazete" metnini prompt'ta bulamaz, ikinci
test `SEKTOR_ETIKETLEME_KURALI` içinde `"boş dizi"`/`"[]"` bulamaz.

- [ ] **Step 3: `classifier.py`'yi güncelle**

`KURUM_ADLARI` sözlüğüne ekle (mevcut 3 satırın yanına):

```python
    "resmi_gazete": "Resmi Gazete (T.C. Cumhurbaşkanlığı)",
```

`SEKTOR_ETIKETLEME_KURALI`'yı şununla değiştir (mevcut metnin SONUNA yeni
bir cümle eklendi, öncesi AYNI kalıyor):

```python
SEKTOR_ETIKETLEME_KURALI = (
    '"genel" etiketini SADECE karar dört sektörün hepsini '
    "(e-ticaret, finans, sağlık, eğitim) eşit ölçüde ve aynı şekilde "
    "ilgilendiriyorsa kullan. Karar belirli bir veya birkaç sektöre daha çok "
    "uyuyorsa (örn. özel nitelikli/sağlık verisi işleyenler, çevrimiçi satış "
    "yapanlar, kredi ve ödeme kuruluşları, öğrenci verisi tutan kurumlar) "
    'yalnızca o sektör(ler)i etiketle, "genel" EKLEME. "genel" nadiren doğru '
    "cevaptır; kararların çoğu aslında belirli sektörleri ilgilendirir. Emin "
    'değilsen "genel" yerine en uygun spesifik sektörü seç. "genel" diğer '
    'etiketlerle birlikte kullanılmaz: ya yalnızca "genel", ya bir veya daha '
    "fazla spesifik sektör. Karar HİÇBİR işletme sektörünü (e-ticaret, "
    'finans, sağlık, eğitim), hatta "genel" bile ilgilendirmiyorsa (örn. '
    "askeri bölge ilanı, diplomatik vize muafiyeti, kamu kurumu iç "
    'organizasyon kararı) "sektorler" alanını boş dizi ([]) olarak döndür.'
)
```

- [ ] **Step 4: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_classifier.py -v`
Expected: Tüm testler PASS (eski + 3 yeni)

- [ ] **Step 5: Tüm paketi çalıştır (regresyon yok)**

Run: `pytest -v`
Expected: 97/97 PASS (94 + 3 yeni)

- [ ] **Step 6: Commit et**

```bash
git add classifier.py tests/test_classifier.py
git commit -m "feat(classifier): allow empty sektorler for kararlar irrelevant to any business"
```

---

### Task 4: `backend.py` — Çoklu-Kaynak Döngüsüne Resmi Gazete Ekleme

**Files:**
- Modify: `backend.py`
- Modify: `tests/test_backend.py`

**Interfaces:**
- Consumes: `scrapers.resmi_gazete.scrape_and_store` (Task 1'de üretildi)
- Produces: `backend.resmi_gazete` modül referansı (testlerin
  `monkeypatch.setattr(backend.resmi_gazete, "scrape_and_store", ...)` ile
  eriştiği isim)

**ÖNEMLİ**: `tests/test_backend.py`'de zaten `backend.kvkk`/`backend.bddk`/
`backend.spk`'yi monkeypatch eden 3 mevcut test var
(`test_run_scrape_continues_when_one_source_fails`,
`test_run_scrape_logs_warning_for_failed_source`,
`test_run_scrape_logs_traceback_for_failed_source`). Bu task'ta
`run_scrape()`'e `resmi_gazete` eklenince bu 3 test de güncellenmezse,
gerçek Resmi Gazete API'sine (ağa) çıkmaya çalışıp yavaşlar/başarısız
olur — bu adımda İKİSİ DE (backend.py VE bu 3 test) birlikte
güncelleniyor.

- [ ] **Step 1: Mevcut 3 testi güncelle (başarısız hale gelmelerini
      bekliyoruz — henüz `backend.resmi_gazete` yok)**

`tests/test_backend.py`'de `test_run_scrape_continues_when_one_source_fails`'i
şununla değiştir:

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
        backend.resmi_gazete, "scrape_and_store",
        lambda conn: calls.append("resmi_gazete") or 3,
    )
    monkeypatch.setattr(
        backend.classifier, "classify_pending",
        lambda conn: {"basarili": 0, "basarisiz": 0, "kalici_hata": 0},
    )

    backend.run_scrape()

    assert calls == ["kvkk", "spk", "resmi_gazete"]
    cikti = capsys.readouterr().out
    assert "kvkk: 1 yeni karar" in cikti
    assert "spk: 2 yeni karar" in cikti
    assert "resmi_gazete: 3 yeni karar" in cikti
    # bddk başarısız olduğu için "bddk: ... yeni karar" satırı YOK — bu
    # kaynağın hatası, print edilen özet çıktısına hiç girmemeli.
    assert "bddk:" not in cikti
```

`test_run_scrape_logs_warning_for_failed_source`'a
`monkeypatch.setattr(backend.spk, "scrape_and_store", lambda conn: 0)`
satırından HEMEN SONRA şunu ekle:

```python
    monkeypatch.setattr(backend.resmi_gazete, "scrape_and_store", lambda conn: 0)
```

`test_run_scrape_logs_traceback_for_failed_source`'a
`monkeypatch.setattr(backend.bddk, "scrape_and_store", lambda conn: 0)`
satırından HEMEN SONRA şunu ekle:

```python
    monkeypatch.setattr(backend.resmi_gazete, "scrape_and_store", lambda conn: 0)
```

- [ ] **Step 2: Testleri çalıştır, `backend.resmi_gazete` olmadığı için
      başarısız olduklarını doğrula**

Run: `pytest tests/test_backend.py -k run_scrape -v`
Expected: FAIL — `AttributeError: module 'backend' has no attribute 'resmi_gazete'`

- [ ] **Step 3: `backend.py`'yi güncelle**

Import satırını değiştir:

```python
from scrapers import bddk, kvkk, resmi_gazete, spk
```

`run_scrape()`'in içindeki döngü listesini değiştir:

```python
        for isim, modul in [("kvkk", kvkk), ("bddk", bddk), ("spk", spk), ("resmi_gazete", resmi_gazete)]:
```

(Fonksiyonun geri kalanı — `try/except`, `logging.warning(..., exc_info=True)`,
`classifier.classify_pending(conn)` çağrısı — AYNI kalır.)

- [ ] **Step 4: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_backend.py -v`
Expected: Tüm testler PASS

- [ ] **Step 5: Tüm paketi çalıştır (regresyon yok)**

Run: `pytest -v`
Expected: 97/97 PASS (Task 3'teki sayıyla aynı — bu task yeni test
eklemiyor, mevcut 3 testi günceliyor)

- [ ] **Step 6: Commit et**

```bash
git add backend.py tests/test_backend.py
git commit -m "feat(web): include resmi_gazete in multi-source run_scrape loop"
```

---

### Task 5: `index.html` + `README.md` — Kaynak Etiketi ve Dokümantasyon

**Files:**
- Modify: `index.html`
- Modify: `tests/test_frontend.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: yok (saf frontend + dokümantasyon değişikliği)
- Produces: `kaynakEtiketi(k: string) -> string` (yeni JS fonksiyonu,
  `kararKart` ve `kaynakOzetMetni` tarafından kullanılıyor)

**ÖNEMLİ**: `tests/test_frontend.py`'de `_node_calistir` ile `kararKart`'ı
çalıştıran 5 MEVCUT test var
(`test_kararKart_quote_in_aciliyet_aciklama_does_not_inject_attribute`,
`test_kararKart_omits_link_for_javascript_scheme_url`,
`test_kararKart_renders_link_for_http_and_https_urls`,
`test_kararKart_renders_kaynak_rozeti`,
`test_kararKart_omits_kaynak_rozeti_when_kaynak_missing`) — hepsi
fonksiyon listesinde `["esc", "escAttr", "guvenliUrl", "kararKart"]`
kullanıyor. `kararKart` artık `kaynakEtiketi()`'i çağıracağı için, bu 5
listenin HEPSİNE `"kaynakEtiketi"` eklenmezse (node script'inde
`kaynakEtiketi` fonksiyonu tanımsız kalacağından)
`ReferenceError: kaynakEtiketi is not defined` ile başarısız olurlar.

- [ ] **Step 1: 5 mevcut testin fonksiyon listesini güncelle**

`tests/test_frontend.py`'de aşağıdaki 5 satırın HER BİRİNDE
`["esc", "escAttr", "guvenliUrl", "kararKart"]` listesini
`["esc", "escAttr", "guvenliUrl", "kaynakEtiketi", "kararKart"]` ile
değiştir (metnin geri kalanı — test gövdeleri, assertion'lar — AYNI
kalır):

- `test_kararKart_quote_in_aciliyet_aciklama_does_not_inject_attribute`
- `test_kararKart_omits_link_for_javascript_scheme_url`
- `test_kararKart_renders_link_for_http_and_https_urls`
- `test_kararKart_renders_kaynak_rozeti`
- `test_kararKart_omits_kaynak_rozeti_when_kaynak_missing`

- [ ] **Step 2: Yeni başarısız testleri ekle (`tests/test_frontend.py`'nin
      sonuna)**

```python
@node_gerekli
def test_kararKart_renders_resmi_gazete_label_not_raw_uppercase():
    karar = {
        "baslik": "Karar",
        "tarih": "2026-01-01",
        "ozet": "özet",
        "yapilmasi_gerekenler": [],
        "aciliyet_var": False,
        "aciliyet_aciklama": "",
        "kaynak_url": "https://example.com/1",
        "kaynak": "resmi_gazete",
    }
    (html,) = _node_calistir(
        ["esc", "escAttr", "guvenliUrl", "kaynakEtiketi", "kararKart"],
        f"[kararKart({json.dumps(karar)})]",
    )
    span = BeautifulSoup(html, "html.parser").select_one("span.kaynak-rozet")
    assert span is not None
    assert span.get_text(strip=True) == "Resmi Gazete"


@node_gerekli
def test_kaynakOzetMetni_includes_resmi_gazete_in_fixed_order():
    (metin,) = _node_calistir(
        ["kaynakOzetMetni", "kaynakEtiketi"],
        '[kaynakOzetMetni({"resmi_gazete": 5, "bddk": 10, "kvkk": 8, "spk": 10})]',
    )
    assert metin == "Toplam: 8 KVKK, 10 BDDK, 10 SPK, 5 Resmi Gazete karar takip ediliyor."
```

- [ ] **Step 3: Testleri çalıştır, başarısız olduklarını doğrula**

Run: `pytest tests/test_frontend.py -v`
Expected: `kaynakEtiketi` henüz tanımlı olmadığı için hem güncellenen 5
eski test hem 2 yeni test `node` hata kodu ile FAIL (`ReferenceError:
kaynakEtiketi is not defined`) — `node` kurulu değilse bu testler zaten
`skip` edilir, o durumda bu adımı atla ve Step 5'e geç.

- [ ] **Step 4: `index.html`'i güncelle**

`kararKart` fonksiyonundan HEMEN ÖNCE yeni bir fonksiyon ekle:

```javascript
    // Harita fonksiyon İÇİNE gömülü: _node_calistir testleri fonksiyon
    // gövdelerini tek tek çıkarıp çalıştırıyor, üst seviye bir sabite
    // (const) referans fonksiyon dışında tanımlıysa testte "undefined"
    // hatası verir.
    function kaynakEtiketi(k) {
      const etiketler = { kvkk: "KVKK", bddk: "BDDK", spk: "SPK", resmi_gazete: "Resmi Gazete" };
      return etiketler[k] || String(k).toUpperCase();
    }
```

`kararKart` fonksiyonundaki `kaynakRozetiHtml` satırını değiştir:

```javascript
      const kaynakRozetiHtml = karar.kaynak
        ? `<span class="kaynak-rozet">${esc(kaynakEtiketi(karar.kaynak))}</span>`
        : "";
```

`kaynakOzetMetni` fonksiyonundaki iki satırı değiştir — `bilinenSira`:

```javascript
      const bilinenSira = ["kvkk", "bddk", "spk", "resmi_gazete"];
```

ve `.map(...)` satırı:

```javascript
        .map((k) => `${sayilar[k]} ${kaynakEtiketi(k)}`);
```

(Fonksiyonların geri kalanı — `digerleri` hesaplaması, boş durum kontrolü,
`parcalar.join(", ")` — AYNI kalır.)

- [ ] **Step 5: Testleri çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_frontend.py -v`
Expected: Tüm testler PASS (eski + 2 yeni)

- [ ] **Step 6: `README.md`'yi güncelle**

Üstteki tanıtım cümlesini değiştir:

```
Türkiye'deki KOBİ'ler için KVKK, BDDK, SPK ve Resmi Gazete kararlarını
otomatik tarayıp,
```

Kapsam bölümündeki giriş cümlesini ve tabloyu değiştir:

```markdown
Dört kaynak destekleniyor; her birinden en güncel ~10 karar taranır (liste
sayfasının/API yanıtının ilk sayfası):

| Kaynak        | Ne taranıyor                                          |
| ------------- | ------------------------------------------------------ |
| KVKK          | Kurul Kararları                                        |
| BDDK          | Kurul Kararları                                        |
| SPK           | Kurul Kararları / İlke Kararları                       |
| Resmi Gazete  | Yürütme ve İdare bölümü (yönetmelik/tebliğ/CB kararı/kurul kararı) |
```

"Kapsam dışı" satırını değiştir (Resmi Gazete artık kapsamda, listeden
çıkar):

```markdown
Kapsam dışı (ileriye dönük): PDF tam metin çıkarımı (yalnızca liste
sayfasındaki başlık kullanılıyor) ve sayfalama — yani her kaynağın ilk
sayfasından öteye gidilmiyor.
```

"Not:" paragrafının hemen altına yeni bir not ekle:

```markdown
Not: Resmi Gazete kararlarının kaynak linki, ilgili maddenin kendisine
değil o günün resmi fihrist (içindekiler) sayfasına gider — yine de resmi
ve doğru bir kaynak, sadece tek maddeye değil günün tümüne işaret eder.
```

- [ ] **Step 7: Tüm paketi çalıştır (regresyon yok)**

Run: `pytest -v`
Expected: 99/99 PASS (97 + 2 yeni frontend testi; Task 4 yeni test
eklemedi)

- [ ] **Step 8: Commit et**

```bash
git add index.html tests/test_frontend.py README.md
git commit -m "feat(web): clean kaynak labels for Resmi Gazete, update docs"
```

---

### Task 6: Faz 2 Uçtan Uca Canlı Demo

**Files:** Yok

**Interfaces:** Yok

- [ ] **Step 1: Temiz baştan uçtan uca çalıştır (4 kaynak birden)**

Run: `rm -f kvkk.db && python backend.py --scrape`
Expected: Konsolda dört ayrı satır (`kvkk: ...`, `bddk: ...`, `spk: ...`,
`resmi_gazete: ...`), ardından `Sınıflandırma sonucu: {...}`.

- [ ] **Step 2: SQLite'ta doğrula — boş dizi kuralının gerçekten çalıştığını
      kontrol et**

Run: `sqlite3 kvkk.db "SELECT kaynak, sektorler FROM kararlar WHERE kaynak = 'resmi_gazete'"`
Expected: En az bir satırda `sektorler` değeri `[]` (tamamen alakasız bir
karar, örn. askeri bölge ilanı, kamu kurumu iç kararı vb.) — LLM'in gerçek
veride de "boş dizi" kuralını uyguladığını doğrular. (Eğer bu haftaki
gerçek Resmi Gazete içeriğinde hiç böyle bir karar yoksa, en azından hiçbir
satırın YANLIŞLIKLA zorla bir sektöre yapıştırılmadığını gözle kontrol et.)

- [ ] **Step 3: Web sunucusunu başlat, tarayıcıda doğrula**

Run: `python backend.py`
`http://localhost:5001` adresini aç. "Resmi Gazete" rozetli kartların
doğru göründüğünü, kaynak özeti satırının dördüncü kaynağı da
("... , N Resmi Gazete karar takip ediliyor.") doğru sırada gösterdiğini,
alakasız (boş dizi) kararların HİÇBİR profilde görünmediğini doğrula.

- [ ] **Step 4: Kullanıcıya göster, onay al**

🛑 **FAZ 2 KONTROL NOKTASI (son)** — Tarayıcıda çalışan uygulamayı (4
kaynak, rozetler, kaynak özeti, boş-dizi filtrelemesi) kullanıcıya göster.
Onay alındıktan sonra bu iterasyon tamamlanmış sayılır.

---

## Self-Review Notları (plan yazarı tarafından, uygulayıcı için referans)

- **Kapsam kontrolü:** Spec'teki her madde bir task'a karşılık geliyor:
  scraper + canlı doğrulama → Task 1-2, boş dizi kuralı → Task 3,
  backend entegrasyonu → Task 4, frontend/dokümantasyon → Task 5, uçtan
  uca doğrulama → Task 6.
- **`db.py`'ye hiç dokunulmuyor** — `get_kararlar_by_profil` ve
  `get_kaynak_sayilari` zaten `kaynak` sütununa göre tam genelleştirilmiş
  (`GROUP BY kaynak`, sabit bir kaynak listesi yok). Bu, önceki
  iterasyonun (BDDK/SPK) bilinçli tasarım kararının doğrudan faydası.
- **Tip/arayüz tutarlılığı:** Dört scraper modülü de birebir aynı
  `scrape_and_store(conn, url=..., limit=10) -> int` imzasını paylaşıyor
  (kvkk.py hariç — Task 1 MVP planından beri `limit` parametresi yok, bu
  bilinen ve kabul edilmiş bir asimetri). `classify_pending`'in imzası bu
  planda HİÇ değişmiyor — sadece `SEKTOR_ETIKETLEME_KURALI`'nın metni
  genişliyor.
- **Kritik cross-task bağımlılık, plan içinde açıkça işaretlendi:** Task 4
  (backend.py) ve Task 5 (index.html), her ikisi de MEVCUT testleri
  güncellemeden yeni kod eklerse o testler ya gerçek ağa çıkar (Task 4) ya
  da `ReferenceError` ile patlar (Task 5) — bu yüzden her iki task'ın
  Step 1'i "önce mevcut testleri güncelle" ile başlıyor, yeni davranış
  eklenmeden ÖNCE.
- **Canlı doğrulama:** Task 1'deki `/Home/Filter` istek/yanıt formatı ve
  fixture, plan yazımı sırasında gerçek `https://www.resmigazete.gov.tr/`
  sitesinin kendi JS'i incelenerek ve `curl` ile doğrudan test edilerek
  doğrulandı — placeholder/varsayım değil.
