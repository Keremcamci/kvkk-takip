import logging
from pathlib import Path

import pytest

import db
import classifier


class FakeAPIError(Exception):
    def __init__(self, status_code):
        super().__init__(f"fake api error {status_code}")
        self.status_code = status_code


class FakeToolUseBlock:
    def __init__(self, name, input_):
        self.type = "tool_use"
        self.name = name
        self.input = input_


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeMessages:
    def __init__(self, effects):
        self.effects = list(effects)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        effect = self.effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


class FakeClient:
    def __init__(self, effects):
        self.messages = FakeMessages(effects)


SUCCESS_INPUT = {
    "sektorler": ["e-ticaret", "genel"],
    "ozet": "Kısa özet.",
    "yapilmasi_gerekenler": ["Madde 1"],
    "aciliyet_var": False,
    "aciliyet_aciklama": "",
}


def _success_response():
    return FakeResponse([FakeToolUseBlock("karar_sinifla", SUCCESS_INPUT)])


def test_classify_karar_returns_tool_input_on_first_success():
    client = FakeClient([_success_response()])
    sonuc = classifier.classify_karar(client, "Başlık", "2026-01-01", "özet", "model", sleep_fn=lambda s: None)
    assert sonuc == SUCCESS_INPUT


def test_classify_karar_retries_on_retryable_error_then_succeeds():
    uyku_cagrilari = []
    client = FakeClient([FakeAPIError(429), FakeAPIError(503), _success_response()])
    sonuc = classifier.classify_karar(
        client, "Başlık", "2026-01-01", "özet", "model",
        sleep_fn=lambda s: uyku_cagrilari.append(s),
    )
    assert sonuc == SUCCESS_INPUT
    assert uyku_cagrilari == [1, 2]


def test_classify_karar_raises_after_max_attempts_exhausted():
    client = FakeClient([FakeAPIError(429), FakeAPIError(429), FakeAPIError(429)])
    try:
        classifier.classify_karar(client, "Başlık", "2026-01-01", "özet", "model", sleep_fn=lambda s: None)
        assert False, "RuntimeError bekleniyordu"
    except RuntimeError:
        pass


def test_classify_karar_does_not_retry_non_retryable_error():
    cagrildi_mi = []
    client = FakeClient([ValueError("kalıcı hata")])
    try:
        classifier.classify_karar(
            client, "Başlık", "2026-01-01", "özet", "model",
            sleep_fn=lambda s: cagrildi_mi.append(s),
        )
        assert False, "RuntimeError bekleniyordu"
    except RuntimeError:
        pass
    assert cagrildi_mi == []
    assert client.messages.calls == 1


def test_classify_pending_updates_db_on_success(conn):
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Karar", tarih="2026-01-01", kaynak_url="https://example.com/1", ozet_ham="Karar")
    client = FakeClient([_success_response()])
    sonuc = classifier.classify_pending(conn, client=client, model="model", sleep_fn=lambda s: None)
    assert sonuc == {"basarili": 1, "basarisiz": 0, "kalici_hata": 0}
    assert db.get_pending_kararlar(conn) == []


def test_classify_pending_marks_permanent_failure_after_max_deneme(conn):
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Karar", tarih="2026-01-01", kaynak_url="https://example.com/2", ozet_ham="Karar")

    for _ in range(3):
        client = FakeClient([FakeAPIError(429), FakeAPIError(429), FakeAPIError(429)])
        classifier.classify_pending(conn, client=client, model="model", sleep_fn=lambda s: None)

    assert db.get_pending_kararlar(conn) == []
    row = conn.execute("SELECT islendi_mi, deneme_sayisi FROM kararlar").fetchone()
    assert row["islendi_mi"] == -1
    assert row["deneme_sayisi"] == 3


# --- Sektör etiketleme kuralı (profil filtresinin işlevsiz kalmaması için) ---


