# Karar Metninin Zenginleştirilmesi (Tam Metin Çıkarımı) — Tasarım

**Tarih**: 2026-08-30
**Durum**: Onaylandı
**İlgili bulgu**: Bağımsız bir kod incelemesinde işaretlenen en kritik ürün
riski — sınıflandırma ve özetler yalnızca karar BAŞLIĞINDAN üretiliyordu,
tam metin/PDF çıkarımı yoktu.

## Amaç

`classifier.py`'ye giden `ozet_ham` alanı bugün sadece `baslik`'in bir
kopyası. KVKK karar başlıkları genelde yalnızca tarih ve karar numarası
içeriyor ("...Kurulunun 22.07.2026 Tarihli ve 2026/1491 Sayılı Kararı") —
LLM bu metinden gerçek içeriği, hangi sektörü ilgilendirdiğini ve ne
yapılması gerektiğini isabetli çıkaramaz. Bu tasarım, mümkün olan
kaynaklar için `ozet_ham`'ı gerçek karar metniyle (PDF veya sayfa özeti)
doldurur — **`classifier.py`'de hiçbir değişiklik gerektirmeden**, çünkü
`build_prompt()` zaten `ozet_ham`'ı olduğu gibi prompt'a yazıyor.

## Kapsam Dışı

- **SPK**: "Dosya" linki (`mevzuat.spk.gov.tr/IlkeKarari/Dosya/{id}`) canlı
  test edildi — düz bir HTTP GET, React SPA kabuğu (`<div id="root">`,
  `Content-Type: text/html`, 2830 bayt) döndürüyor; gerçek içerik
  JavaScript ile client-side render ediliyor. Düz `requests.get()` ile
  ulaşılamaz; ya gizli bir API endpoint'i bulmak ya da headless tarayıcı
  eklemek gerekir (projede şu an hiçbiri yok). **Bu iterasyonda SPK
  başlık-tabanlı kalır.**
- **Resmi Gazete**: `kaynak_url` zaten tek bir maddeye değil, o günün
  **fihrist (içindekiler) sayfasına** gidiyor
  (`/fihrist?tarih=2026-08-28`) — bu, önceki spec'te bilinçli kabul
  edilmiş bir sınırlama. Maddenin kendi linkini yakalamak ayrı bir alt
  problem. **Bu iterasyonda Resmi Gazete başlık-tabanlı kalır.**
- Taranmış/görsel (OCR gerektiren) PDF'ler — metin katmanı yoksa
  başlığa düşülür, OCR eklenmez.
- `classifier.py`, `db` şeması (yeni sütun), veya API/UI değişikliği —
  hiçbiri gerekmiyor (bkz. Amaç).

## Kaynak Yapısı (canlı doğrulandı)

### BDDK — doğrudan PDF

`scrapers/bddk.py`'nin ürettiği `kaynak_url`
(`bddk.org.tr/Mevzuat/DokumanGetir/{id}`) düz bir GET ile doğrudan PDF
döndürüyor:

```
Content-Type: application/pdf
Content-Disposition: inline; filename=mevzuat_1345.pdf
```

`pypdf` ile çıkarım canlı test edildi (Karar No 11548, 06.08.2026), 1
sayfa, 627 karakter temiz Türkçe metin:

> "Bankacılık Düzenleme ve Denetleme Kurumundan: BANKACILIK DÜZENLEME VE
> DENETLEME KURULU KARARI ... BLG Varlık Yönetim A.Ş.'nin faaliyet
> izninin ... iptal edilmesine karar verilmiştir."

### KVKK — iki alt durum, host'a göre ayrılır

- **`www.kvkk.gov.tr` üzerindeki dahili linkler** (ör.
  `/Icerik/7791/2023-2135`): HTML detay sayfası, `div.news__detail-article`
  seçicisi içinde gerçek "Konu Özeti" + gerekçe paragrafını taşıyor.
  Canlı doğrulandı (Karar 2023/2135), 898 karakter:

  > "...Kişisel Verileri Koruma Kurulu tarafından, 6698 sayılı Kişisel
  > Verilerin Korunması Kanunu'nun 16'ncı maddesinin (2) numaralı fıkrası
  > ... çerçevesinde yapılan inceleme neticesinde, Köy kamu tüzel
  > kişiliklerinin Veri Sorumluları Siciline kayıt yükümlülüğüne istisna
  > getirilmesine karar verilmesine ... oybirliği ile karar verilmiştir."

  Not: Sayfadaki bir `<table>` içinde "Konu Özeti" etiketli başka bir
  hücre daha var, ama o yalnızca `baslik`'in kısa tekrarı — asıl
  gerekçe metni `div.news__detail-article` içinde, tabloda değil.

