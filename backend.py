import argparse
import logging
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

import classifier
import db
from scrapers import bddk, kvkk, spk

load_dotenv()

BASE_DIR = Path(__file__).parent
app = Flask(__name__, static_folder=None)


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/api/kararlar")
def api_kararlar():
    profil = request.args.get("profil", "genel")
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
        for isim, modul in [("kvkk", kvkk), ("bddk", bddk), ("spk", spk)]:
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
