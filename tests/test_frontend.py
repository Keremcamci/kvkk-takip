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
        ["esc", "escAttr", "guvenliUrl", "kaynakEtiketi", "kararKart"], f"[kararKart({json.dumps(karar)})]"
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
        ["esc", "escAttr", "guvenliUrl", "kaynakEtiketi", "kararKart"], f"[kararKart({json.dumps(karar)})]"
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
        ["esc", "escAttr", "guvenliUrl", "kaynakEtiketi", "kararKart"],
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
        ["esc", "escAttr", "guvenliUrl", "kaynakEtiketi", "kararKart"], f"[kararKart({json.dumps(karar)})]"
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
        ["esc", "escAttr", "guvenliUrl", "kaynakEtiketi", "kararKart"], f"[kararKart({json.dumps(karar)})]"
    )
    assert BeautifulSoup(html, "html.parser").select_one("span.kaynak-rozet") is None


# --- 3. Kaynak sayısı özeti ---------------------------------------------
#
# Bulgu: varsayılan "genel" profili yalnızca "genel" etiketli kararları
# gösteriyor; BDDK/SPK kararlarının hepsi "finans" etiketlendiği için
# --scrape sonrası tarayıcıyı açan kullanıcı 20 yeni kararın varlığına dair
# HİÇBİR iz görmüyordu. Çözüm: profilden bağımsız, her zaman görünen bir
# kaynak sayısı satırı.


def test_source_has_kaynak_ozet_element_and_uses_textContent():
    """KAYNAK seviyesi: eleman var mı ve textContent ile mi yazılıyor.

    innerHTML DEĞİL: metin saf sayı + sabit kaynak adlarından oluşsa da
    kaçırma gerektirmeyen bir yol seçmek bu satırı gelecekteki içerik
    değişikliklerine karşı da güvenli tutar.
    """
    kaynak = _kaynak()
    assert 'id="kaynak-ozet"' in kaynak
    assert "kaynakOzetEl.textContent = kaynakOzetMetni(veri.kaynak_sayilari)" in kaynak
    assert "kaynakOzetEl.innerHTML" not in kaynak


def test_source_updates_kaynak_ozet_inside_yukle():
    """Özet, `son_guncelleme` ile aynı yerde — yani her yukle() çağrısında
    (profil değişince de) güncellenmeli, yalnızca ilk yüklemede değil."""
    yukle_kaynagi = _js_fonksiyonu(_kaynak(), "yukle")
    assert "kaynakOzetEl.textContent" in yukle_kaynagi
    assert "sonGuncellemeEl.textContent" in yukle_kaynagi
    # Erken `return` (boş liste dalı) özet satırını atlamamalı: sayı
    # satırının asıl işe yaradığı durum tam da listenin boş olduğu durum.
    assert yukle_kaynagi.index("kaynakOzetEl.textContent") < yukle_kaynagi.index("return;")


@node_gerekli
def test_kaynakOzetMetni_lists_three_sources_in_fixed_order():
    """Sözlük SQLite'tan alfabetik (bddk, kvkk, spk) gelir; gösterim sırası
    yine de KVKK, BDDK, SPK olmalı. (Dördüncü kaynak Resmi Gazete burada
    bilerek verilmiyor — "bilinen 4 kaynaktan 3'ü mevcut" senaryosu;
    dördünün birlikte sırası için bkz.
    test_kaynakOzetMetni_includes_resmi_gazete_in_fixed_order.)"""
    (metin,) = _node_calistir(
        ["kaynakOzetMetni", "kaynakEtiketi"],
        '[kaynakOzetMetni({"bddk": 10, "kvkk": 8, "spk": 10})]',
    )
    assert metin == "Toplam: 8 KVKK, 10 BDDK, 10 SPK karar takip ediliyor."


