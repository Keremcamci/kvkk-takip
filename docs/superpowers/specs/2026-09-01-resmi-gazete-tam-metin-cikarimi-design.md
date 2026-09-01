# Resmi Gazete Tam Metin Çıkarımı — Tasarım

**Tarih**: 2026-09-01
**Durum**: Onaylandı
**İlgili spec**: `2026-08-30-tam-metin-cikarimi-design.md` (BDDK + KVKK),
`2026-08-31-spk-tam-metin-cikarimi-design.md` (SPK) — ikisi de Resmi
Gazete'yi "madde linki tek karara değil günün fihrist sayfasına gidiyor"
gerekçesiyle bilinçli olarak kapsam dışı bırakmıştı.

## Amaç

Resmi Gazete kararları şu an sadece başlıktan sınıflandırılıyor. Arama
API'sinin (`Home/Filter`) döndürdüğü `url` alanı gerçekten günün fihrist
(içindekiler) sayfasına gidiyor (`/fihrist?tarih=YYYY-MM-DD`), tek bir
maddeye değil — önceki iki spec'in varsayımı bu noktada doğruydu.

Ama fihrist sayfasının **kendisi** her maddeye ayrı bir derin link
veriyor (canlı doğrulandı, aşağıya bakınız) ve o derin link maddenin tam
metnini düz HTML olarak döndürüyor. Yani tam metin çıkarımı, günde bir
kez fihrist sayfasını çekip başlık eşleştirmesiyle doğru maddeye
ulaşarak mümkün — headless tarayıcıya gerek yok.

## Kapsam Dışı

- Sayfalama (7 günlük pencerenin/`limit=10`'un ötesine gitme) — kullanıcı
  onayıyla bu tasarımın dışında tutuldu, ayrı bir gelecek işi.
- `kaynak_url`'in şemasının değiştirilmesi — bkz. aşağıdaki karar bölümü.
- `Home/Filter` API'sinin kendisi (`fetch_veri`) — değişmiyor.
- `classifier.py`, DB şeması, API/UI — önceki iki spec'teki aynı mimari
  sınır, burada da değişmiyor.

## Kaynak Yapısı (canlı doğrulandı)

`Home/Filter` API'sinin döndürdüğü bir kayıt:

```json
{
  "konu": "İzmir Tınaztepe Üniversitesi Lisansüstü Eğitim-Öğretim Yönetmeliğinde Değişiklik Yapılmasına Dair Yönetmelik",
  "resmiGazeteTarihi": "2026-09-01T00:00:00",
  "url": "/fihrist?tarih=2026-09-01"
}
```

`url` günün fihrist sayfasına gidiyor. O sayfa tarayıcıda açılıp
incelendiğinde, her madde şu yapıda ayrı bir linke sahip:

```html
<div class="fihrist-item mb-1">
  <a href="https://www.resmigazete.gov.tr/eskiler/2026/09/20260901-1.htm" data-modal="True">
    –– İzmir Tınaztepe Üniversitesi Lisansüstü Eğitim-Öğretim Yönetmeliğinde Değişiklik Yapılmasına Dair Yönetmelik
  </a>
</div>
```

Bu derin link (`.../20260901-1.htm`) doğrudan (JavaScript/modal
gerekmeden, düz `fetch`/`requests.get` ile) o maddenin tam metnini
içeren bir HTML sayfası döndürüyor — canlı doğrulandı, madde madde tüm
yönetmelik metni geldi. Aynı günün farklı maddeleri sırayla `-1`, `-2`
gibi ayrı URL'lere gidiyor; iki farklı başlık test edildi, ikisi de
doğru ve birbirinden ayrı sayfaya eşleşti.

**Kodlama uyarısı**: Bu `.htm` sayfaları eski bir "MS Word'den web
sayfası olarak kaydet" formatında ve **Windows-1254** (Türkçe) karakter
kodlamasıyla geliyor. HTTP `Content-Type` header'ında charset
belirtilmiyor (yalnızca `text/html`), kodlama sadece HTML içindeki
`<meta charset>` etiketinde beyan ediliyor. `requests`'in
`response.encoding`'e güvenmek (ya da onu decode etmeden `response.text`
kullanmak) Türkçe karakterleri (ı, ş, ğ, ö, ü, ç) bozuk decode eder —
yanıt baytları elle `windows-1254` olarak decode edilmeli.

