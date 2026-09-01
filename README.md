# KVKK Mevzuat Takip Aracı

Türkiye'deki KOBİ'ler için KVKK, BDDK, SPK ve Resmi Gazete kararlarını
otomatik tarayıp,
seçilen şirket profiline (e-ticaret / finans / sağlık / eğitim / genel) göre
hangi kararların ilgili olduğunu özetleyen basit bir araç.

**Bu araç hukuki tavsiye değildir, bilgi amaçlıdır. Kararlar için resmi
kaynağı ve/veya bir avukatı kontrol edin.**

## Kurulum

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env dosyasını açıp ANTHROPIC_API_KEY değerini doldurun
```

## Kullanım

```bash
# 1. Kararları tara ve sınıflandır (SQLite'a yazar)
python backend.py --scrape

# 2. Web arayüzünü başlat
python backend.py
# http://localhost:5001 adresini aç
```

Not: `--scrape` artık tam metin çıkarımı yüzünden öncekinden belirgin
şekilde daha uzun sürebilir (karar başına, kendi timeout'u olan ek
sıralı indirmeler) — sıkı bir timeout'a sahip bir cron job kullanıyorsanız
bunu göz önünde bulundurun.

### Kalıcı hatalardan kurtarma

Bir karar üst üste 3 kez sınıflandırılamazsa (örn. `.env` içindeki
`ANTHROPIC_API_KEY` hatalı yazılmışsa) kalıcı hata olarak işaretlenir ve bir
daha otomatik denenmez. Sorunu düzelttikten sonra bu kararları yeniden
kuyruğa almak için:

```bash
python backend.py --reset-failed   # kalıcı hataları yeniden denenebilir yapar
python backend.py --scrape         # sonra pipeline'ı tekrar çalıştırın
```

Sınıflandırma hataları `logging.warning` ile stderr'e yazılır; hangi kararın
neden başarısız olduğunu görmek için `--scrape` çıktısına bakın.

## Test

```bash
pytest
```

`tests/test_frontend.py` içindeki bazı testler `index.html`'in JavaScript'ini
gerçekten çalıştırmak için `node` kullanır; `node` kurulu değilse o testler
atlanır, diğerleri çalışır.

## Kapsam

Dört kaynak destekleniyor; her birinden en güncel ~10 karar taranır (liste
sayfasının/API yanıtının ilk sayfası):

| Kaynak        | Ne taranıyor                                          |
| ------------- | ------------------------------------------------------ |
| KVKK          | Kurul Kararları                                        |
| BDDK          | Kurul Kararları                                        |
| SPK           | Kurul Kararları / İlke Kararları                       |
| Resmi Gazete  | Yürütme ve İdare bölümü (yönetmelik/tebliğ/CB kararı/kurul kararı) |

Bir kaynağa erişilemezse diğerleri çalışmaya devam eder; hata `--scrape`
çıktısında `logging.warning` ile (yığın iziyle birlikte) raporlanır.

BDDK, KVKK ve SPK kararları artık (mümkün olduğunda) gerçek karar
metninden sınıflandırılıyor — BDDK ve SPK için doğrudan PDF (SPK'nın
"Dosya" sayfası bir React SPA kabuğu, ama sayfanın kendi arka plan
çağrısı izlenerek bulunan düz bir REST API'den PDF doğrudan çekiliyor —
headless tarayıcı gerekmiyor), KVKK için (kaynağa göre) kendi detay
sayfasındaki özet veya PDF. Tam metin indirilemezse (ağ hatası,
taranmış/görsel PDF, vb.) sessizce başlığa düşülür.

Bu tam metin indirme, sertifika zincirini eksik gönderen bazı siteler
(BDDK, Resmi Gazete) için `scrapers/certs/*.pem` altında paketlenmiş
belirli TLS ara sertifikalarına dayanıyor. Hedef site sertifika
altyapısını gelecekte değiştirirse, o kaynak için tam metin çıkarımı
sessizce (hata vermeden, `logging.warning` ile) başlığa geri düşer — bu
bir bakım kalemidir, kalıcı bir çözüm değildir; bundle'ın güncellenmesi
gerekebilir.

Resmi Gazete kararları hâlâ yalnızca başlıktan sınıflandırılıyor:
linki tek bir maddeye değil günün fihrist sayfasına gidiyor (bkz.
aşağıdaki not).

Kapsam dışı (ileriye dönük): Resmi Gazete için tam metin çıkarımı ve
sayfalama — yani her kaynağın ilk sayfasından öteye gidilmiyor.

Not: Arayüzdeki profil filtresi kararları etikete göre süzer; BDDK ve SPK
kararlarının çoğu doğal olarak `finans` etiketi alır. Bu yüzden varsayılan
"Genel" profilinde görünmeyebilirler — sayfanın üstündeki
"Toplam: … karar takip ediliyor." satırı her kaynaktan kaç karar
kaydedildiğini profil seçiminden bağımsız olarak gösterir.

Not: Bir kararın `sektorler` alanı boş dizi ([]) olarak sınıflandırılması,
kararın dört sektörün (e-ticaret, finans, sağlık, eğitim) hiçbirini
ilgilendirmediği anlamına gelir (örn. askeri bölge ilanı, kurum içi
organizasyon kararı). Böyle bir karar yine de "Toplam: … karar takip
ediliyor." satırındaki kaynak sayısına dahildir, ama profil değiştirilse
bile HİÇBİR profilde görünmez. Bu kasıtlıdır — aracın kararı doğru şekilde
"hiçbir takip edilen işletme türüyle ilgisiz" olarak değerlendirdiği
anlamına gelir; eksik bir profil ya da hata değildir.

Not: Resmi Gazete kararlarının kaynak linki, ilgili maddenin kendisine
değil o günün resmi fihrist (içindekiler) sayfasına gider — yine de resmi
ve doğru bir kaynak, sadece tek maddeye değil günün tümüne işaret eder.

## Lisans

MIT License — bkz. [LICENSE](LICENSE).

**AS IS, NO WARRANTY.** Bu yazılım "olduğu gibi" sunulur, hiçbir garanti
verilmez. Kullanım sorumluluğu kullanıcıya aittir.
