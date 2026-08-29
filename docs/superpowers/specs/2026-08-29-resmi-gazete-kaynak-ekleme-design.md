# Resmi Gazete Kaynağının Eklenmesi — Tasarım

**Tarih**: 2026-08-29
**Durum**: Onaylandı
**Önceki spec**: `2026-08-28-bddk-spk-kaynak-ekleme-design.md` (BDDK + SPK)

## Amaç

KVKK + BDDK + SPK üçlüsüne dördüncü bir kaynak eklenir: **Resmi Gazete**
(T.C. Cumhurbaşkanlığı'nın günlük resmi yayın organı). Diğer üç kaynaktan
farklı olarak Resmi Gazete tek bir kurumun kararları değil, devletin günlük
tüm yayınlarını (kanun, yönetmelik, tebliğ, Cumhurbaşkanı kararı, çeşitli
kurul kararları) içerir — bu yüzden hem kapsam daraltması hem sınıflandırma
kuralında bir ek gerektiriyor (aşağıda).

## Kapsam Dışı

- Yasama (kanunlar) ve Yargı (mahkeme kararları) bölümleri — sadece
  **Yürütme ve İdare** kategorisi (yönetmelik/tebliğ/CB kararları/kurul
  kararları) alınır.
- İlan Bölümü (ihale/çeşitli ilanlar) — zaten `/Home/Filter` API'sinin
  kategori seçeneklerinde yok, kapsam dışı kalması otomatik.
- Mükerrer (tekrar yayımlanan) sayılar, pagination (son 1 hafta + en
  güncel `limit` kaydı yeterli — diğer kaynaklarla tutarlı).
- Kaynak bazlı UI filtresi — önceki iterasyonlardaki kural devam ediyor,
  sadece rozet + özet sayacı.

## Kaynak Yapısı

**Kaynak**: `POST https://www.resmigazete.gov.tr/Home/Filter`

Bu, sitenin ana sayfasındaki "Tüm Kategoriler" / "Zaman Aralığı"
dropdown'larının arkasındaki gerçek JSON API'si — sitenin kendi JS'i
incelenerek (`$("#selectTarihAraligi, #selectMevzuatTuru").on("change", ...)`
handler'ı) bulundu ve plan yazımı sırasında `curl` ile doğrudan test edilip
çalıştığı doğrulandı.

**İstek** (`Content-Type: application/json`):

```json
{
  "draw": 1,
  "columns": [],
  "order": [],
  "start": 0,
  "length": 50,
  "search": { "value": "", "regex": false },
  "parameters": {
    "genelBaslangicTarihi": "<bugünden 7 gün önce, YYYY-MM-DD>",
    "genelBitisTarihi": "<bugün, YYYY-MM-DD>",
    "searchtype": 1,
    "mevzuatTuru": "2"
  }
}
```

`mevzuatTuru` değerleri: `""` = Tüm Kategoriler, `"1"` = Yasama,
`"2"` = **Yürütme ve İdare** (bizim kullandığımız), `"3"` = Yargı.

**Yanıt**:

```json
{
  "draw": 1,
  "recordsTotal": 44,
  "recordsFiltered": 44,
  "data": [
    {
      "konu": "...",
      "mevzuatAdi": "YÖNETMELİKLER",
      "resmiGazeteSayisi": 33354,
      "kanunKararNo": "",
      "resmiGazeteTarihi": "2026-08-28T00:00:00",
      "mukerrer": "HAYIR",
      "url": "/fihrist?tarih=2026-08-28",
      "resmiGazeteTarihiFormatted": "28.08.2026"
    }
  ]
}
```

- `baslik = konu`
- `tarih = resmiGazeteTarihi[:10]` (zaten ISO datetime string, regex yok —
  SPK ile aynı desen)
- `kaynak_url = urljoin(base_url, url)` — **önemli sınırlama**: `url` alanı
  ilgili maddenin kendi sayfasına değil, **o günün fihrist (içindekiler)
  sayfasına** gidiyor (örn. `/fihrist?tarih=2026-08-28`). Aynı günün birden
  fazla maddesi aynı `kaynak_url`'i paylaşabilir. Bu, kullanıcı onayıyla
  kabul edilmiş bir sınırlama — hâlâ resmi ve doğru bir kaynağa işaret
  ediyor, sadece tek maddeye değil günün tümüne.
- `ozet_ham = baslik` (diğer kaynaklarla aynı desen, ayrı özet metni yok)
- En güncel `limit` (varsayılan 10) kayıt alınır (liste zaten
  `resmiGazeteTarihi`'ye göre sıralı geliyor, garanti için scraper kendi
  içinde de yeni→eski sıralar).

Test fixture: `tests/fixtures/resmi_gazete_kararlar_sample.json` (plan
yazımı sırasında gerçek API'den gözlemlenen 3 kayıt: 2 işletme-ilgili
yönetmelik + 1 tamamen alakasız Cumhurbaşkanı kararı — bu üçüncüsü
aşağıdaki "boş dizi" kuralının test edilmesi için bilinçli dahil edildi,
ama fixture SADECE scraper'ın parse mantığını test eder; "boş dizi" kararı
LLM'in kendi yargısı olduğu için sınıflandırıcı testlerinde ayrı, sahte bir
client ile test edilir).

## Sınıflandırmada Yeni Davranış: "Boş Dizi" Kuralı

KVKK/BDDK/SPK'nın HER kararı zaten en az bir işletme sektörünü ilgilendiren
türden kararlardı (düzenleyici kurumların kendi iş alanına dair kararlar).
Resmi Gazete'de bu doğru değil — askeri bölge ilanı, diplomatik vize
muafiyeti gibi HİÇBİR işletme sektörünü ilgilendirmeyen kararlar da var.

`classifier.py`'nin `SEKTOR_ETIKETLEME_KURALI`'ına şu eklenir: *"Karar
hiçbir işletme sektörünü (e-ticaret, finans, sağlık, eğitim), hatta 'genel'
bile ilgilendirmiyorsa, `sektorler` alanını boş dizi `[]` olarak döndür."*

Bu, **kod değişikliği gerektirmiyor** — `db.get_kararlar_by_profil`'in
mevcut filtresi (`profil in sektorler or "genel" in sektorler`) boş bir
diziyi zaten her profilde otomatik olarak dışlıyor. Sadece prompt/tool
şema açıklaması güncelleniyor. `KURUM_ADLARI`'na
`"resmi_gazete": "Resmi Gazete (T.C. Cumhurbaşkanlığı)"` eklenir.

## DB, Backend, Frontend Değişiklikleri

- **`backend.py`**: `run_scrape()`'in kaynak listesine
  `("resmi_gazete", resmi_gazete)` eklenir — per-source try/except zaten
  genelleştirilmiş, tek satır ekleme yeterli.
- **`index.html`**: Mevcut `kaynakOzetMetni()` fonksiyonu zaten bilinmeyen
  kaynakları öngörecek şekilde yazılmıştı (`digerleri` fallback'i), ama
  etiketi `String(k).toUpperCase()` ile üretiyor — `"resmi_gazete"` için
  çirkin `"RESMI_GAZETE"` üretirdi. Küçük bir etiket haritası eklenir:

  ```js
  const KAYNAK_ETIKETLERI = { kvkk: "KVKK", bddk: "BDDK", spk: "SPK", resmi_gazete: "Resmi Gazete" };
  function kaynakEtiketi(k) { return KAYNAK_ETIKETLERI[k] || String(k).toUpperCase(); }
  ```

  Hem `kararKart()`'taki rozet hem `kaynakOzetMetni()`'deki etiket üretimi
  bu fonksiyonu kullanacak şekilde güncellenir (`String(k).toUpperCase()`
  çağrıları `kaynakEtiketi(k)` ile değiştirilir).
- **`README.md`**: Kapsam bölümü artık 4 kaynağı da (KVKK, BDDK, SPK, Resmi
  Gazete) desteklendiği şekilde günceller.

## Uygulama Sırası (kullanıcı onayı ile ilerlenecek)

Tek yeni kaynak eklendiği için (BDDK+SPK'daki 3 faz yerine) **2 faz**:

1. **Faz 1**: `scrapers/resmi_gazete.py` yaz (TDD, fixture'a karşı) + canlı
   demo (gerçek `/Home/Filter` API'sine karşı çalıştır, en güncel 10
   kaydı konsola bas) → onay bekle
2. **Faz 2**: `classifier.py` (boş dizi kuralı + kurum adı) +
   `backend.py`/`index.html`/`README.md` entegrasyonu + uçtan uca canlı
   demo (4 kaynak birlikte; alakasız bir Resmi Gazete kararının hiçbir
   profilde görünmediği doğrulanır) → onay bekle
