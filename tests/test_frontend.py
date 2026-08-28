"""index.html içindeki istemci tarafı kaçırma (escaping) mantığının testleri.

İki katman var:

1. Kaynak seviyesi kontrol — dosyanın metnine bakar. Ucuz ve her ortamda
   çalışır, ama SADECE ilgili kodun hâlâ orada olduğunu kanıtlar, çalışma
   zamanı davranışını kanıtlamaz.
2. Davranış kontrolü — `node` varsa, index.html'den ilgili fonksiyonları
   çıkarıp GERÇEKTEN çalıştırır ve çıktısını doğrular. `node` yoksa atlanır
   (katkıcıların Node kurmak zorunda kalmaması için).

Bu ayrım bilinçli: eski test yalnızca `esc(karar.kaynak_url)` metninin
sayfada geçtiğini kontrol ediyordu ve tırnak kaçırma açığı canlıyken bile
geçiyordu — yani gerçek bir regresyon koruması değildi.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

INDEX_HTML = Path(__file__).resolve().parent.parent / "index.html"
NODE = shutil.which("node")
node_gerekli = pytest.mark.skipif(NODE is None, reason="node bulunamadı")


def _kaynak() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _js_fonksiyonu(kaynak: str, ad: str) -> str:
    """index.html'den `function <ad>(...) { ... }` bloğunu süslü parantez
    sayarak çıkarır (şablon literallerindeki ${...} dengeli olduğu için
    sayım bozulmaz)."""
    baslangic = kaynak.index(f"function {ad}(")
    derinlik = 0
    for i in range(kaynak.index("{", baslangic), len(kaynak)):
        if kaynak[i] == "{":
            derinlik += 1
        elif kaynak[i] == "}":
            derinlik -= 1
            if derinlik == 0:
                return kaynak[baslangic : i + 1]
    raise AssertionError(f"{ad} fonksiyonunun sonu bulunamadı")


def _node_calistir(fonksiyon_adlari, ifade: str):
    """Verilen fonksiyonları index.html'den çıkarıp node ile çalıştırır ve
    `ifade`nin JSON'a çevrilmiş sonucunu döner."""
    kaynak = _kaynak()
    tanimlar = "\n".join(_js_fonksiyonu(kaynak, ad) for ad in fonksiyon_adlari)
    script = f"{tanimlar}\nconsole.log(JSON.stringify({ifade}));"
    sonuc = subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, timeout=30
    )
    assert sonuc.returncode == 0, f"node hatası: {sonuc.stderr}"
    return json.loads(sonuc.stdout)


# --- 1. Kaynak seviyesi kontroller -------------------------------------


def test_escAttr_source_escapes_double_quotes():
    """KAYNAK seviyesi: escAttr tanımı çift tırnak kaçırmayı içeriyor mu.

    Bu test yalnızca kodun orada olduğunu gösterir, çalıştığını değil —
    davranış kanıtı aşağıdaki node testlerinde.
    """
    escAttr_kaynagi = _js_fonksiyonu(_kaynak(), "escAttr")
    assert '"&quot;"' in escAttr_kaynagi
    assert '/"/g' in escAttr_kaynagi


def test_source_uses_escAttr_not_esc_in_attribute_contexts():
    kaynak = _kaynak()
    assert 'title="${escAttr(karar.aciliyet_aciklama)}"' in kaynak
    assert 'title="${esc(karar.aciliyet_aciklama)}"' not in kaynak
    assert 'href="${escAttr(url)}"' in kaynak
    assert 'href="${esc(karar.kaynak_url)}"' not in kaynak
    assert 'href="${karar.kaynak_url}"' not in kaynak


# --- 2. Davranış kontrolleri (node ile gerçek çalıştırma) ---------------


@node_gerekli
def test_escAttr_escapes_quotes_and_esc_does_not():
    girdi = '" onmouseover="alert(1)'
    esc_cikti, escAttr_cikti = _node_calistir(
        ["esc", "escAttr"], f"[esc({json.dumps(girdi)}), escAttr({json.dumps(girdi)})]"
    )
    # Bulgunun özü: esc() tırnağı OLDUĞU GİBİ bırakır.
    assert '"' in esc_cikti
    # escAttr() bırakmaz — öznitelik bağlamında güvenli.
    assert '"' not in escAttr_cikti
    assert escAttr_cikti == "&quot; onmouseover=&quot;alert(1)"


@node_gerekli
def test_escAttr_escapes_all_five_html_metacharacters():
    (cikti,) = _node_calistir(["escAttr"], """[escAttr("&<>\\"'")]""")
    assert cikti == "&amp;&lt;&gt;&quot;&#39;"


SALDIRI_DIZESI = '" onmouseover="alert(1)'


