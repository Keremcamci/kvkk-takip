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

from pathlib import Path
from unittest.mock import patch

import backend
import classifier
import db
import scraper

FIXTURE = Path(__file__).parent / "fixtures" / "kvkk_kararlari_sample.html"

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
    with patch("scraper.fetch_page", return_value=html):
        scraper.scrape_and_store(conn)
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
    with patch("scraper.fetch_page", return_value=html):
        scraper.scrape_and_store(conn)

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
