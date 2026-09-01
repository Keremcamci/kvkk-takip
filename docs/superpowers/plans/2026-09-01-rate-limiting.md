# API Rate Limiting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/api/kararlar` endpoint'ine IP bazlı rate limiting eklemek (dakikada 30 istek), test suite'i etkilemeden.

**Architecture:** `Flask-Limiter` kütüphanesi `backend.py`'ye eklenir, `/api/kararlar` rotasına `@limiter.limit("30 per minute")` dekoratörü uygulanır, 429 yanıtı projenin mevcut JSON hata formatına uyacak şekilde özelleştirilir. `tests/conftest.py`'ye limiter state'ini her testten önce sıfırlayan bir autouse fixture eklenir (test hermetikliği için — bkz. Global Constraints).

**Tech Stack:** Python, Flask, Flask-Limiter (yeni bağımlılık), `pytest`.

## Global Constraints

- Limit: dakikada 30 istek, IP bazlı (`flask_limiter.util.get_remote_address`).
- Sadece `/api/kararlar` — `/` rotası kapsam dışı.
- Storage backend açıkça `"memory://"` olarak belirtilir (Flask-Limiter'ın storage belirtilmeden kullanılmasının ürettiği `UserWarning`'i önlemek için — test çıktısı kirlenmemeli).
- 429 yanıtı `{"error": "..."}"` JSON formatında olur (mevcut profil-doğrulama 400 hatasıyla aynı desen).
- `headers_enabled=True` ile `Retry-After` header'ı 429 yanıtlarında bulunur.
- **Kritik**: Flask-Limiter state'i process boyunca (`app` singleton'ında) kalıcıdır. Rate-limit testi limiti bilerek aşacağı için, bu state diğer testlere sızmaması adına `tests/conftest.py`'ye HER testten önce `limiter.reset()` çağıran autouse bir fixture eklenmelidir — aksi halde test sırasına bağlı, kırılgan başarısızlıklar oluşur.

---

### Task 1: Rate limiting ekle + test hermetikliğini koru

**Files:**
- Modify: `requirements.txt` (yeni bağımlılık)
- Modify: `backend.py` (limiter kurulumu + route dekoratörü + 429 handler)
- Modify: `tests/conftest.py` (yeni autouse fixture)
- Modify: `tests/test_backend.py` (yeni testler)

**Interfaces:**
- Produces: `backend.limiter` (modül seviyesinde bir `flask_limiter.Limiter` nesnesi — `tests/conftest.py`'nin `limiter.reset()` çağırabilmesi için erişilebilir olmalı)

- [ ] **Step 1: Bağımlılığı ekle ve kur**

`requirements.txt`'ye ekle (dosyanın sonuna, mevcut sıralamayı bozmadan):

```
flask-limiter>=3.5
```

Sonra kur:

```bash
pip install flask-limiter
```

(venv aktifse `pip install -r requirements.txt` de çalıştırılabilir, ama sadece yeni paketi kurmak için tek başına `pip install flask-limiter` yeterli ve daha hızlı.)

- [ ] **Step 2: Write the failing tests**

`tests/test_backend.py` dosyasının sonuna ekle:

```python
def test_api_kararlar_allows_up_to_rate_limit():
    client = backend.app.test_client()
    for _ in range(30):
        response = client.get("/api/kararlar")
        assert response.status_code == 200


def test_api_kararlar_returns_429_after_exceeding_rate_limit():
    client = backend.app.test_client()
    for _ in range(30):
        client.get("/api/kararlar")
    response = client.get("/api/kararlar")
    assert response.status_code == 429
    assert "error" in response.get_json()


def test_api_kararlar_429_response_includes_retry_after_header():
    client = backend.app.test_client()
    for _ in range(30):
        client.get("/api/kararlar")
    response = client.get("/api/kararlar")
    assert "Retry-After" in response.headers
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_backend.py -k rate_limit -v`
Expected: FAIL — `/api/kararlar` henüz limitlenmediği için 31 istek de `200` dönüyor, `test_api_kararlar_returns_429_after_exceeding_rate_limit` ve `test_api_kararlar_429_response_includes_retry_after_header` başarısız olmalı (`test_api_kararlar_allows_up_to_rate_limit` zaten geçer, bu normal — henüz limit yok).

- [ ] **Step 4: `tests/conftest.py`'ye limiter reset fixture'ı ekle**

Dosyanın başına `import backend` ekle (mevcut `import db`'nin yanına), dosyanın sonuna ekle:

```python
@pytest.fixture(autouse=True)
def limiter_sifirla():
    """Flask-Limiter'ın rate-limit state'i process boyunca (tek `app`
    singleton'ında) kalıcıdır. Rate-limit testi limiti bilerek aşacağı
    için, bu state sıfırlanmazsa diğer /api/kararlar testlerine sızıp
    onları da 429'a düşürebilir — test sırasına bağlı, kırılgan bir hata
    sınıfı. Her testten önce sayaçları sıfırlamak bunu önler."""
    backend.limiter.reset()
    yield
```

- [ ] **Step 5: `backend.py`'ye rate limiting ekle**

İmportlara ekle (mevcut `from flask import ...` satırının altına):

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
```

`app = Flask(__name__, static_folder=None)` satırından hemen sonra ekle:

```python
limiter = Limiter(get_remote_address, app=app, storage_uri="memory://", headers_enabled=True)
```

`_guvenlik_basliklari_ekle` fonksiyonundan sonra, `index()` rotasından önce ekle:

```python
@app.errorhandler(429)
def _rate_limit_asildi(e):
    return jsonify({"error": "Çok fazla istek gönderildi. Lütfen biraz sonra tekrar deneyin."}), 429
```

`@app.route("/api/kararlar")` satırının hemen altına (fonksiyon tanımından önce) ekle:

```python
@limiter.limit("30 per minute")
```

Sonuç olarak `api_kararlar` fonksiyonunun üstü şöyle görünmeli:

```python
@app.route("/api/kararlar")
@limiter.limit("30 per minute")
def api_kararlar():
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_backend.py -v`
Expected: PASS (tüm dosya)

Sonra tüm test paketini çalıştır (mevcut `/api/kararlar` testlerinin — `test_backend.py` ve `test_integration.py`'deki — yeni limiter'dan etkilenmediğini doğrulamak için):

Run: `python -m pytest -q`
Expected: PASS (tüm proje, regresyon yok, çıktı temiz — `UserWarning` gibi gürültü olmamalı)

- [ ] **Step 7: Commit**

```bash
git add requirements.txt backend.py tests/conftest.py tests/test_backend.py
git commit -m "feat(backend): add rate limiting to /api/kararlar"
```

---

## Uygulama Sırası

Tek görev — küçük, tek dosyaya odaklı bir özellik (bir route dekoratörü + bir
error handler + bir bağımlılık). Ayrı faz kontrol noktalarına gerek yok.
