# KVKK Mevzuat Takip Aracı

Türkiye'deki KOBİ'ler için KVKK Kurulu Kararları'nı otomatik tarayıp, seçilen
şirket profiline (e-ticaret / finans / sağlık / eğitim / genel) göre hangi
kararların ilgili olduğunu özetleyen basit bir araç.

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

MVP sadece KVKK Kurulu Kararları'nı (son ~10 karar, liste sayfasının ilk
sayfası) tarar. BDDK, SPK ve Resmi Gazete kaynakları henüz desteklenmiyor.
PDF tam metin işlenmiyor — yalnızca liste sayfasındaki başlık kullanılıyor.

## Lisans

MIT License — bkz. [LICENSE](LICENSE).

**AS IS, NO WARRANTY.** Bu yazılım "olduğu gibi" sunulur, hiçbir garanti
verilmez. Kullanım sorumluluğu kullanıcıya aittir.
