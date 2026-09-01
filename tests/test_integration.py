"""Uçtan uca kompozisyon testleri: scraper -> db -> classifier -> API.

Neden ayrı bir dosya: her görevin kendi birim testleri geçiyordu, çünkü her
testin sahte verisi zaten doğru şekilde farklılaşmıştı. Gerçek uçtan uca
veride ise LLM 10/10 kararı "genel" etiketledi ve profil filtresi tamamen
işlevsiz kaldı — her profil aynı listeyi döndürdü. Bu dosya tam da o sınıfı
yakalar: parçaları BİRLİKTE çalıştırır ve iki farklı profilin FARKLI sonuç
kümeleri döndürdüğünü doğrular.

Sınıflandırıcı sahtedir (gerçek Anthropic API'ye çıkılmaz: testte anahtar
garantisi ve tekrarlanabilir çıktı yok).
"""

import json
from pathlib import Path
from unittest.mock import patch

import backend
import classifier
import db
from scrapers import bddk, kvkk, resmi_gazete, spk

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "kvkk_kararlari_sample.html"
BDDK_FIXTURE = FIXTURES / "bddk_kararlar_sample.html"
SPK_FIXTURE = FIXTURES / "spk_kararlar_sample.json"
RESMI_GAZETE_FIXTURE = FIXTURES / "resmi_gazete_kararlar_sample.json"

# Gerçekçi, FARKLILAŞMIŞ etiketler — fixture'daki üç gerçek karar başlığına
# anahtar kelimeyle eşlenir.
SAHTE_ETIKETLER = {
    "Sadakat Kart": ["e-ticaret"],
    "Özel Nitelikli": ["saglik"],
    "Köy Tüzel": ["genel"],
}


class SahteToolUseBlock:
    def __init__(self, input_):
        self.type = "tool_use"
        self.name = "karar_sinifla"
        self.input = input_


class SahteResponse:
    def __init__(self, input_):
        self.content = [SahteToolUseBlock(input_)]


class SahteMessages:
    """Prompt'taki başlığa bakarak etiket seçen sahte Anthropic client."""

    def __init__(self, etiket_haritasi, varsayilan=None):
        self.etiket_haritasi = etiket_haritasi
        self.varsayilan = varsayilan
        self.prompts = []

    def create(self, **kwargs):
        prompt = kwargs["messages"][0]["content"]
        self.prompts.append(prompt)
        sektorler = self.varsayilan
        for anahtar, etiketler in self.etiket_haritasi.items():
            if anahtar in prompt:
                sektorler = etiketler
                break
        if sektorler is None:
            raise AssertionError(f"Beklenmeyen karar prompt'u: {prompt[:120]}")
        return SahteResponse({
            "sektorler": sektorler,
            "ozet": "Sahte özet.",
            "yapilmasi_gerekenler": ["Madde 1"],
            "aciliyet_var": False,
            "aciliyet_aciklama": "",
        })


class SahteClient:
    def __init__(self, etiket_haritasi, varsayilan=None):
        self.messages = SahteMessages(etiket_haritasi, varsayilan)


def _pipeline_calistir(conn, client) -> dict:
    """scraper + classifier'ı gerçek fixture HTML'i üzerinde uçtan uca koşar."""
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.kvkk.fetch_page", return_value=html), \
         patch("scrapers.kvkk.tammetin.pdf_metni_cek", return_value=None), \
         patch("scrapers.kvkk.tammetin.kvkk_sayfa_metni_cek", return_value=None):
        kvkk.scrape_and_store(conn)
    return classifier.classify_pending(
        conn, client=client, model="test-model", sleep_fn=lambda s: None
    )


def _basliklar(kararlar) -> set:
    return {k["baslik"] for k in kararlar}