@node_gerekli
def test_kararKart_quote_in_aciliyet_aciklama_does_not_inject_attribute():
    """Gerçek karar başlıklarında " karakteri var; title özniteliğinden
    kaçıp yeni bir öznitelik enjekte edilememeli.

    Doğrulama HTML metninde dize arayarak değil, üretilen HTML'i PARSE edip
    span'ın gerçek öznitelik listesine bakarak yapılır — tarayıcının göreceği
    şey budur.
    """
    karar = {
        "baslik": 'Veri Sorumluları Sicilin" hakkında',
        "tarih": "2026-01-01",
        "ozet": "özet",
        "yapilmasi_gerekenler": [],
        "aciliyet_var": True,
        "aciliyet_aciklama": SALDIRI_DIZESI,
        "kaynak_url": "https://example.com/1",
    }
    (html,) = _node_calistir(
        ["esc", "escAttr", "guvenliUrl", "kararKart"], f"[kararKart({json.dumps(karar)})]"
    )
    span = BeautifulSoup(html, "html.parser").select_one("span.aciliyet")
    assert span is not None
    assert set(span.attrs) == {"class", "title"}, f"enjekte edilmiş öznitelik: {span.attrs}"
    # Değer bozulmadan, tek bir öznitelik değeri olarak taşınmış olmalı.
    assert span["title"] == SALDIRI_DIZESI


@node_gerekli
def test_esc_output_in_attribute_would_inject_negative_control():
    """Yukarıdaki testin boşuna geçmediğinin kanıtı: aynı doğrulama, eski
    (hatalı) `esc()` çıktısı bir özniteliğe konduğunda BAŞARISIZ olur —
    yani test gerçekten enjeksiyonu yakalayabiliyor."""
    (esc_cikti,) = _node_calistir(["esc"], f"[esc({json.dumps(SALDIRI_DIZESI)})]")
    hatali_html = f'<span class="aciliyet" title="{esc_cikti}">Aciliyet</span>'
    span = BeautifulSoup(hatali_html, "html.parser").select_one("span.aciliyet")
    assert "onmouseover" in span.attrs
    assert span["title"] == ""


@node_gerekli
def test_kararKart_omits_link_for_javascript_scheme_url():
    karar = {
        "baslik": "Karar",
        "tarih": "2026-01-01",
        "ozet": "özet",
        "yapilmasi_gerekenler": [],
        "aciliyet_var": False,
        "aciliyet_aciklama": "",
        "kaynak_url": "javascript:alert(1)",
    }
    (html,) = _node_calistir(
        ["esc", "escAttr", "guvenliUrl", "kararKart"], f"[kararKart({json.dumps(karar)})]"
    )
    assert "javascript:" not in html
    assert "<a" not in html
    # Kart yine de render edilmeli, sadece link düşmeli.
    assert "Karar" in html


@node_gerekli
def test_kararKart_renders_link_for_http_and_https_urls():
    def kart(url):
        karar = {
            "baslik": "Karar",
            "tarih": "2026-01-01",
            "ozet": "özet",
            "yapilmasi_gerekenler": [],
            "aciliyet_var": False,
            "aciliyet_aciklama": "",
            "kaynak_url": url,
        }
        return json.dumps(karar)

    https_html, http_html = _node_calistir(
        ["esc", "escAttr", "guvenliUrl", "kararKart"],
        f"[kararKart({kart('https://example.com/a?x=1&y=2')}), "
        f"kararKart({kart('http://example.com/b')})]",
    )
    assert 'href="https://example.com/a?x=1&amp;y=2"' in https_html
    assert 'href="http://example.com/b"' in http_html


@node_gerekli
def test_guvenliUrl_rejects_non_http_schemes():
    sonuclar = _node_calistir(
        ["guvenliUrl"],
        '["javascript:alert(1)", " javascript:alert(1)", "JaVaScRiPt:alert(1)", '
        '"data:text/html,<script>", "//example.com", "", null, '
        '"https://ok.example", "  HTTPS://ok.example  "].map(guvenliUrl)',
    )
    assert sonuclar[:7] == [None] * 7
    assert sonuclar[7] == "https://ok.example"
    assert sonuclar[8] == "HTTPS://ok.example"


@node_gerekli
def test_kararKart_renders_kaynak_rozeti():
    karar = {
        "baslik": "Karar",
        "tarih": "2026-01-01",
        "ozet": "özet",
        "yapilmasi_gerekenler": [],
        "aciliyet_var": False,
        "aciliyet_aciklama": "",
        "kaynak_url": "https://example.com/1",
        "kaynak": "bddk",
    }
    (html,) = _node_calistir(
        ["esc", "escAttr", "guvenliUrl", "kararKart"], f"[kararKart({json.dumps(karar)})]"
    )
    span = BeautifulSoup(html, "html.parser").select_one("span.kaynak-rozet")
    assert span is not None
    assert span.get_text(strip=True) == "BDDK"


@node_gerekli
def test_kararKart_omits_kaynak_rozeti_when_kaynak_missing():
    karar = {
        "baslik": "Karar",
        "tarih": "2026-01-01",
        "ozet": "özet",
        "yapilmasi_gerekenler": [],
        "aciliyet_var": False,
        "aciliyet_aciklama": "",
        "kaynak_url": "https://example.com/1",
    }
    (html,) = _node_calistir(
        ["esc", "escAttr", "guvenliUrl", "kararKart"], f"[kararKart({json.dumps(karar)})]"
    )
    assert BeautifulSoup(html, "html.parser").select_one("span.kaynak-rozet") is None
