"""SQLite depolama. Checkpoint mantigi burada: hicbir istek iki kez atilmaz."""

import json
import sqlite3
from contextlib import contextmanager

SEMA = """
CREATE TABLE IF NOT EXISTS items (
    item_id   TEXT PRIMARY KEY,      -- handle
    lang_file TEXT NOT NULL,         -- hangi dosyadan geldi (tr/en/es/de/ru/ar/zh)
    question  TEXT NOT NULL,         -- KODLANACAK metin: varsa question_full
    topic     TEXT,
    answered  TEXT
);

CREATE TABLE IF NOT EXISTS codings (
    item_id  TEXT NOT NULL,
    model    TEXT NOT NULL,
    ok       INTEGER NOT NULL,       -- 1 basarili, 0 hatali
    payload  TEXT,                   -- JSON kodlama ya da hata mesaji
    tokens   INTEGER DEFAULT 0,
    ts       TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (item_id, model)
);

CREATE TABLE IF NOT EXISTS gold (
    item_id  TEXT NOT NULL,
    coder    TEXT NOT NULL,          -- insan kodlayici adi
    payload  TEXT NOT NULL,
    ts       TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (item_id, coder)
);

CREATE TABLE IF NOT EXISTS sample (
    item_id  TEXT PRIMARY KEY,       -- altin standart icin secilen ornek
    stratum  TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_lang ON items(lang_file);
CREATE INDEX IF NOT EXISTS idx_codings_model ON codings(model);
"""


@contextmanager
def baglan(yol="coder.db"):
    con = sqlite3.connect(yol, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    finally:
        con.close()


# Eski veritabanlarina sonradan eklenen sutunlar. ALTER TABLE'in
# "IF NOT EXISTS" karsiligi olmadigi icin hatayi yutuyoruz.
EK_SUTUNLAR = [
    ("items", "question_api", "TEXT"),      # API'nin dondurdugu kirpik hali
    ("items", "was_truncated", "INTEGER"),  # 280'de kesilmis miydi
    ("items", "fulltext_ok", "INTEGER"),    # tam metin kurtarilabildi mi
]


def kur(yol="coder.db"):
    with baglan(yol) as con:
        con.executescript(SEMA)
        for tablo, sutun, tip in EK_SUTUNLAR:
            try:
                con.execute(f"ALTER TABLE {tablo} ADD COLUMN {sutun} {tip}")
            except sqlite3.OperationalError:
                pass                      # sutun zaten var


def items_ekle(kayitlar, yol="coder.db"):
    """
    kayitlar: (item_id, lang_file, question, topic, answered,
               question_api, was_truncated, fulltext_ok) listesi.
    `question` alanina TAM metin yazilir (varsa question_full).
    """
    with baglan(yol) as con:
        con.executemany(
            """INSERT OR IGNORE INTO items
               (item_id, lang_file, question, topic, answered,
                question_api, was_truncated, fulltext_ok)
               VALUES (?,?,?,?,?,?,?,?)""", kayitlar
        )
        return con.total_changes


def items_guncelle_fulltext(kayitlar, yol="coder.db"):
    """
    Daha once KIRPIK metinle eklenmis kayitlarin metnini tam metinle degistirir.
    kayitlar: (question, question_api, was_truncated, fulltext_ok, item_id)
    Metni degisen kayitlarin eski kodlamalari gecersizdir -> silinir.
    """
    with baglan(yol) as con:
        degisen = []
        for tam, api, kesik, ok, iid in kayitlar:
            r = con.execute("SELECT question FROM items WHERE item_id=?",
                            (iid,)).fetchone()
            if r and r["question"] != tam:
                degisen.append(iid)
        con.executemany(
            """UPDATE items SET question=?, question_api=?, was_truncated=?,
               fulltext_ok=? WHERE item_id=?""", kayitlar)
        # Kirpik metinle uretilmis kodlamalar artik gecersiz
        con.executemany("DELETE FROM codings WHERE item_id=?",
                        [(i,) for i in degisen])
        return len(degisen)


def kodlanmamis(model, lang=None, limit=None, yol="coder.db"):
    """Bu model tarafindan henuz BASARIYLA kodlanmamis kayitlar."""
    q = """SELECT i.item_id, i.question, i.lang_file FROM items i
           LEFT JOIN codings c ON c.item_id=i.item_id AND c.model=? AND c.ok=1
           WHERE c.item_id IS NULL"""
    p = [model]
    if lang:
        q += " AND i.lang_file=?"
        p.append(lang)
    if limit:
        q += f" LIMIT {int(limit)}"
    with baglan(yol) as con:
        return [dict(r) for r in con.execute(q, p)]


def kodlama_yaz(kayitlar, yol="coder.db"):
    """kayitlar: (item_id, model, ok, payload, tokens) listesi."""
    with baglan(yol) as con:
        con.executemany(
            "INSERT OR REPLACE INTO codings (item_id,model,ok,payload,tokens) "
            "VALUES (?,?,?,?,?)", kayitlar
        )


def gold_yaz(item_id, coder, payload, yol="coder.db"):
    with baglan(yol) as con:
        con.execute(
            "INSERT OR REPLACE INTO gold (item_id,coder,payload) VALUES (?,?,?)",
            (item_id, coder, json.dumps(payload, ensure_ascii=False)),
        )


def ozet(yol="coder.db"):
    with baglan(yol) as con:
        toplam = con.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]
        per_lang = {r["lang_file"]: r["c"] for r in con.execute(
            "SELECT lang_file, COUNT(*) c FROM items GROUP BY 1")}
        per_model = {r["model"]: (r["ok"], r["hata"]) for r in con.execute(
            "SELECT model, SUM(ok) ok, SUM(1-ok) hata FROM codings GROUP BY 1")}
        gold_n = con.execute("SELECT COUNT(DISTINCT item_id) c FROM gold").fetchone()["c"]
        tam_metin = con.execute(
            "SELECT COUNT(*) c FROM items WHERE fulltext_ok=1").fetchone()["c"]
        kesik_kalan = con.execute(
            "SELECT COUNT(*) c FROM items WHERE was_truncated=1 AND "
            "(fulltext_ok IS NULL OR fulltext_ok=0)").fetchone()["c"]
        ornek_n = con.execute("SELECT COUNT(*) c FROM sample").fetchone()["c"]
    return {"toplam": toplam, "dil": per_lang, "model": per_model,
            "gold": gold_n, "ornek": ornek_n, "tam_metin": tam_metin,
            "kesik_kalan": kesik_kalan}