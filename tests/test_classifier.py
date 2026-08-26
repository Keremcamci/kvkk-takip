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