def test_sektorler_schema_restricts_genel_to_truly_universal_kararlar():
    aciklama = classifier.KARAR_SINIFLANDIRMA_TOOL["input_schema"]["properties"]["sektorler"]["description"]
    assert classifier.SEKTOR_ETIKETLEME_KURALI in aciklama
    # Kuralın özü: "genel" kısıtlı ve nadir olmalı.
    assert "SADECE" in aciklama
    assert "nadiren" in aciklama
    for sektor in ("e-ticaret", "finans", "sağlık", "eğitim"):
        assert sektor in aciklama


def test_build_prompt_includes_sektor_labeling_rule():
    prompt = classifier.build_prompt("Başlık", "2026-01-01", "ham özet")
    assert classifier.SEKTOR_ETIKETLEME_KURALI in prompt
    assert "ham özet" in prompt
    assert "2026-01-01" in prompt


# --- Hata görünürlüğü ve model yapılandırması ---


def test_classify_pending_logs_warning_instead_of_swallowing_error(conn, caplog):
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Karar", tarih="2026-01-01", kaynak_url="https://example.com/3", ozet_ham="Karar")
    karar_id = db.get_pending_kararlar(conn)[0]["id"]
    client = FakeClient([ValueError("çok özel bir hata")])

    with caplog.at_level(logging.WARNING):
        classifier.classify_pending(conn, client=client, model="model", sleep_fn=lambda s: None)

    metin = caplog.text
    assert str(karar_id) in metin
    assert "çok özel bir hata" in metin


def test_classify_pending_logs_recovery_hint_on_permanent_failure(conn, caplog):
    db.insert_karar_if_new(conn, kaynak="kvkk", baslik="Karar", tarih="2026-01-01", kaynak_url="https://example.com/4", ozet_ham="Karar")

    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            classifier.classify_pending(
                conn, client=FakeClient([ValueError("hata")]), model="model", sleep_fn=lambda s: None
            )

    assert "--reset-failed" in caplog.text


def test_get_model_raises_when_env_var_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_MODEL"):
        classifier._get_model()


def test_get_model_raises_when_env_var_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "")
    with pytest.raises(RuntimeError, match="ANTHROPIC_MODEL"):
        classifier._get_model()


def test_get_model_returns_env_var_value(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "bir-model-adi")
    assert classifier._get_model() == "bir-model-adi"


def test_no_hardcoded_model_name_fallback_in_source():
    """Plan kısıtı: model adı asla kod içine sabit yazılmaz."""
    kaynak = Path(classifier.__file__).read_text(encoding="utf-8")
    assert "claude-sonnet" not in kaynak
    assert 'os.environ.get("ANTHROPIC_MODEL",' not in kaynak


def test_build_prompt_uses_correct_institution_name_per_kaynak():
    assert "KVKK (Kişisel Verilerin Korunması Kurumu)" in classifier.build_prompt(
        "Başlık", "2026-01-01", "özet"
    )
    assert "BDDK (Bankacılık Düzenleme ve Denetleme Kurumu)" in classifier.build_prompt(
        "Başlık", "2026-01-01", "özet", kaynak="bddk"
    )
    assert "SPK (Sermaye Piyasası Kurulu)" in classifier.build_prompt(
        "Başlık", "2026-01-01", "özet", kaynak="spk"
    )


class RecordingMessages:
    def __init__(self, response):
        self.response = response
        self.captured_prompts = []

    def create(self, **kwargs):
        self.captured_prompts.append(kwargs["messages"][0]["content"])
        return self.response


class RecordingClient:
    def __init__(self, response):
        self.messages = RecordingMessages(response)


def test_classify_pending_passes_kaynak_from_db_row_to_prompt(conn):
    db.insert_karar_if_new(
        conn, kaynak="bddk", baslik="BDDK Kararı", tarih="2026-01-01",
        kaynak_url="https://example.com/bddk1", ozet_ham="BDDK Kararı",
    )
    client = RecordingClient(_success_response())
    classifier.classify_pending(conn, client=client, model="model", sleep_fn=lambda s: None)
    assert len(client.messages.captured_prompts) == 1
    assert "BDDK (Bankacılık Düzenleme ve Denetleme Kurumu)" in client.messages.captured_prompts[0]