def test_pipeline_differentiated_tags_produce_different_results_per_profil(conn):
    """ASIL REGRESYON KORUMASI: farklılaşmış etiketlerle iki profil AYNI
    listeyi döndürmemeli."""
    sonuc = _pipeline_calistir(conn, SahteClient(SAHTE_ETIKETLER))
    assert sonuc == {"basarili": 3, "basarisiz": 0, "kalici_hata": 0}

    e_ticaret = _basliklar(db.get_kararlar_by_profil(conn, "e-ticaret"))
    saglik = _basliklar(db.get_kararlar_by_profil(conn, "saglik"))
    finans = _basliklar(db.get_kararlar_by_profil(conn, "finans"))

    assert e_ticaret != saglik, "e-ticaret ve sağlık profilleri aynı listeyi döndürdü"
    assert e_ticaret != finans
    assert len(e_ticaret) == 2  # kendi kararı + genel
    assert len(saglik) == 2
    assert len(finans) == 1  # yalnızca genel

    # Her profil kendi sektör kararını görmeli, diğerininkini görmemeli.
    sadakat = next(b for b in e_ticaret if "Sadakat Kart" in b)
    ozel_nitelikli = next(b for b in saglik if "Özel Nitelikli" in b)
    assert sadakat not in saglik
    assert ozel_nitelikli not in e_ticaret

    # "genel" kararı herkeste olmalı.
    koy = next(b for b in finans if "Köy Tüzel" in b)
    assert koy in e_ticaret and koy in saglik


def test_pipeline_all_genel_tags_collapse_every_profil_to_one_list(conn):
    """Bulgunun kendisini belgeler: model her karara "genel" derse filtre
    çöker ve TÜM profiller birebir aynı listeyi döndürür. Bu davranış
    `get_kararlar_by_profil` açısından doğrudur — hata sınıflandırma
    tarafındadır, bu yüzden düzeltme classifier prompt'unda yapıldı."""
    _pipeline_calistir(conn, SahteClient({}, varsayilan=["genel"]))

    profiller = ["genel", "e-ticaret", "finans", "saglik", "egitim"]
    listeler = [_basliklar(db.get_kararlar_by_profil(conn, p)) for p in profiller]
    assert all(liste == listeler[0] for liste in listeler)
    assert len(listeler[0]) == 3


def test_classifier_prompt_carries_restrictive_genel_rule_to_the_model(conn):
    """Prompt kuralının gerçekten API'ye giden mesajda olduğunu doğrular —
    yalnızca sabitte durduğunu değil."""
    client = SahteClient(SAHTE_ETIKETLER)
    _pipeline_calistir(conn, client)
    assert len(client.messages.prompts) == 3
    for prompt in client.messages.prompts:
        assert classifier.SEKTOR_ETIKETLEME_KURALI in prompt


def test_api_returns_different_kararlar_for_different_profil(monkeypatch, tmp_path):
    """Aynı farklılaşma HTTP katmanında da görünmeli (kullanıcının gördüğü yol)."""
    db_path = tmp_path / "test_integration.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)

    conn = db.get_connection()
    db.init_db(conn)
    _pipeline_calistir(conn, SahteClient(SAHTE_ETIKETLER))
    conn.close()

    client = backend.app.test_client()
    e_ticaret = client.get("/api/kararlar?profil=e-ticaret").get_json()["kararlar"]
    saglik = client.get("/api/kararlar?profil=saglik").get_json()["kararlar"]

    assert _basliklar(e_ticaret) != _basliklar(saglik)
    assert all("saglik" not in k["sektorler"] for k in e_ticaret)
    assert all("e-ticaret" not in k["sektorler"] for k in saglik)


