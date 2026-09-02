# API Rate Limiting — Tasarım

**Tarih**: 2026-09-01
**Durum**: Onaylandı

## Amaç

Bir arkadaşın kod review'ında işaret edilen bulgu: `/api/kararlar` endpoint'inde
rate limiting yok. MVP'nin yerel/tek kullanıcılı kullanımı için sorun değil, ama
üstüne production'a taşınırsa endpoint kötüye kullanılabilir (döngüsel istek,
kazara sonsuz döngü, vb. — DB'yi gereksiz yere yorar).

## Kapsam

Sadece `/api/kararlar` — DB sorgusu yapan, en hassas endpoint. `/` (statik
sayfa) kapsam dışı, çok daha hafif ve spam riski düşük.

## Kütüphane Seçimi

`Flask-Limiter` (`requirements.txt`'ye `flask-limiter>=3.5` eklenir). El
yapımı bir limiter yerine bu tercih edildi: sliding-window/thread-safety/IP
çıkarımı gibi detayları kendimiz doğru yazıp test etmek bu küçük özellik için
gereksiz risk ve bakım yükü olurdu; Flask-Limiter iyi test edilmiş, standart
bir kütüphane.

## Uygulama

`backend.py`'ye:

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(get_remote_address, app=app, headers_enabled=True)


@app.errorhandler(429)
def _rate_limit_asildi(e):
    return jsonify({"error": "Çok fazla istek gönderildi. Lütfen biraz sonra tekrar deneyin."}), 429


@app.route("/api/kararlar")
@limiter.limit("30 per minute")
def api_kararlar():
    ...  # mevcut gövde değişmiyor
```

- Limit: **dakikada 30 istek**, IP bazlı (`get_remote_address`) — normal UI
  kullanımı (profil değiştirildikçe tek fetch) için bol, kötüye kullanımı
  sınırlıyor.
- 429 yanıtı projenin mevcut hata formatına uyuyor: `{"error": "..."}"`
  (profil doğrulamasındaki 400 hatasıyla aynı desen — bkz. `backend.py`
  `GECERLI_PROFILLER` kontrolü).
- `headers_enabled=True` ile `Retry-After`/`X-RateLimit-*` başlıkları da
  dönüyor — istemcinin ne zaman tekrar deneyebileceğini bilmesi için.

## Test Hermetikliği (kritik tasarım kararı)

Flask-Limiter'ın rate-limit state'i process boyunca (tek `app` singleton'ında)
kalıcıdır. Rate-limit testinin kendisi limiti bilerek aşacağı için (429'u
tetiklemek amacıyla 31 istek atması gerekir), bu state test suite'teki DİĞER
`/api/kararlar` testlerine (şu an 5 tane var: `test_backend.py`,
`test_integration.py`) sızıp onları da 429'a düşürebilir — test sırasına
bağlı, kırılgan bir hata sınıfı.

Çözüm: `tests/conftest.py`'ye `limiter.reset()` çağıran autouse bir fixture
eklenir — her testten önce rate-limit sayaçları sıfırlanır. Bu, projenin
zaten kullandığı "autouse fixture ile hermetiklik" desenine (gerçek ağ
çıkışını engelleyen socket-block fixture'ı gibi) birebir uygun.

## Test Planı

- 30. isteğin hâlâ `200` döndüğü (limit dahil, aşılmamış).
- 31. isteğin `429` + `{"error": "..."}"` JSON body döndüğü.
- 429 yanıtında `Retry-After` header'ının var olduğu.
- Mevcut `test_backend.py`/`test_integration.py` testlerinin
  `limiter.reset()` fixture'ı sayesinde etkilenmediği (bu, fixture'ın kendisi
  doğru çalışıyorsa zaten dolaylı olarak doğrulanır — testler sırasız
  çalıştırıldığında da geçmeye devam eder).

## Kapsam Dışı

- `/` rotası için rate limiting.
- Redis/harici storage backend — tek process'lik yerel Flask uygulaması için
  in-memory storage (Flask-Limiter varsayılanı) yeterli.
- Kullanıcı bazlı (auth'a dayalı) limit — uygulamada kimlik doğrulama yok,
  IP bazlı limit tek makul seçenek.
