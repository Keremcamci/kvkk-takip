# Resmi Gazete Tam Metin Çıkarımı Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resmi Gazete kararlarını, günün fihrist sayfasından başlık eşleştirmesiyle bulunan maddenin kendi HTML sayfasından çekilen tam metinle sınıflandırmak (şu an sadece başlıktan sınıflandırılıyorlar).

**Architecture:** `scrapers/tammetin.py`'ye yeni bir fonksiyon (`resmi_gazete_madde_metni_cek`) madde sayfasının HTML'ini Windows-1254 olarak decode edip metnini çıkarır. `scrapers/resmi_gazete.py`'ye iki yeni yardımcı fonksiyon (`_fihrist_linkleri`, `_madde_url_bul`) günün fihrist sayfasını (taramanın ömrü boyunca önbelleklenerek) çekip başlık eşleştirmesiyle madde linkini bulur. `scrape_and_store` bu ikisini BDDK/SPK'nin deseniyle birbirine bağlar.

**Tech Stack:** Python, `requests`, `BeautifulSoup` (`bs4`), `pytest` (Node.js/diğer araçlar yok — bu proje Python).

## Global Constraints

- `kaynak_url`'in değeri/şeması DEĞİŞMİYOR (spec kararı — ağa bağımlı bir migrasyon riskine girilmiyor).
- Her başarısızlık modu (ağ hatası, eşleşme bulunamaması, boş içerik) sessizce başlığa düşer — hiçbir zaman exception fırlatmaz, `logging.warning` ile loglanır (mevcut BDDK/KVKK/SPK felsefesiyle birebir).
- Madde sayfalarının (`.htm`) yanıt baytları elle `windows-1254` olarak decode edilir — `response.text`/`response.encoding`'e güvenilmez (HTTP header'da charset yok).
- Tüm yeni ağ çağrıları `tammetin.guven_paketi()` ile TLS doğrulaması yapar (mevcut desen).
- Yeni bir bağımlılık eklenmiyor (`bs4`/`requests` zaten mevcut).
- Testler gerçek ağa çıkmaz — tüm `requests.get`/`requests.post` çağrıları mock'lanır (autouse socket-block fixture zaten bunu garantiler, ama testler yine de kasıtlı mock kullanır).

---

### Task 1: Resmi Gazete madde sayfası için tam metin çıkarımı (`tammetin.py`)

**Files:**
- Modify: `scrapers/tammetin.py` (dosya sonuna yeni fonksiyon eklenir)
- Test: `tests/test_scrapers_tammetin.py` (dosya sonuna yeni testler eklenir)

**Interfaces:**
- Produces: `tammetin.resmi_gazete_madde_metni_cek(url: str, timeout: int = 15) -> str | None`

- [ ] **Step 1: Write the failing tests**

`tests/test_scrapers_tammetin.py` dosyasının sonuna ekle:

