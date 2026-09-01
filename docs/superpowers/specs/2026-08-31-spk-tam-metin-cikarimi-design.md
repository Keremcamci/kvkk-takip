# SPK Tam Metin Çıkarımı — Tasarım

**Tarih**: 2026-08-31
**Durum**: Onaylandı
**İlgili spec**: `2026-08-30-tam-metin-cikarimi-design.md` (BDDK + KVKK; SPK
o iterasyonda "React SPA, headless tarayıcı gerektirir" gerekçesiyle
bilinçli olarak kapsam dışı bırakılmıştı)

## Amaç

Önceki spec SPK'yı kapsam dışı bırakırken şu varsayımı yapmıştı: SPK'nın
"Dosya" linki (`mevzuat.spk.gov.tr/IlkeKarari/Dosya/{id}`) React ile
client-side render ediliyor, düz bir HTTP GET ile içeriğe ulaşılamıyor,
dolayısıyla headless tarayıcı (Playwright/Selenium) gerekir.

Bu varsayım **kısmen yanlıştı**: sayfanın kabuğu gerçekten SPA, ama sayfa
kendi içinde arka planda düz bir REST API çağrısı yapıyor ve bu API
düz bir HTTP GET ile (kimlik doğrulama, cookie, JavaScript render
gerekmeden) doğrudan PDF döndürüyor. Bu tasarım, headless tarayıcı
eklemeden, mevcut `scrapers/tammetin.py` altyapısını (BDDK için zaten
kullanılan) yeniden kullanarak SPK'yı da tam metinden sınıflandırmaya
açar.

## Kapsam Dışı

- Headless tarayıcı entegrasyonu (Playwright/Selenium) — artık gerekmiyor.
- `GECERLI_TURLER` dışındaki tür (Tebliğ) — zaten taramada eleniyor,
  bu tasarım onu etkilemiyor.
- Resmi Gazete tam metin çıkarımı — ayrı, çözülmemiş bir sorun (madde
  linki tek karara değil günün fihrist sayfasına gidiyor), bu tasarımın
  kapsamında değil.

## Kaynak Yapısı (canlı doğrulandı)

Tarayıcıda `https://mevzuat.spk.gov.tr/IlkeKarari/Dosya/377` açılıp ağ
istekleri incelendi. Sayfa kendi içinde şu çağrıyı yapıyor:

```
GET https://mevzuat.spk.gov.tr/api/IlkeKarari/File/377
```

Bu URL, oturum/cookie olmadan düz `curl` ile de doğrudan çalışıyor:

```
HTTP/1.1 200 OK
Content-Length: 70830
Content-Type: application/pdf
```

Aynı desen ikinci bir kayıtla (id=375, "Kurul Kararı" türü) da doğrulandı
— aynı şekilde `200` + `application/pdf`. Mevcut `GECERLI_TURLER`'ın
kabul ettiği iki türün (`İlke Kararı`, `Kurul Kararı`) ikisi de arama
API'sinde `contentSource: "IlkeKarari"` taşıyor, yani dönüşüm kuralı
her ikisi için de aynı.

Arama API'sinin (`api/Search/All`) her kaydı zaten `contentSource` ve
`contentID` alanlarını taşıyor — bu alanlar tam olarak dosya URL'sini
inşa etmek için var:

```json
{
  "contentSource": "IlkeKarari",
  "contentID": 377,
  "link": "IlkeKarari/Dosya/377"
}
```

Dönüşüm kuralı: `link` alanını regex ile parse etmek yerine, zaten
mevcut olan `contentSource` + `contentID` alanlarından doğrudan
`api/{contentSource}/File/{contentID}` üretilir — daha az kırılgan.

**SPK'nın kendi sertifika zinciri tam** (BDDK/Resmi Gazete'nin aksine)
— canlı doğrulandı, `guven_paketi()`'nin eklediği ek ara sertifikalara
ihtiyaç yok, ama `pdf_metni_cek()` zaten `guven_paketi()` kullandığı
için (certifi + ekstra sertifikalar, süperset) sorun oluşturmuyor.