@node_gerekli
def test_kaynakOzetMetni_omits_sources_with_no_kararlar():
    """ASIL DAVRANIŞ: taranmamış kaynak "0 BDDK" olarak GÖSTERİLMEZ,
    tamamen atlanır."""
    yalniz_kvkk, sifir_bddk, kvkk_spk = _node_calistir(
        ["kaynakOzetMetni", "kaynakEtiketi"],
        '[kaynakOzetMetni({"kvkk": 8}), '
        'kaynakOzetMetni({"kvkk": 8, "bddk": 0}), '
        'kaynakOzetMetni({"kvkk": 8, "spk": 10})]',
    )
    assert yalniz_kvkk == "Toplam: 8 KVKK karar takip ediliyor."
    assert sifir_bddk == "Toplam: 8 KVKK karar takip ediliyor."
    assert "BDDK" not in sifir_bddk and "0" not in sifir_bddk
    # Aradaki kaynak eksikse kalanların sırası bozulmamalı.
    assert kvkk_spk == "Toplam: 8 KVKK, 10 SPK karar takip ediliyor."


@node_gerekli
def test_kaynakOzetMetni_returns_empty_string_when_nothing_scraped():
    """Hiç veri yokken satır tamamen boş kalmalı — "Toplam: karar takip
    ediliyor." gibi bozuk bir cümle çıkmamalı."""
    sonuclar = _node_calistir(
        ["kaynakOzetMetni", "kaynakEtiketi"],
        "[kaynakOzetMetni({}), kaynakOzetMetni(undefined), kaynakOzetMetni(null), "
        'kaynakOzetMetni({"kvkk": 0, "bddk": 0, "spk": 0})]',
    )
    assert sonuclar == ["", "", "", ""]


@node_gerekli
def test_kaynakOzetMetni_still_shows_an_unknown_future_kaynak():
    """Bu özetin var olma sebebi "yeni kaynak sessizce görünmez oldu"
    bulgusu; sabit listede olmayan bir kaynak da aynı tuzağa düşmemeli.

    Yer tutucu olarak "danistay" kullanılır (Danıştay — henüz eklenmemiş,
    varsayımsal bir kaynak): gerçek "resmi_gazete" anahtarıyla
    karıştırılabilecek "resmigazete" (alt çizgisiz) artık kullanılmıyor.
    """
    (metin,) = _node_calistir(
        ["kaynakOzetMetni", "kaynakEtiketi"],
        '[kaynakOzetMetni({"kvkk": 8, "danistay": 5})]',
    )
    assert metin == "Toplam: 8 KVKK, 5 DANISTAY karar takip ediliyor."


@node_gerekli
def test_kararKart_renders_resmi_gazete_label_not_raw_uppercase():
    karar = {
        "baslik": "Karar",
        "tarih": "2026-01-01",
        "ozet": "özet",
        "yapilmasi_gerekenler": [],
        "aciliyet_var": False,
        "aciliyet_aciklama": "",
        "kaynak_url": "https://example.com/1",
        "kaynak": "resmi_gazete",
    }
    (html,) = _node_calistir(
        ["esc", "escAttr", "guvenliUrl", "kaynakEtiketi", "kararKart"],
        f"[kararKart({json.dumps(karar)})]",
    )
    span = BeautifulSoup(html, "html.parser").select_one("span.kaynak-rozet")
    assert span is not None
    assert span.get_text(strip=True) == "Resmi Gazete"


# --- 4. Ağ/parse hatası görünürlüğü -------------------------------------
#
# Bulgu: yukle() içinde try/catch yoktu. fetch() başarısız olur (ağ hatası,
# sunucu 500, bozuk JSON) ya da backend artık geçersiz profil için 400
# döndürürse (bkz. backend.py GECERLI_PROFILLER), önceki davranış:
# yakalanmamış bir promise reddi — sayfa sessizce eski/boş halinde kalır,
# kullanıcıya hiçbir şey gösterilmez.


