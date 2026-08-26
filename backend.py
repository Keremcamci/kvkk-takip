import argparse
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

import classifier
import db
import scraper

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
    finally:
        conn.close()
    return jsonify({"son_guncelleme": son_guncelleme, "kararlar": kararlar})


def run_scrape() -> None:
    conn = db.get_connection()
    try:
        db.init_db(conn)
        yeni = scraper.scrape_and_store(conn)
        print(f"{yeni} yeni karar bulundu.")
        sonuc = classifier.classify_pending(conn)
        print(f"Sınıflandırma sonucu: {sonuc}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="KVKK Mevzuat Takip Aracı")
    parser.add_argument("--scrape", action="store_true", help="Scrape + sınıflandırma pipeline'ını çalıştır")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    if args.scrape:
        run_scrape()
        return

    conn = db.get_connection()
    db.init_db(conn)
    conn.close()
    app.run(port=args.port)


if __name__ == "__main__":
    main()