## `kaynak_url` Kararı (kullanıcı onayıyla)

`kaynak_url` artık SPA sayfası değil, doğrudan çalışan API PDF linkine
işaret eder — hem "Kaynağı gör" linkinde hem tam metin çekiminde
kullanılan TEK URL, diğer tüm kaynaklarla (BDDK/KVKK) aynı desen.
Gerekçe: SPA sayfası bu ortamda test edildiğinde içerik göstermeden boş
kaldı (canlı ekran görüntüsüyle doğrulandı) — API linki hem daha basit
hem daha güvenilir bir kullanıcı deneyimi.

`contentSource`/`contentID` eksikse (beklenmeyen bir API yanıtı
durumunda) `kaynak_url` ham `link` değerine (SPA sayfası) düşer —
sessiz bozulma yok, sadece tam metin çıkarımı o kayıt için çalışmaz.

## Mimari

`scrapers/spk.py`'ye yeni bir yardımcı fonksiyon:

```python
def _dosya_api_yolu(item: dict) -> str | None:
    kaynak = item.get("contentSource")
    kimlik = item.get("contentID")
    if not kaynak or kimlik is None:
        return None
    return f"api/{kaynak}/File/{kimlik}"
```

`parse_kararlar`'daki `kaynak_url` satırı değişir:
```python
"kaynak_url": urljoin(base_url, _dosya_api_yolu(item) or link),
```

`scrape_and_store`, BDDK'nın (Task 4, önceki iterasyon) desenini
BİREBİR tekrarlar: `db.karar_var_mi` ile önce varlık kontrolü, sonra
`tammetin.pdf_metni_cek(karar["kaynak_url"])`, başarılıysa `ozet_ham`
değişir, başarısızsa (ağ hatası, taranmış PDF, vb.) mevcut davranış
(başlık) korunur.

`fetch_veri` (arama API'si çağrısı) DEĞİŞMİYOR — SPK'nın bu ucu zaten
sertifika sorunu yaşamıyor.

`classifier.py`, DB şeması, API/UI — yine hiçbiri değişmiyor (önceki
spec'teki aynı mimari sınır).

## Test Planı

- Mevcut fixture (`tests/fixtures/spk_kararlar_sample.json`) zaten
  `contentSource`/`contentID` alanlarını içeriyor, değişiklik gerekmez.
- `tests/test_scrapers_spk.py`'deki mevcut `kaynak_url` beklentisi
  (`.../IlkeKarari/Dosya/377`) yeni değere (`.../api/IlkeKarari/File/377`)
  güncellenir.
- BDDK'nın Task 4'ündeki testlerin birebir eşi: tam metin başarılı/
  başarısız/idempotency (`karar_var_mi` sayesinde tekrar çekilmiyor).
- `_dosya_api_yolu`'nun `contentSource`/`contentID` eksik olduğunda
  `None` döndüğü ve `kaynak_url`'in bu durumda ham `link`'e düştüğü
  ayrı test edilir.
- Mevcut 3 test (`test_scrape_and_store_inserts_new_kararlar`,
  `test_scrape_and_store_is_idempotent`, `test_scrape_and_store_respects_limit`)
  `tammetin.pdf_metni_cek` mock'lanarak güncellenir (BDDK'daki ÖNEMLİ
  notla aynı gerekçe: mock'lanmazsa gerçek ağa çıkarlar).

## Uygulama Sırası

Tek fazlı — BDDK'nın deseninin doğrudan tekrarı olduğu için (yeni bir
mimari riski yok, headless tarayıcı gibi büyük bir bağımlılık eklenmiyor)
ayrı faz kontrol noktalarına gerek görülmedi; tek bir canlı doğrulama
adımı (Task sonunda) yeterli.
