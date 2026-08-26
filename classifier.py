import os
import time

from anthropic import Anthropic

import db

MAX_BACKOFF_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1
MAX_KARAR_DENEME = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

KARAR_SINIFLANDIRMA_TOOL = {
    "name": "karar_sinifla",
    "description": "Bir KVKK Kurulu kararını şirket profillerine göre sınıflandırır.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sektorler": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["e-ticaret", "finans", "saglik", "egitim", "genel"],
                },
                "description": "Bu kararın ilgilendirdiği şirket profilleri.",
            },
            "ozet": {"type": "string", "description": "2-3 cümlelik özet."},
            "yapilmasi_gerekenler": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Şirketin yapması gereken somut adımlar.",
            },
            "aciliyet_var": {"type": "boolean"},
            "aciliyet_aciklama": {"type": "string"},
        },
        "required": [
            "sektorler", "ozet", "yapilmasi_gerekenler",
            "aciliyet_var", "aciliyet_aciklama",
        ],
    },
}


def build_prompt(baslik: str, tarih, ozet_ham: str) -> str:
    return (
        "Aşağıda bir KVKK (Kişisel Verilerin Korunması Kurumu) kurul kararının "
        "başlığı verilmiştir. Bu kararı karar_sinifla aracını kullanarak "
        "sınıflandır.\n\n"
        f"Tarih: {tarih or 'bilinmiyor'}\n"
        f"Başlık/Özet: {ozet_ham}\n"
    )


def _is_retryable(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) in RETRYABLE_STATUS_CODES


def _get_client() -> Anthropic:
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _get_model() -> str:
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")


def classify_karar(client, baslik, tarih, ozet_ham, model, sleep_fn=time.sleep) -> dict:
    prompt = build_prompt(baslik, tarih, ozet_ham)
    son_hata: Exception | None = None
    for deneme in range(MAX_BACKOFF_ATTEMPTS):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                tools=[KARAR_SINIFLANDIRMA_TOOL],
                tool_choice={"type": "tool", "name": "karar_sinifla"},
                messages=[{"role": "user", "content": prompt}],
            )
            for block in response.content:
                if getattr(block, "type", None) == "tool_use" and block.name == "karar_sinifla":
                    return block.input
            raise RuntimeError("Anthropic yanıtında tool_use bloğu bulunamadı")
        except Exception as exc:
            son_hata = exc
            son_deneme_mi = deneme == MAX_BACKOFF_ATTEMPTS - 1
            if not _is_retryable(exc) or son_deneme_mi:
                raise RuntimeError(f"Sınıflandırma başarısız: {son_hata}") from son_hata
            sleep_fn(BACKOFF_BASE_SECONDS * (2 ** deneme))
    raise RuntimeError(f"Sınıflandırma başarısız: {son_hata}")


def classify_pending(conn, client=None, model=None, sleep_fn=time.sleep) -> dict:
    client = client or _get_client()
    model = model or _get_model()
    sonuc = {"basarili": 0, "basarisiz": 0, "kalici_hata": 0}
    for karar in db.get_pending_kararlar(conn):
        try:
            classification = classify_karar(
                client, karar["baslik"], karar["tarih"], karar["ozet_ham"], model,
                sleep_fn=sleep_fn,
            )
            db.update_karar_classification(
                conn,
                karar["id"],
                classification["sektorler"],
                classification["ozet"],
                classification["yapilmasi_gerekenler"],
                classification["aciliyet_var"],
                classification["aciliyet_aciklama"],
            )
            sonuc["basarili"] += 1
        except Exception:
            kalici_mi = db.mark_karar_failed(conn, karar["id"])
            if kalici_mi:
                sonuc["kalici_hata"] += 1
            else:
                sonuc["basarisiz"] += 1
    return sonuc


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    connection = db.get_connection()
    db.init_db(connection)
    sonuc = classify_pending(connection)
    print(f"Sınıflandırma sonucu: {sonuc}")
    for karar in db.get_kararlar_by_profil(connection, "genel"):
        print(f"- [{karar['tarih']}] {karar['baslik'][:80]}...")
        print(f"  Sektörler: {karar['sektorler']}")
        print(f"  Özet: {karar['ozet']}")
    connection.close()
