import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "kvkk.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS kararlar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kaynak TEXT NOT NULL DEFAULT 'kvkk',
    baslik TEXT NOT NULL,
    tarih TEXT,
    kaynak_url TEXT UNIQUE NOT NULL,
    ozet_ham TEXT,
    sektorler TEXT,
    llm_ozet TEXT,
    yapilmasi_gerekenler TEXT,
    aciliyet_var INTEGER,
    aciliyet_aciklama TEXT,
    islendi_mi INTEGER NOT NULL DEFAULT 0,
    deneme_sayisi INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
"""


def get_connection(db_path=None) -> sqlite3.Connection:
    if db_path is None:
        db_path = DB_PATH
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(SCHEMA)
    conn.commit()


def insert_karar_if_new(conn, kaynak, baslik, tarih, kaynak_url, ozet_ham) -> bool:
    cur = conn.execute(
        "INSERT OR IGNORE INTO kararlar (kaynak, baslik, tarih, kaynak_url, ozet_ham) "
        "VALUES (?, ?, ?, ?, ?)",
        (kaynak, baslik, tarih, kaynak_url, ozet_ham),
    )
    conn.commit()
    return cur.rowcount > 0


def get_pending_kararlar(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT id, baslik, tarih, ozet_ham, deneme_sayisi FROM kararlar WHERE islendi_mi = 0"
    ).fetchall()
    return [dict(row) for row in rows]


def update_karar_classification(
    conn, karar_id, sektorler, ozet, yapilmasi_gerekenler, aciliyet_var, aciliyet_aciklama
) -> None:
    conn.execute(
        "UPDATE kararlar SET sektorler = ?, llm_ozet = ?, yapilmasi_gerekenler = ?, "
        "aciliyet_var = ?, aciliyet_aciklama = ?, islendi_mi = 1 WHERE id = ?",
        (
            json.dumps(sektorler, ensure_ascii=False),
            ozet,
            json.dumps(yapilmasi_gerekenler, ensure_ascii=False),
            1 if aciliyet_var else 0,
            aciliyet_aciklama,
            karar_id,
        ),
    )
    conn.commit()


def mark_karar_failed(conn, karar_id) -> bool:
    row = conn.execute(
        "SELECT deneme_sayisi FROM kararlar WHERE id = ?", (karar_id,)
    ).fetchone()
    yeni_deneme = row["deneme_sayisi"] + 1
    kalici_mi = yeni_deneme >= 3
    yeni_durum = -1 if kalici_mi else 0
    conn.execute(
        "UPDATE kararlar SET deneme_sayisi = ?, islendi_mi = ? WHERE id = ?",
        (yeni_deneme, yeni_durum, karar_id),
    )
    conn.commit()
    return kalici_mi


def get_kararlar_by_profil(conn, profil) -> list[dict]:
    rows = conn.execute(
        "SELECT id, baslik, tarih, llm_ozet, sektorler, yapilmasi_gerekenler, "
        "aciliyet_var, aciliyet_aciklama, kaynak_url FROM kararlar "
        "WHERE islendi_mi = 1 ORDER BY tarih DESC"
    ).fetchall()
    sonuc = []
    for row in rows:
        sektorler = json.loads(row["sektorler"]) if row["sektorler"] else []
        if profil in sektorler or "genel" in sektorler:
            sonuc.append({
                "id": row["id"],
                "baslik": row["baslik"],
                "tarih": row["tarih"],
                "ozet": row["llm_ozet"],
                "sektorler": sektorler,
                "yapilmasi_gerekenler": json.loads(row["yapilmasi_gerekenler"]) if row["yapilmasi_gerekenler"] else [],
                "aciliyet_var": bool(row["aciliyet_var"]),
                "aciliyet_aciklama": row["aciliyet_aciklama"],
                "kaynak_url": row["kaynak_url"],
            })
    return sonuc


def get_son_guncelleme(conn) -> str | None:
    row = conn.execute("SELECT MAX(created_at) AS son FROM kararlar").fetchone()
    return row["son"] if row and row["son"] else None