def test_source_yukle_has_try_catch_around_fetch_and_parse():
    yukle_kaynagi = _js_fonksiyonu(_kaynak(), "yukle")
    assert "try {" in yukle_kaynagi
    assert "} catch" in yukle_kaynagi
    # Hem ağ hatası (fetch reddi) hem de sunucunun ürettiği hata durumu
    # (ör. 400/500) try bloğunun İÇİNDE olmalı, aksi halde yakalanmaz.
    try_govdesi = yukle_kaynagi.split("try {", 1)[1].split("} catch", 1)[0]
    assert "await fetch(" in try_govdesi
    assert "res.ok" in try_govdesi


def test_source_yukle_catch_block_shows_safe_error_via_textContent():
    """Hata mesajı innerHTML DEĞİL textContent ile yazılmalı — diğer kaçırma
    (escaping) bulgularıyla aynı disiplin: statik bir dizeyse bile
    textContent kullanmak bu satırı gelecekteki değişikliklere karşı da
    güvenli tutar.

    rsplit kullanılır (split değil): 429 dalı artık kendi iç try/catch'ini
    içeriyor (res.json() parse hatası için), yani "} catch" fonksiyon
    içinde artık İKİ kez geçiyor. DIŞ (asıl) catch bloğu her zaman SONUNCU
    "} catch" — bu yüzden en sondan bölmek gerekir."""
    yukle_kaynagi = _js_fonksiyonu(_kaynak(), "yukle")
    catch_govdesi = yukle_kaynagi.rsplit("} catch", 1)[1]
    assert "liste.textContent" in catch_govdesi
    assert "liste.innerHTML" not in catch_govdesi


@node_gerekli
def test_yukle_shows_backend_429_message_not_generic_reload_advice():
    """Bulgu: önceki davranışta `!res.ok` her zaman aynı statik "sayfayı
    yenile" mesajını üretiyordu — 429 (rate limit) için bu YANLIŞ tavsiye:
    yenilemek yeni bir istek daha yapar, durumu düzeltmez. Backend zaten
    JSON gövdesinde Türkçe bir mesaj gönderiyor (`{"error": "..."}"`); bu
    test, `yukle()`nin gerçekten bu mesajı okuyup kullanıcıya gösterdiğini
    (statik mesaj yerine) kanıtlar — `fetch` ve DOM elemanları mock'lanıp
    fonksiyon node ile GERÇEKTEN çalıştırılır."""
    # _js_fonksiyonu, arama "function <ad>(" dizesiyle başladığı için önündeki
    # "async " anahtar kelimesini dahil etmez (bu yardımcı fonksiyon şimdiye
    # kadar hep senkron fonksiyonlar için kullanıldı) — burada elle eklenir.
    yukle_kaynagi = "async " + _js_fonksiyonu(_kaynak(), "yukle")
    script = f"""
{yukle_kaynagi}
const profilSelect = {{ value: "genel" }};
const liste = {{ innerHTML: "", textContent: "" }};
const sonGuncellemeEl = {{ textContent: "" }};
const kaynakOzetEl = {{ textContent: "" }};
globalThis.fetch = async () => ({{
  ok: false,
  status: 429,
  json: async () => ({{ error: "test mesajı" }}),
}});
yukle().then(() => {{
  console.log(JSON.stringify(liste.textContent));
}});
"""
    sonuc = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert sonuc.returncode == 0, f"node hatası: {sonuc.stderr}"
    assert json.loads(sonuc.stdout) == "test mesajı"


@node_gerekli
def test_kaynakOzetMetni_includes_resmi_gazete_in_fixed_order():
    (metin,) = _node_calistir(
        ["kaynakOzetMetni", "kaynakEtiketi"],
        '[kaynakOzetMetni({"resmi_gazete": 5, "bddk": 10, "kvkk": 8, "spk": 10})]',
    )
    assert metin == "Toplam: 8 KVKK, 10 BDDK, 10 SPK, 5 Resmi Gazete karar takip ediliyor."