```python
def test_resmi_gazete_madde_metni_cek_extracts_and_decodes_windows1254():
    html = (
        "<html><body><div class=Section1>"
        "MADDE 1- Türkçe karakterler doğru gösterilmeli: ışığöüç"
        "</div></body></html>"
    )
    fake = Mock()
    fake.content = html.encode("windows-1254")
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake):
        metin = tammetin.resmi_gazete_madde_metni_cek(
            "https://www.resmigazete.gov.tr/eskiler/2026/09/20260901-1.htm"
        )
    assert metin is not None
    assert "ışığöüç" in metin


def test_resmi_gazete_madde_metni_cek_falls_back_to_body_when_section1_missing():
    html = "<html><body>MADDE 1- İçerik burada.</body></html>"
    fake = Mock()
    fake.content = html.encode("windows-1254")
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake):
        metin = tammetin.resmi_gazete_madde_metni_cek("https://example.com/madde.htm")
    assert metin == "MADDE 1- İçerik burada."


def test_resmi_gazete_madde_metni_cek_returns_none_on_network_error(caplog):
    with patch("scrapers.tammetin.requests.get", side_effect=ConnectionError("zaman aşımı")):
        with caplog.at_level(logging.WARNING):
            metin = tammetin.resmi_gazete_madde_metni_cek(
                "https://www.resmigazete.gov.tr/eskiler/2026/09/x.htm"
            )
    assert metin is None
    assert "indirilemedi" in caplog.text


def test_resmi_gazete_madde_metni_cek_returns_none_for_whitespace_only_content(caplog):
    # NOT: KVKK'nın "görünmez Unicode karakter" testinin eşi burada
    # uygulanamaz — bu sayfalar sabit tek baytlık windows-1254 kodlamalı
    # olduğu için U+200B gibi çok baytlı karakterleri hiç temsil edemez.
    # Windows-1254'te temsil edilebilen "boş içerik" senaryosu düz
    # boşluk/tab/newline'dır, bu test onu kapsıyor.
    html = "<html><body><div class=Section1>   \r\n\t  </div></body></html>"
    fake = Mock()
    fake.content = html.encode("windows-1254")
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake):
        with caplog.at_level(logging.WARNING):
            metin = tammetin.resmi_gazete_madde_metni_cek("https://example.com/x.htm")
    assert metin is None
    assert "bulunamadı" in caplog.text


def test_resmi_gazete_madde_metni_cek_truncates_to_max_length():
    uzun_metin = "a" * (tammetin.MAKS_METIN_KARAKTER + 500)
    html = f"<html><body><div class=Section1>{uzun_metin}</div></body></html>"
    fake = Mock()
    fake.content = html.encode("windows-1254")
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake):
        metin = tammetin.resmi_gazete_madde_metni_cek("https://example.com/x.htm")
    assert len(metin) == tammetin.MAKS_METIN_KARAKTER


def test_resmi_gazete_madde_metni_cek_passes_guven_paketi_to_requests():
    html = "<html><body><div class=Section1>MADDE 1- İçerik.</div></body></html>"
    fake = Mock()
    fake.content = html.encode("windows-1254")
    fake.raise_for_status = Mock()
    with patch("scrapers.tammetin.requests.get", return_value=fake) as mock_get:
        tammetin.resmi_gazete_madde_metni_cek("https://example.com/x.htm")
    _, kwargs = mock_get.call_args
    assert kwargs["verify"] == tammetin.guven_paketi()
```