def test_reset_failed_unsticks_kararlar_and_pipeline_recovers(conn):
    """API anahtarı hatalıyken kalıcı hataya düşen kararlar, anahtar
    düzeltilip --reset-failed çalıştırıldıktan sonra sınıflandırılabilmeli."""
    html = FIXTURE.read_text(encoding="utf-8")
    with patch("scrapers.kvkk.fetch_page", return_value=html), \
         patch("scrapers.kvkk.tammetin.pdf_metni_cek", return_value=None), \
         patch("scrapers.kvkk.tammetin.kvkk_sayfa_metni_cek", return_value=None):
        kvkk.scrape_and_store(conn)

    class BozukClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("401 geçersiz api anahtarı")

    for _ in range(3):
        classifier.classify_pending(
            conn, client=BozukClient(), model="test-model", sleep_fn=lambda s: None
        )
    assert db.get_pending_kararlar(conn) == []
    assert db.get_kararlar_by_profil(conn, "genel") == []

    assert db.reset_failed_kararlar(conn) == 3
    assert len(db.get_pending_kararlar(conn)) == 3

    _sonuc = classifier.classify_pending(
        conn, client=SahteClient(SAHTE_ETIKETLER), model="test-model", sleep_fn=lambda s: None
    )
    assert _sonuc["basarili"] == 3
    assert _basliklar(db.get_kararlar_by_profil(conn, "e-ticaret")) != _basliklar(
        db.get_kararlar_by_profil(conn, "saglik")
    )


# --- Dört kaynağın BİRLİKTE kompozisyonu ---------------------------------
#
# Yukarıdaki testlerin hepsi yalnızca KVKK fixture'ını kullanıyordu. Önceki
# bir gözden geçirmenin bulgusu tam da bu boşluktan geçti: her görevin
# kendi sahte verisi elle farklılaştırılmıştı, bu yüzden hiçbir test
# "kaynaklar birlikte tarandığında profil filtresi kullanıcıya ne
# gösterir?" sorusunu sormadı. Canlı veride BDDK ve SPK kararlarının
# TAMAMI "finans" etiketlendi (doğru sınıflandırma — ikisi de finansal
# düzenleyici), dolayısıyla varsayılan "genel" profilini açan kullanıcı 20
# yeni kararın hiçbirini görmedi.
#
# Bu branch dördüncü kaynağı (Resmi Gazete) ekliyor ve AYNI kompozisyon
# boşluğunu bir kez daha üretiyor: sınıflandırıcının izin verdiği boş
# `sektorler: []` durumu (karar hiçbir işletme sektörünü ilgilendirmiyor)
# ilk kez burada, dört kaynak BİRLİKTE koşulduğunda test ediliyor.

# Gerçek dağılımın birebir taklidi: KVKK ve Resmi Gazete başlıkları anahtar
# kelimeyle farklılaşır, BDDK/SPK ise kurum adından yakalanıp "finans"
# etiketlenir.
UC_KAYNAK_ETIKETLERI = {
    "Sadakat Kart": ["e-ticaret"],
    "Özel Nitelikli": ["saglik"],
    "Köy Tüzel": ["genel"],
    # classifier.build_prompt kurum adını prompt'a yazar (KURUM_ADLARI).
    "BDDK (Bankacılık": ["finans"],
    "SPK (Sermaye": ["finans"],
    # tests/fixtures/resmi_gazete_kararlar_sample.json: 2 ilgili karar + 1
    # bilerek alakasız karar (boş-dizi kuralını uçtan uca tetiklemek için).
    "İstihdamı Koruma": ["egitim"],
    "Özel Hastaneler": ["saglik"],
    "Askeri Yasak Bölge": [],
}

# tests/fixtures içindeki gerçek kayıt sayıları. SPK fixture'ında 3 kayıt
# var ama biri "Tebliğ" türünde; spk.GECERLI_TURLER onu tarama sırasında
# eler, yani sınıflandırmaya hiç ulaşmaz. Resmi Gazete fixture'ındaki 3
# kaydın hepsi taramadan geçer (tür bazlı eleme yok); biri (Askeri Yasak
# Bölge) sınıflandırmada boş `sektorler: []` alır ama yine de bu sayıma
# dahildir — bkz. aşağıdaki boş-dizi testleri.
BEKLENEN_KAYNAK_SAYILARI = {"kvkk": 3, "bddk": 3, "spk": 2, "resmi_gazete": 3}


