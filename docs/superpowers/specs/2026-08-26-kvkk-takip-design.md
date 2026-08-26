# KVKK Mevzuat Takip Aracı — Tasarım

**Tarih**: 2026-08-26
**Durum**: Onaylandı (MVP kapsamı)

## Amaç

Türkiye'deki KOBİ'ler için mevzuat takip/uyarı aracı. MVP kapsamı: KVKK Kurulu
Kararları'nı otomatik tara, kullanıcının seçtiği şirket profiline (e-ticaret /
finans / sağlık / eğitim / genel) göre hangi kararların onu ilgilendirdiğini
özetle. BDDK, SPK, Resmi Gazete kaynakları MVP sonrası eklenecek — şema ve
mimari bunu göz önünde bulundurarak tasarlandı (`kaynak` sütunu).

**Bu araç hukuki tavsiye değildir, bilgi amaçlıdır.** Kararlar için resmi
kaynağı ve/veya bir avukatı kontrol edin. Bu uyarı hem README'de hem UI'da
sabit olarak yer alacak.

## Kapsam Dışı (MVP)

- BDDK, SPK, Resmi Gazete kaynakları (sonraki faz)
- PDF tam metin çıkarma (sadece liste özeti kullanılıyor)
- Web'den scrape tetikleme endpoint'i (sadece CLI)
- Kullanıcı hesabı / çoklu kullanıcı / auth
- Otomatik zamanlama (cron) — MVP'de manuel `python backend.py --scrape`

## Proje Yapısı

```
kvkk-takip/
├── backend.py          # Flask app (serve + API) + CLI (--scrape)
├── scraper.py           # KVKK sayfası scraping
├── classifier.py        # Anthropic API sınıflandırma
├── db.py                 # SQLite şema + CRUD (stdlib sqlite3)
├── index.html            # Tek dosya frontend
├── kvkk.db                 # SQLite (gitignore)
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
└── LICENSE                  # MIT
```

## Veri Modeli (`db.py`, SQLite)

```sql
CREATE TABLE kararlar (
    id INTEGER PRIMARY KEY,
    kaynak TEXT NOT NULL DEFAULT 'kvkk',
    baslik TEXT NOT NULL,
    tarih TEXT,
    kaynak_url TEXT UNIQUE NOT NULL,
    ozet_ham TEXT,
    sektorler TEXT,               -- JSON array string, örn ["e-ticaret","genel"]
    llm_ozet TEXT,
    yapilmasi_gerekenler TEXT,     -- JSON array string
    aciliyet_var INTEGER,          -- 0/1
    aciliyet_aciklama TEXT,
    islendi_mi INTEGER DEFAULT 0,  -- 0=bekliyor, 1=tamamlandı, -1=kalıcı hata
    deneme_sayisi INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

`kaynak_url` üzerindeki `UNIQUE` constraint duplicate-scrape'i engeller
(`INSERT OR IGNORE`).

## Scraper (`scraper.py`)

**Güncelleme (plan yazımı sırasında canlı siteye bakılarak doğrulandı):**
Kullanıcının verdiği `kvkk.gov.tr/Icerik/Kurul-Kararlari` URL'i güncel değil
(anasayfaya 302 redirect ediyor). Gerçek sayfa: `https://www.kvkk.gov.tr/Icerik/5419/kurul-kararlari`.

- `robots.txt` `https://www.kvkk.gov.tr/robots.txt` şu an mevcut değil (302 →
  anasayfa), yani beyan edilmiş bir kısıtlama yok.
- Sayfa **düz HTML** (JS render gerekmiyor) — `requests.get()` + descriptive
  `User-Agent` header, status 200, doğrudan tam liste dönüyor. `playwright`
  gerekmiyor.