Dosyanın başında `Mock`, `patch`, `logging` zaten import edilmiş olmalı (mevcut KVKK testleri bunları kullanıyor) — değilse dosyanın üstündeki import bloğunu kontrol et, eksikse ekle.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scrapers_tammetin.py -k resmi_gazete_madde_metni_cek -v`
Expected: FAIL with `AttributeError: module 'scrapers.tammetin' has no attribute 'resmi_gazete_madde_metni_cek'`

- [ ] **Step 3: Write the implementation**

`scrapers/tammetin.py` dosyasının sonuna ekle:

```python
def resmi_gazete_madde_metni_cek(url: str, timeout: int = 15) -> str | None:
    try:
        response = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=timeout, verify=guven_paketi()
        )
        response.raise_for_status()
    except (requests.RequestException, ConnectionError, OSError) as exc:
        logging.warning("Resmi Gazete madde sayfası indirilemedi (%s): %s", url, exc)
        return None

    # Bu .htm sayfaları eski bir "MS Word'den web sayfası olarak kaydet"
    # çıktısı ve Windows-1254 (Türkçe) kodlamalı — HTTP Content-Type
    # header'ında charset yok, sadece HTML içindeki <meta>'da beyan
    # ediliyor. response.text (requests'in kendi tahmini) bu yüzden
    # Türkçe karakterleri bozuk decode eder; bayt içeriği elle
    # windows-1254 olarak decode edilir.
    html = response.content.decode("windows-1254", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    icerik = soup.select_one("div.Section1") or soup.body
    if icerik is None:
        logging.warning("Resmi Gazete madde sayfasında beklenen içerik bulunamadı: %s", url)
        return None

    metin = icerik.get_text(separator=" ", strip=True)
    gorunmez_temizlenmis = metin.strip("​‌‍﻿ \t\n\r")
    if not gorunmez_temizlenmis:
        logging.warning(
            "Resmi Gazete madde sayfasında metin bulunamadı (görünmez/boş içerik olabilir): %s",
            url,
        )
        return None
    return metin[:MAKS_METIN_KARAKTER]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scrapers_tammetin.py -v`
Expected: PASS (tüm dosya, sadece yeni testler değil — regresyon kontrolü)

- [ ] **Step 5: Commit**

```bash
git add scrapers/tammetin.py tests/test_scrapers_tammetin.py
git commit -m "feat(tammetin): extract Resmi Gazete article text from windows-1254 htm pages"
```

---

### Task 2: Fihrist sayfasından madde linki bulma (`resmi_gazete.py`)

**Files:**
- Modify: `scrapers/resmi_gazete.py` (yeni importlar + 3 yeni fonksiyon)
- Test: `tests/test_scrapers_resmi_gazete.py` (dosya sonuna yeni testler eklenir)

**Interfaces:**
- Consumes: `tammetin.guven_paketi()` (Task 1'den önce de mevcuttu, davranışı değişmedi)
- Produces:
  - `resmi_gazete._normalize_baslik(metin: str) -> str`
  - `resmi_gazete._fihrist_linkleri(tarih: str, timeout: int = 15) -> dict[str, str]`
  - `resmi_gazete._madde_url_bul(tarih: str, konu: str, fihrist_cache: dict) -> str | None`

- [ ] **Step 1: Write the failing tests**

`tests/test_scrapers_resmi_gazete.py`'de mevcut `test_parse_kararlar_skips_record_missing_konu_instead_of_raising` testi `logging`'i modül üstünde değil, fonksiyon İÇİNDE yerel olarak import ediyor (`import logging` satırı fonksiyon gövdesinde) — aynı dosya-içi kuralı koru: `caplog` kullanan yeni testlerin (`test_fihrist_linkleri_returns_empty_dict_on_network_error`) İÇİNE, fonksiyonun ilk satırı olarak `import logging` ekle, modül üstüne EKLEME. Dosyanın sonuna ekle:

```python
FIHRIST_HTML = """
<html><body>
<div class="html-subtitle">YÖNETMELİKLER</div>
<div class="fihrist-item mb-1">
  <a href="https://www.resmigazete.gov.tr/eskiler/2026/09/20260901-1.htm" data-modal="True">
    –– İzmir Tınaztepe Üniversitesi Lisansüstü Eğitim-Öğretim Yönetmeliğinde Değişiklik Yapılmasına Dair Yönetmelik
  </a>
</div>
<div class="fihrist-item mb-1">
  <a href="https://www.resmigazete.gov.tr/eskiler/2026/09/20260901-2.htm" data-modal="True">
    –– İzmir Tınaztepe Üniversitesi Ön Lisans ve Lisans Eğitim Öğretim Yönetmeliğinde Değişiklik Yapılmasına Dair Yönetmelik
  </a>
</div>
</body></html>
"""

LISANSUSTU_BASLIK = (
    "İzmir Tınaztepe Üniversitesi Lisansüstü Eğitim-Öğretim Yönetmeliğinde "
    "Değişiklik Yapılmasına Dair Yönetmelik"
)
ON_LISANS_BASLIK = (
    "İzmir Tınaztepe Üniversitesi Ön Lisans ve Lisans Eğitim Öğretim "
    "Yönetmeliğinde Değişiklik Yapılmasına Dair Yönetmelik"
)


def test_normalize_baslik_strips_leading_dash_prefix_and_collapses_whitespace():
    assert resmi_gazete._normalize_baslik("––  İzmir   Tınaztepe\n Üniversitesi ") == \
        "İzmir Tınaztepe Üniversitesi"


def test_fihrist_linkleri_maps_normalized_title_to_href():
    fake = Mock()
    fake.text = FIHRIST_HTML
    fake.raise_for_status = Mock()
    with patch("scrapers.resmi_gazete.requests.get", return_value=fake):
        linkler = resmi_gazete._fihrist_linkleri("2026-09-01")
    assert linkler[LISANSUSTU_BASLIK] == \
        "https://www.resmigazete.gov.tr/eskiler/2026/09/20260901-1.htm"
    assert linkler[ON_LISANS_BASLIK] == \
        "https://www.resmigazete.gov.tr/eskiler/2026/09/20260901-2.htm"


def test_fihrist_linkleri_returns_empty_dict_on_network_error(caplog):
    import logging

    with patch("scrapers.resmi_gazete.requests.get", side_effect=ConnectionError("zaman aşımı")):
        with caplog.at_level(logging.WARNING):
            linkler = resmi_gazete._fihrist_linkleri("2026-09-01")
    assert linkler == {}
    assert "indirilemedi" in caplog.text


def test_fihrist_linkleri_passes_guven_paketi_to_requests():
    fake = Mock()
    fake.text = FIHRIST_HTML
    fake.raise_for_status = Mock()
    with patch("scrapers.resmi_gazete.requests.get", return_value=fake) as mock_get:
        resmi_gazete._fihrist_linkleri("2026-09-01")
    _, kwargs = mock_get.call_args
    assert kwargs["verify"] == tammetin.guven_paketi()


def test_madde_url_bul_returns_matching_href():
    fake = Mock()
    fake.text = FIHRIST_HTML
    fake.raise_for_status = Mock()
    with patch("scrapers.resmi_gazete.requests.get", return_value=fake):
        url = resmi_gazete._madde_url_bul("2026-09-01", LISANSUSTU_BASLIK, {})
    assert url == "https://www.resmigazete.gov.tr/eskiler/2026/09/20260901-1.htm"


def test_madde_url_bul_returns_none_when_no_match():
    fake = Mock()
    fake.text = FIHRIST_HTML
    fake.raise_for_status = Mock()
    with patch("scrapers.resmi_gazete.requests.get", return_value=fake):
        url = resmi_gazete._madde_url_bul("2026-09-01", "Bambaşka Bir Başlık", {})
    assert url is None


def test_madde_url_bul_uses_cache_and_fetches_fihrist_only_once():
    fake = Mock()
    fake.text = FIHRIST_HTML
    fake.raise_for_status = Mock()
    cache: dict = {}
    with patch("scrapers.resmi_gazete.requests.get", return_value=fake) as mock_get:
        resmi_gazete._madde_url_bul("2026-09-01", LISANSUSTU_BASLIK, cache)
        resmi_gazete._madde_url_bul("2026-09-01", ON_LISANS_BASLIK, cache)
    assert mock_get.call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scrapers_resmi_gazete.py -k "normalize_baslik or fihrist_linkleri or madde_url_bul" -v`
Expected: FAIL with `AttributeError: module 'scrapers.resmi_gazete' has no attribute '_normalize_baslik'` (ve benzerleri)

- [ ] **Step 3: Write the implementation**

`scrapers/resmi_gazete.py`'nin importlarına `BeautifulSoup`'u ekle (dosyanın üstünde, diğer importlarla birlikte):

```python
from bs4 import BeautifulSoup
```

Dosyanın sonuna (mevcut `scrape_and_store`'dan önce, `YURUTME_VE_IDARE` sabitinden sonraki herhangi bir yere) ekle:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scrapers_resmi_gazete.py -v`
Expected: PASS (tüm dosya)

- [ ] **Step 5: Commit**

```bash
git add scrapers/resmi_gazete.py tests/test_scrapers_resmi_gazete.py
git commit -m "feat(resmi-gazete): resolve article deep link via daily fihrist page lookup"
```

---

### Task 3: `scrape_and_store`'a bağlama, README, canlı doğrulama

**Files:**
- Modify: `scrapers/resmi_gazete.py:scrape_and_store` (bkz. Task 2'nin ürettiği `_madde_url_bul`, Task 1'in ürettiği `tammetin.resmi_gazete_madde_metni_cek`)
- Modify: `tests/test_scrapers_resmi_gazete.py` (3 mevcut test + 5 yeni test)
- Modify: `README.md`

**Interfaces:**
- Consumes: `resmi_gazete._madde_url_bul` (Task 2), `tammetin.resmi_gazete_madde_metni_cek` (Task 1)

- [ ] **Step 1: Write the failing tests**

Mevcut 3 testi (`test_scrape_and_store_inserts_new_kararlar`, `test_scrape_and_store_is_idempotent`, `test_scrape_and_store_respects_limit`) güncelle — her birine `patch("scrapers.resmi_gazete._madde_url_bul", return_value=None)` ekle (yeni ağ çağrılarını nötralize eder, mevcut davranışı korur):

```python
def test_scrape_and_store_inserts_new_kararlar(conn):
    with patch(
        "scrapers.resmi_gazete.fetch_veri", return_value=_fixture_veri()
    ), patch("scrapers.resmi_gazete._madde_url_bul", return_value=None):
        yeni_sayisi = resmi_gazete.scrape_and_store(conn)
    assert yeni_sayisi == 3
    assert len(db.get_pending_kararlar(conn)) == 3


def test_scrape_and_store_is_idempotent(conn):
    with patch(
        "scrapers.resmi_gazete.fetch_veri", return_value=_fixture_veri()
    ), patch("scrapers.resmi_gazete._madde_url_bul", return_value=None):
        resmi_gazete.scrape_and_store(conn)
        ikinci_calistirma = resmi_gazete.scrape_and_store(conn)
    assert ikinci_calistirma == 0


def test_scrape_and_store_respects_limit(conn):
    with patch(
        "scrapers.resmi_gazete.fetch_veri", return_value=_fixture_veri()
    ), patch("scrapers.resmi_gazete._madde_url_bul", return_value=None):
        yeni_sayisi = resmi_gazete.scrape_and_store(conn, limit=1)
    assert yeni_sayisi == 1
```

Dosyanın sonuna 5 yeni test ekle:

```python
def test_scrape_and_store_uses_full_text_when_madde_bulunur(conn):
    with patch(
        "scrapers.resmi_gazete.fetch_veri", return_value=_fixture_veri()
    ), patch(
        "scrapers.resmi_gazete._madde_url_bul",
        return_value="https://www.resmigazete.gov.tr/eskiler/2026/08/20260828-1.htm",
    ), patch(
        "scrapers.resmi_gazete.tammetin.resmi_gazete_madde_metni_cek",
        return_value="Gerçek madde metni burada.",
    ):
        resmi_gazete.scrape_and_store(conn, limit=1)
    karar = db.get_pending_kararlar(conn)[0]
    assert karar["ozet_ham"] == "Gerçek madde metni burada."


def test_scrape_and_store_falls_back_to_title_when_madde_bulunamaz(conn):
    with patch(
        "scrapers.resmi_gazete.fetch_veri", return_value=_fixture_veri()
    ), patch("scrapers.resmi_gazete._madde_url_bul", return_value=None):
        resmi_gazete.scrape_and_store(conn, limit=1)
    karar = db.get_pending_kararlar(conn)[0]
    assert karar["ozet_ham"] == karar["baslik"]


def test_scrape_and_store_falls_back_to_title_when_full_text_fetch_fails(conn):
    with patch(
        "scrapers.resmi_gazete.fetch_veri", return_value=_fixture_veri()
    ), patch(
        "scrapers.resmi_gazete._madde_url_bul",
        return_value="https://www.resmigazete.gov.tr/eskiler/2026/08/20260828-1.htm",
    ), patch(
        "scrapers.resmi_gazete.tammetin.resmi_gazete_madde_metni_cek", return_value=None
    ):
        resmi_gazete.scrape_and_store(conn, limit=1)
    karar = db.get_pending_kararlar(conn)[0]
    assert karar["ozet_ham"] == karar["baslik"]


def test_scrape_and_store_does_not_refetch_full_text_for_known_kararlar(conn):
    with patch(
        "scrapers.resmi_gazete.fetch_veri", return_value=_fixture_veri()
    ), patch(
        "scrapers.resmi_gazete._madde_url_bul", return_value=None
    ) as mock_madde_url_bul:
        resmi_gazete.scrape_and_store(conn)
        ilk_cagri_sayisi = mock_madde_url_bul.call_count
        resmi_gazete.scrape_and_store(conn)
        ikinci_cagri_sayisi = mock_madde_url_bul.call_count
    assert ilk_cagri_sayisi == 3  # fixture'da 3 karar var
    assert ikinci_cagri_sayisi == ilk_cagri_sayisi  # ikinci koşuda yeni çağrı yok


def test_scrape_and_store_reuses_fihrist_cache_across_same_day_kararlar(conn):
    """Fixture'daki 2026-08-29 tarihli 2 karar (Özel Hastaneler + Askeri
    Yasak Bölge) aynı taramanın ömrü boyunca fihrist_cache'i paylaşmalı
    — _fihrist_linkleri (ağ isteği) o gün için sadece BİR kez
    tetiklenmeli."""
    with patch(
        "scrapers.resmi_gazete.fetch_veri", return_value=_fixture_veri()
    ), patch(
        "scrapers.resmi_gazete._fihrist_linkleri", return_value={}
    ) as mock_fihrist_linkleri:
        resmi_gazete.scrape_and_store(conn)
    tarihler_cagrilan = [c.args[0] for c in mock_fihrist_linkleri.call_args_list]
    assert tarihler_cagrilan.count("2026-08-29") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scrapers_resmi_gazete.py -v`
Expected: Yeni 5 test FAIL olur (`scrape_and_store` henüz `_madde_url_bul`/`resmi_gazete_madde_metni_cek`'i çağırmıyor, `ozet_ham` her zaman `baslik`'in kopyası kalıyor) — güncellenmiş 3 mevcut test PASS kalmalı (henüz davranış değişmedi, sadece patch eklendi).

- [ ] **Step 3: Write the implementation**

`scrapers/resmi_gazete.py`'deki mevcut `scrape_and_store` fonksiyonunu tamamen şununla değiştir:

```python
def scrape_and_store(conn, url: str = RESMI_GAZETE_FILTER_URL, limit: int = 10) -> int:
    veri = fetch_veri(url)
    kararlar = parse_kararlar(veri)[:limit]
    fihrist_cache: dict = {}
    yeni_sayisi = 0
    for karar in kararlar:
        if db.karar_var_mi(conn, karar["kaynak_url"]):
            continue
        madde_url = _madde_url_bul(karar["tarih"], karar["baslik"], fihrist_cache)
        if madde_url:
            tam_metin = tammetin.resmi_gazete_madde_metni_cek(madde_url)
            if tam_metin:
                karar["ozet_ham"] = tam_metin
        if db.insert_karar_if_new(conn, kaynak="resmi_gazete", **karar):
            yeni_sayisi += 1
    return yeni_sayisi
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scrapers_resmi_gazete.py -v`
Expected: PASS (tüm dosya)

Sonra tüm test paketini çalıştır:

Run: `python -m pytest -q`
Expected: PASS (tüm proje, regresyon yok)

- [ ] **Step 5: README güncelle**

`README.md`'deki şu paragrafı (BDDK/KVKK/SPK tam metin çıkarımını anlatan):

```
BDDK, KVKK ve SPK kararları artık (mümkün olduğunda) gerçek karar
metninden sınıflandırılıyor — BDDK ve SPK için doğrudan PDF (SPK'nın
"Dosya" sayfası bir React SPA kabuğu, ama sayfanın kendi arka plan
çağrısı izlenerek bulunan düz bir REST API'den PDF doğrudan çekiliyor —
headless tarayıcı gerekmiyor), KVKK için (kaynağa göre) kendi detay
sayfasındaki özet veya PDF. Tam metin indirilemezse (ağ hatası,
taranmış/görsel PDF, vb.) sessizce başlığa düşülür.
```

şununla değiştir:

```
BDDK, KVKK, SPK ve Resmi Gazete kararları artık (mümkün olduğunda)
gerçek karar metninden sınıflandırılıyor — BDDK ve SPK için doğrudan
PDF (SPK'nın "Dosya" sayfası bir React SPA kabuğu, ama sayfanın kendi
arka plan çağrısı izlenerek bulunan düz bir REST API'den PDF doğrudan
çekiliyor — headless tarayıcı gerekmiyor), KVKK için (kaynağa göre) kendi
detay sayfasındaki özet veya PDF, Resmi Gazete için günün fihrist
sayfasından başlık eşleştirmesiyle bulunan maddenin kendi sayfası. Tam
metin indirilemezse (ağ hatası, eşleşme bulunamaması, taranmış/görsel
PDF, vb.) sessizce başlığa düşülür.
```

Hemen altındaki, artık YANLIŞ olan şu paragrafı (Resmi Gazete'yi hâlâ
sadece başlıktan sınıflandırılıyormuş gibi anlatan):

```
Resmi Gazete kararları hâlâ yalnızca başlıktan sınıflandırılıyor:
linki tek bir maddeye değil günün fihrist sayfasına gidiyor (bkz.
aşağıdaki not).

```

(blank satır dahil) TAMAMEN SİL — yukarıdaki güncellenmiş paragraf ve
dosyanın sonundaki mevcut not ("Not: Resmi Gazete kararlarının kaynak
linki, ilgili maddenin kendisine değil...") zaten aynı bilgiyi
(kaynak_url'in hâlâ fihrist sayfasına gittiğini) doğru şekilde
veriyor — bu paragraf artık hem yanlış hem tekrar.

Hemen altındaki (silinen paragraftan sonra gelen) şu satırı:

```
Kapsam dışı (ileriye dönük): Resmi Gazete için tam metin çıkarımı ve
sayfalama — yani her kaynağın ilk sayfasından öteye gidilmiyor.
```

şununla değiştir:

```
Kapsam dışı (ileriye dönük): Resmi Gazete için sayfalama — yani her
kaynağın ilk sayfasından öteye gidilmiyor.
```

- [ ] **Step 6: Canlı doğrulama**

Production `kvkk.db`'ye dokunmadan, izole bir geçici DB ile gerçek
Resmi Gazete kararlarını tara:

```bash
python3 -c "
import db, tempfile, os
from scrapers import resmi_gazete

fd, path = tempfile.mkstemp(suffix='.db')
os.close(fd)
conn = db.get_connection(path)
db.init_db(conn)

n = resmi_gazete.scrape_and_store(conn)
print('yeni karar sayisi:', n)

rows = conn.execute(
    \"SELECT baslik, kaynak_url, length(ozet_ham) as uzunluk, \"
    \"substr(ozet_ham,1,150) as ornek FROM kararlar WHERE kaynak='resmi_gazete' LIMIT 5\"
).fetchall()
for r in rows:
    print('---')
    print('baslik:', r['baslik'])
    print('kaynak_url:', r['kaynak_url'])
    print('ozet_ham uzunluk:', r['uzunluk'])
    print('ornek:', r['ornek'])

conn.close()
os.remove(path)
"
```

Beklenen: en az bir kararın `ozet_ham uzunluk`'u `baslik`'in uzunluğundan
belirgin şekilde büyük (gerçek madde metni geldi, sadece başlık kopyası
değil) VE `ornek`'te Türkçe karakterler (ı/ş/ğ/ö/ü/ç) bozuk
görünmüyor (windows-1254 decode doğru çalışıyor). Bazı kararların
eşleşme bulamayıp başlığa düşmesi normal (`ozet_ham uzunluk` ==
`baslik` uzunluğu) — hepsi eşleşmek zorunda değil.

- [ ] **Step 7: Commit**

```bash
git add scrapers/resmi_gazete.py tests/test_scrapers_resmi_gazete.py README.md
git commit -m "feat(resmi-gazete): enrich ozet_ham with real article text when available"
```

---

## Uygulama Sırası

Tek fazlı — her görev bağımsız test edilebilir bir teslim üretiyor ve
mimari risk düşük (yeni bir bağımlılık yok, mevcut `guven_paketi()`/
`kvkk_sayfa_metni_cek` desenlerinin bir varyasyonu). Task 1 ve Task 2
birbirinden bağımsız (paralel de yürütülebilir), Task 3 ikisine de
bağımlı. Tek bir canlı doğrulama adımı (Task 3 sonunda) yeterli.