- **Diğer tüm linkler** (ör. `resmigazete.gov.tr/eskiler/...pdf`):
  doğrudan PDF — BDDK ile aynı `pdf_metni_cek()` yolunu kullanır.

## Mimari

**Yeni modül**: `scrapers/tammetin.py`

```python
def pdf_metni_cek(url: str, timeout: int = 15) -> str | None: ...
def kvkk_sayfa_metni_cek(url: str, timeout: int = 15) -> str | None: ...
```

Her ikisi de her hata sınıfında (ağ hatası, beklenmeyen content-type, boş/
taranmış metin, seçici bulunamadı, çok büyük dosya) `None` döner ve
`logging.warning` ile nedenini loglar — hiçbiri exception fırlatmaz,
scraper'ın geri kalanını durdurmaz.

**Yeni `db.py` fonksiyonu**: `karar_var_mi(conn, kaynak_url) -> bool` —
zaten bilinen bir karar için gereksiz tam metin indirmesi yapılmasın diye
(her scrape koşusunda aynı 10 kararı tekrar tekrar indirmemek, hem
performans hem hedef siteye saygı için), `insert_karar_if_new`'den ÖNCE
ucuz bir varlık kontrolü.

**Entegrasyon** (`scrapers/bddk.py`, `scrapers/kvkk.py`):

```python
for karar in kararlar:
    if db.karar_var_mi(conn, karar["kaynak_url"]):
        continue
    tam_metin = ...  # kaynağa göre pdf_metni_cek / kvkk_sayfa_metni_cek
    if tam_metin:
        karar["ozet_ham"] = tam_metin
    if db.insert_karar_if_new(conn, kaynak=..., **karar):
        yeni_sayisi += 1
```

KVKK'da dallanma: `urlparse(kaynak_url).netloc == "www.kvkk.gov.tr"` ise
`kvkk_sayfa_metni_cek`, değilse `pdf_metni_cek`.

## Sınırlar

- **PDF boyutu**: 5 MB üst sınır — anormal büyük bir dosya indirilirse
  atlanır (metin çıkarımı denenmez).
- **Metin uzunluğu**: Çıkarılan metin 6000 karakterde kırpılır (LLM
  prompt maliyetini kontrol altında tutmak için). Gerçek örneklerde
  (627 / 898 karakter) bu sınıra hiç yaklaşılmıyor — çoğunlukla devreye
  girmeyecek bir güvenlik ağı. Kırpma düz `metin[:6000]` ile yapılır;
  kelime/cümle sınırına denk gelmesi gerekmez (LLM için önemli değil).
- Yeni bağımlılık: `pypdf` (`requirements.txt`'e eklenir).

## Test Planı

- `tests/fixtures/bddk_karar_sample.pdf`: canlı BDDK sitesinden indirilen
  gerçek dosya (Karar No 11548, 136 KB) — projenin "gerçek mevzuat
  sitelerinden alınmış fixture" geleneğiyle uyumlu.
- `tests/fixtures/kvkk_karar_detay_sample.html`: gerçek KVKK detay
  sayfasından alınmış, `div.news__detail-article` içeren kırpılmış örnek.
- `pdf_metni_cek` / `kvkk_sayfa_metni_cek` için her başarısızlık yolu ayrı
  test edilir: ağ hatası, yanlış content-type, boş/taranmış metin, seçici
  yok, dosya çok büyük.
- `db.karar_var_mi`: doğrudan birim testi (var olan/olmayan `kaynak_url`
  için `True`/`False`).
- `karar_var_mi` entegrasyonu için: ikinci `scrape_and_store` çağrısında
  tam metin fonksiyonlarının TEKRAR çağrılmadığını doğrulayan idempotency
  testi (mock'un `call_count`'u kontrol edilir).
- `scrapers/bddk.py` ve `scrapers/kvkk.py` testleri: tam metin başarılı/
  başarısız olduğunda `ozet_ham`'ın doğru değeri aldığını doğrular.

## Uygulama Sırası (her fazdan sonra onay)

1. **Faz 1**: `scrapers/tammetin.py` (TDD, yukarıdaki fixture'lara karşı)
   + `db.karar_var_mi()` → onay bekle
2. **Faz 2**: BDDK entegrasyonu + canlı demo (gerçek siteye karşı çalıştır,
   `ozet_ham`'ın gerçek karar metnini içerdiğini konsola bas) → onay bekle
3. **Faz 3**: KVKK entegrasyonu (iki alt durum) + canlı demo + README
   güncellemesi (Kapsam bölümüne "BDDK/KVKK artık tam metinden
   sınıflandırılıyor, SPK/Resmi Gazete başlık-tabanlı kalıyor" notu)
   → onay bekle
