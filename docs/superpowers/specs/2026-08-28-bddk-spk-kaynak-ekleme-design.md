# BDDK ve SPK Kaynaklarının Eklenmesi — Tasarım

**Tarih**: 2026-08-28
**Durum**: Onaylandı
**Önceki spec**: `2026-08-26-kvkk-takip-design.md` (MVP — sadece KVKK)

## Amaç

MVP'de sadece KVKK Kurulu Kararları destekleniyordu. Bu iterasyonda BDDK
("Resmi Gazetede Yayımlanan Kurul Kararları") ve SPK ("Kurul Kararları ve
İlke Kararları") kaynakları aynı pipeline'a (scrape → sınıflandır →
SQLite → API → frontend) eklenir. `db.py` şeması zaten `kaynak` sütununu
genelleştirilmiş şekilde tutuyordu — bu bilinçli tasarım şimdi karşılığını
veriyor.

## Kapsam Dışı

- SPK'nın Tebliğ/Yönetmelik/Rehber/Kanun türleri (sadece Kurul Kararı +
  İlke Kararı türleri alınır)
- BDDK'nın diğer duyuru kategorileri (Basın Duyuruları, Güncel Duyurular,
  Veri Yayımlama Duyuruları vb. — çok gürültülü/genelde alakasız, sadece
  Kurul Kararları)
- Resmi Gazete kaynağı (ayrı bir sonraki iterasyon)
- Kaynak bazlı filtre UI'ı (dropdown'a "sadece BDDK göster" gibi bir seçenek
  eklenmiyor — sadece profil filtresi var, kaynaklar birleşik listede rozetle
  gösteriliyor)
- Pagination (her iki kaynak için de "en güncel 10" ile sınırlı, bu yeterli)

## Proje Yapısı

```
kvkk-takip/
├── scrapers/
│   ├── __init__.py       # boş, paket işareti
│   ├── common.py         # paylaşılan USER_AGENT sabiti
│   ├── kvkk.py           # scraper.py'den taşınmış, davranış AYNI
│   ├── bddk.py           # yeni
│   └── spk.py            # yeni
├── db.py                  # get_kararlar_by_profil artık kaynak da döner
├── classifier.py           # build_prompt kaynak-farkındalıklı
├── backend.py              # run_scrape() 3 kaynağı sırayla çalıştırır
├── index.html              # her kart üzerinde kaynak rozeti (KVKK/BDDK/SPK)
└── tests/
    └── fixtures/
        ├── kvkk_kararlari_sample.html   (mevcut)
        ├── bddk_kararlar_sample.html     (yeni, gerçek veriden)
        └── spk_kararlar_sample.json      (yeni, gerçek veriden)
```

`scraper.py` → `scrapers/kvkk.py`'ye `git mv` ile taşınır, içeriği
değişmez. `backend.py` ve `classifier.py`'deki `import scraper` satırları
`from scrapers import kvkk, bddk, spk` olur.

## Kaynak Bazlı Scraping Detayları

### `scrapers/common.py`

Sadece: `USER_AGENT = "kvkk-takip-bot/0.1"` (üç scraper da bunu kullanır).

### `scrapers/bddk.py`

- **URL**: `https://www.bddk.org.tr/Mevzuat/Liste/55` ("Resmi Gazetede
  Yayımlanan Kurul Kararları" — KVKK'nın Kurul Kararları'na birebir denk;
  canlı ve güncel, en yeni kayıt plan yazımı sırasında 06.08.2026)
- Sayfa **tek seferde 505 kayıt** döndürüyor (pagination yok, düz
  `requests.get()` ile — JS render gerekmiyor). Liste zaten tarihe göre
  yeni→eski sıralı; scraper **en güncel 10 kaydı** alır.
- Her kayıt `table.table-hover` içinde bir `<tr>`, içinde
  `a.mevzuatBaslik` (href: `/Mevzuat/DokumanGetir/ID`, göreli — `urljoin`
  ile mutlaklaştırılır). Başlık formatı: `(06.08.2026 - 11548) BLG Varlık
  Yönetim A.Ş.'nin faaliyet izninin iptal edilmesine ilişkin Kurul Kararı`
  — tarih+karar no başlığın **başında** parantez içinde.
- Tarih regex: `^\((?P<gun>\d{2})\.(?P<ay>\d{2})\.(?P<yil>\d{4}) - (?P<no>\d+)\)`
- `ozet_ham = baslik` (KVKK ile aynı desen, ayrı özet metni yok)
- Test fixture: `tests/fixtures/bddk_kararlar_sample.html` (3 gerçek kayıt,
  plan yazımı sırasında siteden çekildi)

### `scrapers/spk.py`

- **URL**: `https://mevzuat.spk.gov.tr/api/Search/All` — **düz JSON API**,
  HTML parse YOK. `requests.get(url).json()` yeterli.
- Response ~389 kayıt içerir, `tur` alanına göre filtrelenir:
  `tur in ("Kurul Kararı", "İlke Kararı")`.
- `kurulKararTarihi` alanı zaten **ISO datetime string**
  (`"2026-08-27T00:00:00"`) — regex gerekmiyor, `[:10]` ile tarih alınır.
  `tur` dışındaki türlerde bu alan `null` olabilir (örn. Tebliğ) — filtre
  zaten bunları eledikten sonra kalanlar için hep dolu.
- Filtrelenmiş liste `kurulKararTarihi`'ye göre yeni→eski sıralanır, **en
  güncel 10 kaydı** alınır.