TLS: Resmi Gazete'nin sertifika zinciri sorunu (eksik ara sertifika)
önceki branch'te zaten çözülmüştü (`scrapers/certs/`), bu tasarım
`tammetin.guven_paketi()`'i olduğu gibi kullanır, ek bir sertifika
gerekmiyor.

## `kaynak_url` Kararı (kullanıcı onayıyla — SPK'den farklı)

SPK'de `kaynak_url`'i SPA sayfasından çalışan PDF linkine çevirmiştik.
Resmi Gazete'de de teorik olarak `kaynak_url`'i bulunan madde linkine
(`.../20260901-1.htm`) çevirebilirdik, ama bunun SPK'dekinden önemli bir
farkı var: SPK'nin dönüşümü **deterministik bir string transformasyonu**
(`IlkeKarari/Dosya/{id}` → `api/IlkeKarari/File/{id}`) olduğu için
`db.py`'deki migrasyon ağa çıkmadan, salt SQL `UPDATE` ile yapılabildi.
Resmi Gazete'de böyle bir dönüşüm yok — hangi maddenin hangi `-N.htm`'e
karşılık geldiğini bulmak için fihrist sayfasını tekrar çekip başlık
eşleştirmesi gerekir. Bu, migrasyonu ağa bağımlı (yavaş, kırılgan, her
`init_db()` çağrısında — yani her `--scrape`/`--reset-failed`/sunucu
başlangıcında ağa çıkan) hale getirirdi.

**Karar**: `kaynak_url` DEĞİŞMİYOR — fihrist linki + hash şeması
(`{fihrist_url}#{konu_hash}`) olduğu gibi kalıyor. Tam metin çıkarımı
sadece `ozet_ham`'i zenginleştirir. Bedel: "Kaynağı gör" linki hâlâ
günün fihrist sayfasına gider, tek maddeye değil (mevcut davranış,
regresyon değil) — ama migrasyon riski sıfır, çünkü hiçbir mevcut satır
dokunulmuyor.

## Mimari

`scrapers/resmi_gazete.py`'ye iki yeni yardımcı fonksiyon:

```python
def _fihrist_linkleri(tarih: str) -> dict[str, str]:
    """O günün fihrist sayfasını çeker, normalize edilmiş madde
    başlığından href'e giden bir sözlük döner. Sayfa çekilemezse veya
    beklenen yapı bulunamazsa boş sözlük döner (sessiz düşüş)."""

def _madde_url_bul(tarih: str, konu: str, fihrist_cache: dict) -> str | None:
    """fihrist_cache[tarih] yoksa _fihrist_linkleri ile doldurur (aynı
    günün sonraki kararları tekrar ağa çıkmaz), konu'yu aynı normalize
    kurallarıyla eşleştirip href döner, bulamazsa None."""
```

Normalize kuralı (her iki taraf — API'nin `konu`'su ve fihrist linkinin
metni — için aynı fonksiyonla uygulanır): baştaki tire benzeri
karakterler ve boşluklar (`" \t–—-"` kümesinden) `str.lstrip` ile
temizlenir, `str.split()` + `" ".join(...)` ile iç boşluklar tek
boşluğa indirilir, sonra **birebir (case-sensitive) eşitlik** ile
karşılaştırılır — canlı doğrulamada API'nin `konu`'su ile linkin
normalize edilmiş metni birebir aynı çıktı, bulanık/kısmi eşleştirmeye
gerek yok.

`scrapers/tammetin.py`'ye yeni bir fonksiyon:

```python
def resmi_gazete_madde_metni_cek(url: str, timeout: int = 15) -> str | None:
    """kvkk_sayfa_metni_cek ile aynı hata-yönetimi iskeleti (ağ hatası
    -> None + logging.warning). Farklar: yanıt baytları elle
    windows-1254 olarak decode edilir (HTTP header'da charset yok);
    içerik div.Section1 içinden alınır (Word HTML export'un standart
    kök div'i), bulunamazsa body'e düşülür; aynı görünmez-karakter
    boşluk kontrolü uygulanır."""
```

`scrape_and_store` güncellenir — BDDK/SPK'nin desenini tekrarlar, tek
fark: `_madde_url_bul` için taramanın ömrü boyunca yaşayan bir
`fihrist_cache: dict = {}` tutulur (fonksiyon içinde tanımlanır, günlük
tekrar fetch'i önler):

```python
def scrape_and_store(conn, url=RESMI_GAZETE_FILTER_URL, limit=10) -> int:
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

`kaynak_url` üretimi (`parse_kararlar`) değişmiyor.

## Veri Akışı

1. `fetch_veri()` (değişmiyor) → 7 günlük pencerede en fazla 10 karar.
2. Her karar için: `karar_var_mi` ile dedup kontrolü.
3. Yeni ise `_madde_url_bul(tarih, baslik, fihrist_cache)` — o günün
   fihristi cache'te yoksa bir kez çekilir, sonraki aynı günün kararları
   cache'ten okur.
4. Eşleşme bulunduysa `resmi_gazete_madde_metni_cek(madde_url)` ile tam
   metin çekilir; başarılıysa `ozet_ham` bu metinle değişir.
5. Fihrist eşleşmesi veya metin çekimi başarısız olursa `ozet_ham`
   mevcut davranışta kalır (`baslik`'in kopyası) — sessiz düşüş,
   `logging.warning`.

## Hata Yönetimi

- Fihrist sayfası çekilemezse (ağ/TLS hatası) → `_fihrist_linkleri` boş
  sözlük döner, o günün TÜM kararları başlığa düşer (fihrist günde bir
  kez çekildiği için, hata da o gün için tek seferlik).
- Başlık eşleşmesi bulunamazsa (format değişikliği, mükerrer sayı vb.)
  → `None`, sessiz düşüş.
- Madde sayfası 200 dönse bile `div.Section1`/`body` boşsa/yoksa →
  `None` + `logging.warning`, `kvkk_sayfa_metni_cek` ile aynı desen.
- `windows-1254` decode açıkça yapılır, `response.encoding`'e
  güvenilmez.

## Test Planı

- `_fihrist_linkleri` / `_madde_url_bul`: sabit bir örnek fihrist HTML
  fixture'ı üzerinden başarılı eşleşme, eşleşme yok, önek/boşluk
  normalizasyonu, cache'in aynı gün için tekrar fetch yapmadığı.
- `tammetin.resmi_gazete_madde_metni_cek`: başarı, ağ hatası, boş
  içerik, ve `windows-1254` karakterlerinin (ş/ğ/ı içeren bir fixture
  ile) doğru decode edildiğini doğrulayan bir test.
- `scrape_and_store`: tam metin başarılı/başarısız senaryoları, aynı
  günün birden fazla kararı için fihrist'in sadece bir kez çekildiğini
  doğrulayan test, mevcut testlerin `tammetin`/`_fihrist_linkleri`
  mock'lanarak güncellenmesi (gerçek ağa çıkmasınlar diye — autouse
  socket-block fixture zaten bunu yakalar).
- README güncellemesi: kapsam tablosundaki Resmi Gazete satırı, "hâlâ
  yalnızca başlıktan sınıflandırılıyor" diyen paragraf, ve "Kapsam dışı"
  bölümündeki ilgili not (sayfalama kalır, tam metin çıkarımı çıkar).

## Uygulama Sırası

Tek fazlı — BDDK/SPK'nin deseninin bir varyasyonu olduğu için (yeni bir
bağımlılık eklenmiyor, mimari risk düşük) ayrı faz kontrol noktalarına
gerek görülmedi; tek bir canlı doğrulama adımı (görev sonunda) yeterli.