- Liste sayfasında **ayrı bir özet metni yok** — her karar için tek bir uzun
  başlık var (örn. "... Kişisel Verileri Koruma Kurulunun 22.07.2026 Tarihli
  ve 2026/1491 Sayılı Kararı"), tarih ve karar no bu başlığın içine gömülü.
  Bu yüzden `ozet_ham = baslik` (aynı metin), `tarih` başlıktan regex ile
  parse ediliyor (`DD.MM.YYYY` veya `DD/MM/YYYY` → ISO `YYYY-MM-DD`).
- Her karar satırı: `div.members__item` container, başlık `h2` içinde, link
  `a.read-more[href]`. Link bazen harici bir Resmi Gazete PDF'i, bazen
  KVKK'nın kendi iç sayfası olabiliyor — ikisi de aynı şekilde `kaynak_url`
  olarak saklanıyor, MVP'de fetch/parse edilmiyor.
- Sayfalama var (`?page=1/2/3`, ~10 karar/sayfa) — **MVP sadece sayfa 1'i
  (en güncel ~10 karar) çeker**, pagination kapsam dışı.
- Çekilecek alanlar: `baslik`, `tarih`, `kaynak_url`, `ozet_ham`
- Yeni kararlar `db.insert_karar_if_new()` ile yazılır

## LLM Sınıflandırma (`classifier.py`)

- `islendi_mi = 0` olan kararları sırayla işler (`-1` olanlar bir daha
  denenmez — kalıcı hata)
- Model adı **kod içine sabit yazılmaz** — `.env`'den `ANTHROPIC_MODEL` okunur
- Anthropic API'nin structured output (tool-use / JSON schema) özelliği ile
  şu şema zorlanır:

```json
{
  "sektorler": ["e-ticaret", "genel"],
  "ozet": "2-3 cümlelik özet",
  "yapilmasi_gerekenler": ["madde 1", "madde 2"],
  "aciliyet_var": true,
  "aciliyet_aciklama": "kısa açıklama"
}
```

- Rate-limit / geçici hata (429, 5xx): exponential backoff (1s, 2s, 4s),
  fonksiyon içi retry
- Backoff tükenip yine başarısız olursa: `deneme_sayisi += 1`;
  `deneme_sayisi >= 3` ise `islendi_mi = -1` (kalıcı, otomatik tekrar
  denenmez), değilse `islendi_mi = 0` kalır (sıradaki `--scrape`
  çalıştırmasında tekrar denenir)
- Hatalar sessizce yutulmaz, loglanır

## API (`backend.py`, Flask)

- `GET /` → `index.html` serve eder
- `GET /api/kararlar?profil=e-ticaret` → response:

```json
{
  "son_guncelleme": "2026-08-26T14:32:00",
  "kararlar": [ /* profile + "genel" kararları, tarihe göre yeniden eskiye, islendi_mi=1 olanlar */ ]
}
```

  - `son_guncelleme` = DB genelinde `MAX(created_at)` (profile'dan bağımsız,
    global sinyal — "veri ne kadar güncel" sorusuna cevap). DB boşsa `null`.
  - `islendi_mi = -1` olan kararlar hiçbir zaman API'den dönmez.
- Web'den scrape tetikleyen bir endpoint **yok** — sadece
  `python backend.py --scrape` (CLI). Gerekçe: saldırı yüzeyini büyütmemek +
  minimal kapsam.

## Frontend (`index.html`)

- Dropdown: e-ticaret / finans / sağlık / eğitim / genel
- Seçim değişince `fetch('/api/kararlar?profil=...')`
- Üstte sabit uyarı metni (hukuki tavsiye değildir...)
- Üstte/köşede "Son güncelleme: <tarih>" bilgisi (`son_guncelleme` alanından,
  yoksa "Henüz veri yok")
- Kart listesi: başlık, tarih, özet, yapılması gerekenler (liste), aciliyet
  rozeti (varsa vurgulu)
- Süsleme yok — düz CSS, sistem fontu, aciliyet için tek renk vurgusu

## Lisans & Dokümantasyon

- `LICENSE`: MIT
- `README.md`: kurulum adımları, MIT notu, **"AS IS, NO WARRANTY"**, hukuki
  uyarı metni (UI'dakiyle aynı)

## Uygulama Sırası (kullanıcı onayı ile ilerlenecek)

1. **Scraper testi**: KVKK sayfasını çek, gerçek HTML yapısını incele,
   scraping'in mümkün olduğunu doğrula, çalışan bir demo göster (konsola
   parse edilmiş kararları basmak yeterli) → onay bekle
2. **LLM sınıflandırma**: `classifier.py`'yi ekle, birkaç karar üzerinde
   çalıştığını göster → onay bekle
3. **Frontend**: `backend.py` + `index.html`'i bağla, uçtan uca demo göster →
   onay bekle

Her adımda üretim koduna geçmeden önce çalışan bir demo gösterilecek ve bir
sonraki adıma onay alınmadan geçilmeyecek.