- `baslik = item["title"]`, `ozet_ham = baslik`,
  `kaynak_url = urljoin("https://mevzuat.spk.gov.tr/", item["link"])`
- Test fixture: `tests/fixtures/spk_kararlar_sample.json` (3 gerçek kayıt:
  1 İlke Kararı, 1 Kurul Kararı, 1 Tebliğ — Tebliğ'in filtrelenip
  ELENDIĞINI test etmek için bilinçli olarak dahil edildi)

### `scrapers/kvkk.py`

Mevcut `scraper.py` içeriğiyle birebir aynı, sadece dosya konumu değişiyor.

Her üç modül de aynı arayüzü sağlar:
`scrape_and_store(conn, url=<VARSAYILAN_URL>, limit=10) -> int` (yeni
eklenen karar sayısını döner), içeride
`db.insert_karar_if_new(conn, kaynak="bddk"|"spk"|"kvkk", **karar)` çağırır.

## Sınıflandırmanın Kaynak-Farkındalıklı Hale Gelmesi

`classifier.py` değişiklikleri:

- **`KURUM_ADLARI`** sabiti eklenir:
  ```python
  KURUM_ADLARI = {
      "kvkk": "KVKK (Kişisel Verilerin Korunması Kurumu)",
      "bddk": "BDDK (Bankacılık Düzenleme ve Denetleme Kurumu)",
      "spk": "SPK (Sermaye Piyasası Kurulu)",
  }
  ```
- **`build_prompt(baslik, tarih, ozet_ham, kaynak)`** — yeni `kaynak`
  parametresi, prompt'ta "Aşağıda bir **{KURUM_ADLARI[kaynak]}** kararının
  başlığı verilmiştir" şeklinde doğru kurumu belirtir. Bu, LLM'in KVKK'ya
  özgü bağlamı (örn. "sağlık verisi işleme") BDDK/SPK kararlarına yanlış
  uygulamasını önler.
- **`KARAR_SINIFLANDIRMA_TOOL`**'un `description` alanı "Bir KVKK Kurulu
  kararını..." yerine kaynak-agnostik "Bir düzenleyici kurum kararını
  şirket profillerine göre sınıflandırır." olur.
- **`SEKTOR_ETIKETLEME_KURALI` değişmiyor** — LLM içeriğe göre karar verir,
  kaynak kurumu sadece bağlam olarak eklenir; "BDDK=her zaman finans" gibi
  sabit bir kısayol EKLENMEZ (bir BDDK/SPK kararı içeriğe göre "genel" veya
  başka bir sektöre de değebilir).
- **`db.get_pending_kararlar`** artık `kaynak` sütununu da SELECT edip
  dict'e ekler.
- **`classify_karar`** ve **`classify_pending`** imzalarına `kaynak`
  parametresi eklenir (`classify_pending` bunu `db.get_pending_kararlar`'ın
  döndürdüğü satırdan okuyup `classify_karar`'a iletir).

## DB, Backend, Frontend Değişiklikleri

- **`db.get_kararlar_by_profil`**: SELECT'e `kaynak` eklenir, dönen dict'e
  `"kaynak": row["kaynak"]` eklenir.
- **`backend.py`'nin `run_scrape()`**: Üç scraper modülünü sırayla
  çalıştırır. Bir kaynağın scrape'i başarısız olursa (örn. site erişilemez)
  diğer kaynakları ENGELLEMEZ — her kaynak kendi `try/except` bloğunda,
  hata `logging.warning` ile loglanır:
  ```python
  from scrapers import kvkk, bddk, spk

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
- **`index.html`**: Her kararın başlığının yanına küçük bir kaynak rozeti
  eklenir. Kaynak zaten sabit 3 değerden biri (`kvkk`/`bddk`/`spk`,
  scraper'ların kendi kodundan geliyor, dışarıdan/scrape edilen serbest
  metin değil) — `kaynak.toUpperCase()` ile "KVKK"/"BDDK"/"SPK" gösterilir,
  yine de tutarlılık için `esc()` ile geçirilir. Aciliyet rozetinin yanına,
  nötr gri renkte ikinci bir `<span class="kaynak-rozet">` olarak eklenir.

## Uygulama Sırası (kullanıcı onayı ile ilerlenecek)

1. **Faz 1**: `scraper.py` → `scrapers/kvkk.py`'ye taşı (davranış
   değişmeden) + `scrapers/bddk.py` yaz (TDD, fixture'a karşı) + canlı demo
   (gerçek BDDK sitesine karşı çalıştır, konsola en güncel 10 kararı bas)
   → onay bekle
2. **Faz 2**: `scrapers/spk.py` yaz (TDD, fixture'a karşı — Tebliğ türünün
   filtrelendiğini test et) + canlı demo (gerçek SPK API'sine karşı
   çalıştır) → onay bekle
3. **Faz 3**: `classifier.py` kaynak-farkındalıklı hale getir +
   `db.py`/`backend.py`/`index.html` entegrasyonu + uçtan uca canlı demo
   (3 kaynaktan gelen kararların hepsi tek sayfada, doğru rozetlerle, doğru
   sınıflandırmayla görünüyor) → onay bekle

Her adımda üretim koduna geçmeden önce çalışan bir demo gösterilecek ve bir
sonraki adıma onay alınmadan geçilmeyecek (önceki MVP fazlarındaki gibi).