def _uc_kaynak_pipeline_calistir(conn, client):
    """Dört fixture'ı da AYNI conn'a tarar, sonra hepsini sınıflandırır.
    tammetin çağrıları burada patch'lenerek gerçek ağa çıkılması
    engellenir; bu artık conftest.py'deki autouse
    gercek_aga_cikisi_engelle fixture'ı ile ikinci bir güvenlik
    katmanına da sahip (bir patch yanlışlıkla silinirse test sessizce
    gerçek bir siteye bağlanmak yerine anlaşılır bir hata ile başarısız
    olur), bu yüzden call_count assertion'larına artık gerek yok."""
    with patch("scrapers.kvkk.fetch_page", return_value=FIXTURE.read_text(encoding="utf-8")), \
         patch("scrapers.kvkk.tammetin.pdf_metni_cek", return_value=None), \
         patch("scrapers.kvkk.tammetin.kvkk_sayfa_metni_cek", return_value=None):
        kvkk.scrape_and_store(conn)
    with patch(
        "scrapers.bddk.fetch_page", return_value=BDDK_FIXTURE.read_text(encoding="utf-8")
    ), patch("scrapers.bddk.tammetin.pdf_metni_cek", return_value=None):
        bddk.scrape_and_store(conn)
    with patch(
        "scrapers.spk.fetch_veri",
        return_value=json.loads(SPK_FIXTURE.read_text(encoding="utf-8")),
    ), patch("scrapers.spk.tammetin.pdf_metni_cek", return_value=None):
        spk.scrape_and_store(conn)
    with patch(
        "scrapers.resmi_gazete.fetch_veri",
        return_value=json.loads(RESMI_GAZETE_FIXTURE.read_text(encoding="utf-8")),
    ), patch("scrapers.resmi_gazete._madde_url_bul", return_value=None):
        resmi_gazete.scrape_and_store(conn)
    sonuc = classifier.classify_pending(
        conn, client=client, model="test-model", sleep_fn=lambda s: None
    )
    return sonuc


def _kaynaklar(kararlar) -> set:
    return {k["kaynak"] for k in kararlar}


def test_all_three_sources_compose_through_classification_and_profil_filter(conn):
    """Dört kaynak birlikte tarandığında pipeline uçtan uca tutarlı olmalı."""
    sonuc = _uc_kaynak_pipeline_calistir(conn, SahteClient(UC_KAYNAK_ETIKETLERI))

    # 3 (kvkk) + 3 (bddk) + 2 (spk; "Tebliğ" taramada elendi) + 3 (resmi_gazete) = 11
    assert sonuc == {"basarili": 11, "basarisiz": 0, "kalici_hata": 0}
    assert sum(BEKLENEN_KAYNAK_SAYILARI.values()) == 11

    # Kaynak başına sayım (arayüzdeki her zaman görünen özet satırının verisi).
    assert db.get_kaynak_sayilari(conn) == BEKLENEN_KAYNAK_SAYILARI

    # "finans" profili artık YALNIZCA kvkk değil, üç kaynağı da görmeli.
    finans = db.get_kararlar_by_profil(conn, "finans")
    assert _kaynaklar(finans) == {"kvkk", "bddk", "spk"}
    # 3 bddk + 2 spk ("finans") + 1 kvkk ("genel" olan Köy Tüzel kararı)
    assert len(finans) == 6
    assert len([k for k in finans if k["kaynak"] == "bddk"]) == 3
    assert len([k for k in finans if k["kaynak"] == "spk"]) == 2

    # ASIL YENİ DAVRANIŞ: "sektorler: []" ile sınıflandırılan bir karar
    # (Resmi Gazete'nin Askeri Yasak Bölge kararı) BİLEREK hiçbir profilde
    # görünmemeli — bu bir hata değil, bu branch'ın getirdiği kuralın ta
    # kendisi. Eskiden burada "hiçbir karar kaybolmamalı" diye TEK bir
    # toplam sayı kontrol ediliyordu (len(gorunen) == 8); o iddia artık
    # YANLIŞ, çünkü bu branch kasıtlı olarak bir kararı görünmez kılıyor.
    # Doğru iddia iki parçalıdır ve ikisi de ayrı ayrı doğrulanır:
    profiller = ["genel", "e-ticaret", "finans", "saglik", "egitim"]
    tum_gorunen_kararlar = [
        k for p in profiller for k in db.get_kararlar_by_profil(conn, p)
    ]
    gorunen_id = {k["id"] for k in tum_gorunen_kararlar}
    gorunen_resmi_gazete_id = {
        k["id"] for k in tum_gorunen_kararlar if k["kaynak"] == "resmi_gazete"
    }

    # (1) Boş-dizi kararın FİLTRELENMESİ: 11 kararın 10'u en az bir
    # profilde görünür; yalnızca askeri yasak bölge kararı hiçbir profilde
    # yok.
    assert len(gorunen_id) == 10
    # resmi_gazete'nin 3 kararından yalnızca 2'si (İstihdamı Koruma, Özel
    # Hastaneler) profillerin birleşiminde görünür; Askeri Yasak Bölge yok.
    assert len(gorunen_resmi_gazete_id) == 2

    # (2) Boş-dizi kararın SAYILMASI: profillerden düşse bile kaynak
    # özetinden düşmez — toplam resmi_gazete sayısı hâlâ 3'tür. Bu iddia
    # düşerse ya boş-dizi filtresi ya da kaynak sayacı bozulmuş demektir.
    assert db.get_kaynak_sayilari(conn)["resmi_gazete"] == 3


