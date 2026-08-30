import argparse
import logging
import secrets
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, g, jsonify, request

import classifier
import db
from scrapers import bddk, kvkk, resmi_gazete, spk

load_dotenv()

BASE_DIR = Path(__file__).parent
app = Flask(__name__, static_folder=None)

GECERLI_PROFILLER = {"genel", "e-ticaret", "finans", "saglik", "egitim"}


@app.after_request
def _guvenlik_basliklari_ekle(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # index.html'in tek sayfalık inline <script>/<style> kullanımı yüzünden
    # 'unsafe-inline' CSP'yi neredeyse anlamsız kılardı (enjekte edilen
    # herhangi bir script de çalışırdı). Bunun yerine her istekte üretilen
    # bir nonce hem bu başlığa hem de index() rotasında sayfaya yazılır;
    # esc()/escAttr() atlanan bir hata olsa bile enjekte edilen script bu
    # nonce'u bilemeyeceği için tarayıcı tarafından engellenir.
    nonce = getattr(g, "csp_nonce", None)
    kaynak = f"'self' 'nonce-{nonce}'" if nonce else "'self'"
    response.headers["Content-Security-Policy"] = (
        f"default-src 'self'; script-src {kaynak}; style-src {kaynak}; "
        "img-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'"
    )
    return response


@app.route("/")
def index():
    g.csp_nonce = secrets.token_urlsafe(16)
    html = (BASE_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("<script>", f'<script nonce="{g.csp_nonce}">', 1)
    html = html.replace("<style>", f'<style nonce="{g.csp_nonce}">', 1)
    return Response(html, mimetype="text/html")


@app.route("/api/kararlar")
def api_kararlar():
    profil = request.args.get("profil", "genel")
    if profil not in GECERLI_PROFILLER:
        return jsonify({
            "error": f"Geçersiz profil: {profil!r}. İzin verilenler: "
            f"{', '.join(sorted(GECERLI_PROFILLER))}",
        }), 400
    conn = db.get_connection()
    try:
        kararlar = db.get_kararlar_by_profil(conn, profil)
        son_guncelleme = db.get_son_guncelleme(conn)
        # `son_guncelleme` gibi profilden bağımsızdır: seçili profil listeyi
        # boşaltsa bile kullanıcı hangi kaynaktan kaç karar takip edildiğini
        # görebilmeli.
        kaynak_sayilari = db.get_kaynak_sayilari(conn)
    finally:
        conn.close()
    return jsonify({
        "son_guncelleme": son_guncelleme,
        "kaynak_sayilari": kaynak_sayilari,
        "kararlar": kararlar,
    })


def run_scrape() -> None:
    conn = db.get_connection()
    try:
        db.init_db(conn)
        for isim, modul in [("kvkk", kvkk), ("bddk", bddk), ("spk", spk), ("resmi_gazete", resmi_gazete)]:
            try:
                yeni = modul.scrape_and_store(conn)
                print(f"{isim}: {yeni} yeni karar bulundu.")
            except Exception as exc:
                # exc_info: bir kaynağın hatası diğerlerini durdurmadığı için
                # bu satır her koşuda sessizce tekrarlanabilir. Traceback
                # olmadan "spk scrape başarısız: 'link'" ayıklanamaz.
                logging.warning("%s scrape başarısız: %s", isim, exc, exc_info=True)
        sonuc = classifier.classify_pending(conn)
        print(f"Sınıflandırma sonucu: {sonuc}")
    finally:
        conn.close()


def run_reset_failed() -> None:
    conn = db.get_connection()
    try:
        db.init_db(conn)
        sayi = db.reset_failed_kararlar(conn)
        print(f"{sayi} karar yeniden denenmek üzere kuyruğa alındı.")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="KVKK Mevzuat Takip Aracı")
    parser.add_argument("--scrape", action="store_true", help="Scrape + sınıflandırma pipeline'ını çalıştır")
    parser.add_argument(
        "--reset-failed",
        action="store_true",
        help="Kalıcı hataya düşmüş kararları yeniden kuyruğa al (sonra --scrape çalıştırın)",
    )
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()

    if args.reset_failed:
        run_reset_failed()
        return

    if args.scrape:
        run_scrape()
        return

    conn = db.get_connection()
    db.init_db(conn)
    conn.close()
    app.run(port=args.port)


if __name__ == "__main__":
    main()
