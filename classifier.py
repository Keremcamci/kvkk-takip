import logging
import os
import time

from anthropic import Anthropic

import db

MAX_BACKOFF_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Aracın tüm değeri "kararları SİZİN şirket tipinize göre filtreliyoruz"
# vaadinde. Model her karara "genel" verirse her profil aynı listeyi görür ve
# filtre işlevsiz kalır (canlı testte 10/10 karar "genel" etiketlenmişti).
# Bu yüzden "genel" bilinçli olarak dar tanımlanır; kural hem tool şemasında
# hem prompt'ta tekrarlanır.
SEKTOR_ETIKETLEME_KURALI = (
    '"genel" etiketini SADECE karar dört sektörün hepsini '
    "(e-ticaret, finans, sağlık, eğitim) eşit ölçüde ve aynı şekilde "
    "ilgilendiriyorsa kullan. Karar belirli bir veya birkaç sektöre daha çok "
    "uyuyorsa (örn. özel nitelikli/sağlık verisi işleyenler, çevrimiçi satış "
    "yapanlar, kredi ve ödeme kuruluşları, öğrenci verisi tutan kurumlar) "
    'yalnızca o sektör(ler)i etiketle, "genel" EKLEME. "genel" nadiren doğru '
    "cevaptır; kararların çoğu aslında belirli sektörleri ilgilendirir. Emin "
    'değilsen "genel" yerine en uygun spesifik sektörü seç. "genel" diğer '
    'etiketlerle birlikte kullanılmaz: ya yalnızca "genel", ya bir veya daha '
    "fazla spesifik sektör. Karar HİÇBİR işletme sektörünü (e-ticaret, "
    'finans, sağlık, eğitim), hatta "genel" bile ilgilendirmiyorsa (örn. '
    "askeri bölge ilanı, diplomatik vize muafiyeti, kamu kurumu iç "
    'organizasyon kararı) "sektorler" alanını boş dizi ([]) olarak döndür.'
)

KURUM_ADLARI = {
    "kvkk": "KVKK (Kişisel Verilerin Korunması Kurumu)",
    "bddk": "BDDK (Bankacılık Düzenleme ve Denetleme Kurumu)",
    "spk": "SPK (Sermaye Piyasası Kurulu)",
    "resmi_gazete": "Resmi Gazete (T.C. Cumhurbaşkanlığı)",
}

KARAR_SINIFLANDIRMA_TOOL = {
    "name": "karar_sinifla",
    "description": "Bir düzenleyici kurum kararını şirket profillerine göre sınıflandırır.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sektorler": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["e-ticaret", "finans", "saglik", "egitim", "genel"],
                },
                "description": (
                    "Bu kararın ilgilendirdiği şirket profilleri. "
                    + SEKTOR_ETIKETLEME_KURALI
                ),
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


def build_prompt(baslik: str, tarih, ozet_ham: str, kaynak: str = "kvkk") -> str:
    kurum_adi = KURUM_ADLARI.get(kaynak, kaynak)
    return (
        f"Aşağıda bir {kurum_adi} kararının "
        "başlığı verilmiştir. Bu kararı karar_sinifla aracını kullanarak "
        "sınıflandır.\n\n"
        "Sektör etiketleme kuralı (ÖNEMLİ): "
        f"{SEKTOR_ETIKETLEME_KURALI}\n\n"
        f"Tarih: {tarih or 'bilinmiyor'}\n"
        f"Başlık/Özet: {ozet_ham}\n"
    )


def _is_retryable(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) in RETRYABLE_STATUS_CODES


def _get_client() -> Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY ortam değişkeni ayarlanmamış (.env dosyanızı kontrol edin)"
        )
    return Anthropic(api_key=api_key)


def _get_model() -> str:
    # Model adı asla kod içine sabit yazılmaz (plan kısıtı) — eksikse
    # sessizce bir varsayılana düşmek yerine net bir hata ver.
    model = os.environ.get("ANTHROPIC_MODEL")
    if not model:
        raise RuntimeError(
            "ANTHROPIC_MODEL ortam değişkeni ayarlanmamış (.env dosyasını kontrol edin)"
        )
    return model


def _validate_classification_input(input_: dict) -> dict:
    # input_schema'daki "required" modele bir ipucudur, API tarafından
    # zorunlu kılınmaz — model bazen bir alanı atlar. Böyle bir durumda
    # classify_pending'de ham bir KeyError'a düşüp genel bir "sınıflandırma
    # başarısız" uyarısında boğulmak yerine, tam olarak hangi alanın eksik
    # olduğunu söyleyen net bir hata veriyoruz (bkz. _get_model).
    zorunlu_alanlar = KARAR_SINIFLANDIRMA_TOOL["input_schema"]["required"]
    eksik_alanlar = [alan for alan in zorunlu_alanlar if alan not in input_]
    if eksik_alanlar:
        raise RuntimeError(
            "Model yanıtında zorunlu alan(lar) eksik: " + ", ".join(eksik_alanlar)
        )
    # JSON şeması "genel"i enum ile kısıtlar ama diğer etiketlerle birlikte
    # kullanılamayacağını ZORUNLU KILMAZ (SEKTOR_ETIKETLEME_KURALI yalnızca
    # prompt/description seviyesinde bir talimat). Model buna uymayıp
    # ["e-ticaret", "genel"] gibi bir kombinasyon döndürürse profil filtresi
    # işlevsiz kalır (her profil "genel" kararı görür) — runtime'da reddet.
    sektorler = input_["sektorler"]
    if "genel" in sektorler and len(sektorler) > 1:
        raise RuntimeError(
            '"genel" diğer sektörlerle birlikte döndürüldü: '
            + ", ".join(sektorler)
        )
    return input_


def classify_karar(client, baslik, tarih, ozet_ham, model, kaynak: str = "kvkk", sleep_fn=time.sleep) -> dict:
    prompt = build_prompt(baslik, tarih, ozet_ham, kaynak)
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
                    return _validate_classification_input(block.input)
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
                kaynak=karar["kaynak"], sleep_fn=sleep_fn,
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
        except Exception as exc:
            logging.warning("Karar %s sınıflandırılamadı: %s", karar["id"], exc)
            kalici_mi = db.mark_karar_failed(conn, karar["id"])
            if kalici_mi:
                logging.warning(
                    "Karar %s kalıcı hata olarak işaretlendi (%s deneme). "
                    "Düzelttikten sonra: python backend.py --reset-failed",
                    karar["id"],
                    db.MAX_KARAR_DENEME,
                )
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