def test_default_genel_profil_hides_bddk_and_spk_but_kaynak_ozeti_does_not(conn):
    """ASIL BULGU: gerçek dağılımda varsayılan "genel" profili BDDK ve
    SPK'nın tamamını gizler — bu, filtrenin doğru çalışmasıdır, hata değil.
    Bu yüzden düzeltme filtreyi değil GÖRÜNÜRLÜĞÜ hedefler: kaynak sayısı
    özeti profilden bağımsızdır ve kullanıcıya bu kararların var olduğunu
    söyler.
    """
    _uc_kaynak_pipeline_calistir(conn, SahteClient(UC_KAYNAK_ETIKETLERI))

    genel = db.get_kararlar_by_profil(conn, "genel")
    assert _kaynaklar(genel) == {"kvkk"}, "senaryo kurgusu bozulmuş"
    assert len(genel) == 1

    # ...ama kaynak özeti, "genel" profilinde bile daha fazla kararın var
    # olduğunu gösterir. Bu iddia düşerse bulgu geri gelmiş demektir.
    sayilar = db.get_kaynak_sayilari(conn)
    assert sayilar["bddk"] == 3 and sayilar["spk"] == 2
    assert sum(sayilar.values()) - len(genel) == 10


def test_api_exposes_all_three_sources_via_kaynak_sayilari(monkeypatch, tmp_path):
    """Aynı görünürlük HTTP katmanında da olmalı (kullanıcının gördüğü yol):
    varsayılan profil tek karar döndürse bile yanıt üç kaynağı da bildirir."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_uc_kaynak.db")

    conn = db.get_connection()
    db.init_db(conn)
    _uc_kaynak_pipeline_calistir(conn, SahteClient(UC_KAYNAK_ETIKETLERI))
    conn.close()

    client = backend.app.test_client()
    varsayilan = client.get("/api/kararlar").get_json()
    assert varsayilan["kaynak_sayilari"] == BEKLENEN_KAYNAK_SAYILARI
    assert _kaynaklar(varsayilan["kararlar"]) == {"kvkk"}

    finans = client.get("/api/kararlar?profil=finans").get_json()
    assert finans["kaynak_sayilari"] == BEKLENEN_KAYNAK_SAYILARI
    assert _kaynaklar(finans["kararlar"]) == {"kvkk", "bddk", "spk"}
