"""
Ortak depolama katmani.

Tek kod yolu, iki arka uc:
  - Yalniz calisma : sqlite:///coder.db          (varsayilan)
  - Ekip calismasi : postgresql+psycopg://...    (DB_URL ile)

SQLite dosyasini Dropbox/Drive uzerinden PAYLASMAYIN; es zamanli yazimda
bozulur. Ekip icin barindirilan bir Postgres kullanin (Supabase/Neon ucretsiz
katmani yeterli).
"""

import json
import os

from dotenv import load_dotenv
from sqlalchemy import (NullPool, Boolean, Column, DateTime, Float, Integer, MetaData,
                        String, Table, Text, UniqueConstraint, create_engine,
                        delete, func, insert, select, update)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

load_dotenv()


def _url_duzelt(url: str) -> str:
    """
    Baglanti dizesindeki surucu adini normallestirir.

    SQLAlchemy'de 'postgresql://' varsayilan olarak psycopg2 surucusunu secer.
    Biz psycopg 3 kullaniyoruz, o yuzden acikca belirtmek gerekiyor. Supabase ve
    Neon dizeyi 'postgresql://' (bazen 'postgres://') olarak verdigi icin
    dogrudan yapistirildiginde "No module named 'psycopg2'" hatasi cikar.
    """
    if url.startswith("postgres://"):                 # eski Heroku bicimi
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DB_URL = _url_duzelt(os.getenv("DB_URL", "sqlite:///coder.db"))

_engine = None
meta = MetaData()

items = Table(
    "items", meta,
    Column("item_id", String(200), primary_key=True),
    Column("lang_file", String(8), nullable=False, index=True),
    Column("question", Text, nullable=False),      # TAM metin
    Column("question_api", Text),                  # kirpik hali
    Column("topic", String(64)),
    Column("answered", String(40)),
    Column("was_truncated", Boolean, default=False),
    Column("fulltext_ok", Boolean, default=False),
)

codings = Table(
    "codings", meta,
    Column("item_id", String(200), primary_key=True),
    Column("model", String(120), primary_key=True),
    Column("ok", Boolean, nullable=False),
    Column("payload", Text),
    Column("tokens", Integer, default=0),
    Column("ts", DateTime, server_default=func.now()),
)

# --- Ekip ---------------------------------------------------------------
coders = Table(
    "coders", meta,
    Column("coder", String(80), primary_key=True),
    Column("pin", String(20)),                     # basit ayirt edici, guvenlik degil
    Column("note", Text),
    Column("created", DateTime, server_default=func.now()),
)

sample = Table(
    "sample", meta,
    Column("item_id", String(200), primary_key=True),
    Column("stratum", String(8)),
)

# Her kodlayiciya onceden atanan is listesi. Onceden atama sayesinde iki kisi
# ayni kaydi ayni anda acmaz -> kilit/lease mekanizmasina gerek kalmaz.
assignments = Table(
    "assignments", meta,
    Column("item_id", String(200), primary_key=True),
    Column("coder", String(80), primary_key=True),
    Column("kind", String(16), nullable=False),    # 'overlap' | 'primary'
    Column("sira", Integer),                       # kodlayiciya ozel sunum sirasi
)

gold = Table(
    "gold", meta,
    Column("item_id", String(200), primary_key=True),
    Column("coder", String(80), primary_key=True),
    Column("payload", Text, nullable=False),
    Column("saniye", Float),                       # kodlamaya harcanan sure
    Column("ts", DateTime, server_default=func.now()),
)


def engine():
    global _engine
    if _engine is None:
        kw = {"future": True}
        if DB_URL.startswith("sqlite"):
            kw["connect_args"] = {"timeout": 30}
        elif ":6543" in DB_URL:
            # Supabase/Supavisor "transaction mode" (port 6543) hazir ifadeleri
            # desteklemez; psycopg3 varsayilan olarak kullanir -> "prepared
            # statement already exists" hatasi verir. Kapatiyoruz.
            kw["connect_args"] = {"prepare_threshold": None}
            kw["poolclass"] = NullPool
        try:
            _engine = create_engine(DB_URL, **kw)
        except ModuleNotFoundError as e:
            eksik = str(e).split("'")[1] if "'" in str(e) else str(e)
            raise RuntimeError(
                f"Veritabani surucusu bulunamadi: {eksik}\n"
                f"Kullanilan baglanti: {DB_URL.split('@')[-1]}\n\n"
                "Postgres icin:  pip install 'psycopg[binary]'\n"
                ".env dosyanizda DB_URL su bicimde olmali:\n"
                "  postgresql+psycopg://kullanici:parola@host:5432/veritabani\n"
                "(Supabase/Neon 'postgresql://' verir; kod bunu otomatik "
                "duzeltir, ama surucunun kurulu olmasi gerekir.)"
            ) from e
        if DB_URL.startswith("sqlite"):
            with _engine.begin() as c:
                c.exec_driver_sql("PRAGMA journal_mode=WAL")
    return _engine


def baglanti_testi():
    """
    Baglantiyi dener ve hatayi TESHISLI bir mesaja cevirir.
    Donen: (basarili: bool, mesaj: str)
    """
    import socket
    from urllib.parse import urlparse

    try:
        with engine().connect() as c:
            c.execute(select(1))
        return True, f"Baglanti basarili: {DB_URL.split('@')[-1]}"
    except Exception as e:
        metin = str(e)
        host = urlparse(DB_URL.replace("+psycopg", "")).hostname or ""

        # Adres ailesi kontrolunu HER hatada yap: makineye gore ayni sorun
        # farkli mesaj uretiyor ("failed to resolve host", "connection is bad",
        # "network unreachable"...). Metne guvenmek kirilgan.
        v4 = v6 = False
        if host and not DB_URL.startswith("sqlite"):
            for aile, bayrak in ((socket.AF_INET, "v4"), (socket.AF_INET6, "v6")):
                try:
                    socket.getaddrinfo(host, None, aile)
                    if bayrak == "v4":
                        v4 = True
                    else:
                        v6 = True
                except socket.gaierror:
                    pass

            if not v4 and not v6:
                return False, (
                    f"'{host}' hic cozumlenemiyor. Proje duraklatilmis ya da "
                    "silinmis olabilir; adresi panelden tekrar kopyalayin."
                )
            if v6 and not v4:
                return False, (
                    f"'{host}' YALNIZCA IPv6 adresine sahip (IPv4 kaydi yok).\n\n"
                    "Supabase dogrudan baglantiyi IPv6'ya tasidi; cogu ev/kurum "
                    "agi IPv6 desteklemiyor.\n\n"
                    "COZUM — Session pooler kullanin:\n"
                    "Supabase panel -> Project Settings -> Database -> "
                    "Connection string -> **Session pooler**\n\n"
                    "  postgresql://postgres.<proje-ref>:PAROLA@"
                    "aws-0-<bolge>.pooler.supabase.com:5432/postgres\n\n"
                    "Iki farka dikkat: kullanici adi duz 'postgres' degil "
                    "'postgres.<proje-ref>', host da 'pooler.supabase.com'.\n\n"
                    f"(Ham hata: {metin[:200]})"
                )

        if "password authentication" in metin or "SASL" in metin:
            return False, (
                "Parola reddedildi. Parolada @ / # : gibi karakter varsa URL "
                "kodlamasi gerekir (@ -> %40). Pooler kullaniyorsaniz kullanici "
                "adi 'postgres.<proje-ref>' olmali."
            )
        if "SSL" in metin or "sslmode" in metin:
            return False, ("SSL gerekiyor. Dizenin sonuna ?sslmode=require ekleyin.")
        if "prepared statement" in metin:
            return False, ("Transaction pooler (6543) hazir ifade sorunu. "
                           "Session pooler (5432) kullanin.")
        return False, f"Baglanti kurulamadi:\n{metin[:600]}"


def kur():
    meta.create_all(engine())


def _upsert(tablo, kayitlar, guncelle=None):
    """Arka uca gore INSERT ... ON CONFLICT."""
    if not kayitlar:
        return 0
    ins = pg_insert if DB_URL.startswith("postgres") else sqlite_insert
    st = ins(tablo).values(kayitlar)
    anahtarlar = [c.name for c in tablo.primary_key]
    if guncelle:
        st = st.on_conflict_do_update(
            index_elements=anahtarlar,
            set_={k: getattr(st.excluded, k) for k in guncelle})
    else:
        st = st.on_conflict_do_nothing(index_elements=anahtarlar)
    with engine().begin() as c:
        return c.execute(st).rowcount


# ------------------------------------------------------------------ ITEMS
def items_ekle(kayitlar):
    """kayitlar: dict listesi (items sutun adlariyla)."""
    return _upsert(items, kayitlar)


def items_guncelle_fulltext(kayitlar):
    """
    kayitlar: {item_id, question, question_api, was_truncated, fulltext_ok}
    Metni gercekten degisenlerin MODEL kodlamalari silinir (kirpik metinle
    uretilmislerdi). Elle kodlamalara dokunulmaz.
    """
    if not kayitlar:
        return 0
    mevcut = {}
    with engine().connect() as c:
        for r in c.execute(select(items.c.item_id, items.c.question)):
            mevcut[r.item_id] = r.question
    degisen = [k["item_id"] for k in kayitlar
               if k["item_id"] in mevcut and mevcut[k["item_id"]] != k["question"]]
    with engine().begin() as c:
        for k in kayitlar:
            c.execute(update(items).where(items.c.item_id == k["item_id"]).values(
                question=k["question"], question_api=k.get("question_api"),
                was_truncated=k.get("was_truncated"),
                fulltext_ok=k.get("fulltext_ok")))
        if degisen:
            c.execute(delete(codings).where(codings.c.item_id.in_(degisen)))
    return len(degisen)


def kodlanmamis(model, lang=None, limit=None, sadece_ornek=False):
    q = select(items.c.item_id, items.c.question, items.c.lang_file).where(
        ~items.c.item_id.in_(
            select(codings.c.item_id).where(
                (codings.c.model == model) & (codings.c.ok == True))))
    if lang:
        q = q.where(items.c.lang_file == lang)
    if sadece_ornek:
        q = q.where(items.c.item_id.in_(select(sample.c.item_id)))
    if limit:
        q = q.limit(int(limit))
    with engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(q)]


def kodlama_yaz(kayitlar):
    """kayitlar: (item_id, model, ok, payload, tokens) demetleri."""
    d = [{"item_id": a, "model": b, "ok": bool(c_), "payload": p, "tokens": t}
         for a, b, c_, p, t in kayitlar]
    return _upsert(codings, d, guncelle=["ok", "payload", "tokens"])


# ------------------------------------------------------------------- EKIP
def kodlayici_ekle(ad, pin=None, note=None):
    return _upsert(coders, [{"coder": ad, "pin": pin, "note": note}])


def kodlayicilar():
    with engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(select(coders))]


def ornek_olustur(per_dil, seed=42):
    """Dile gore katmanli altin standart ornegi."""
    import random
    rng = random.Random(seed)
    with engine().connect() as c:
        diller = [r[0] for r in c.execute(
            select(items.c.lang_file).distinct())]
        secim = []
        for lang in diller:
            ids = [r[0] for r in c.execute(
                select(items.c.item_id).where(items.c.lang_file == lang))]
            ids.sort()                          # deterministik taban
            rng.shuffle(ids)
            secim += [{"item_id": i, "stratum": lang}
                      for i in ids[:min(per_dil, len(ids))]]
    with engine().begin() as c:
        c.execute(delete(assignments))
        c.execute(delete(sample))
    return _upsert(sample, secim)


def atama_uret(kodlayici_listesi, ortusme_orani=0.30, seed=42):
    """
    Ornekteki kayitlari kodlayicilara dagitir.

    Tasarim:
      - Her dil AYRI dagitilir -> her kodlayici her dilden kayit gorur.
        (Dil kodlayiciya sabitlenirse kodlayici etkisi dil etkisiyle karisir
         ve diller arasi karsilastirma savunulamaz hale gelir.)
      - Ortusme havuzu HERKESE atanir -> Krippendorff alfa hesaplanabilir.
      - Kalan kayitlar sirayla bolusulur -> is tekrari olmaz.
      - Sunum sirasi kodlayiciya ozel karistirilir -> ayni kayitlari ayni
        sirada gormezler, yorgunluk etkisi ortusme setine yiginlanmaz.
    """
    import random
    if not kodlayici_listesi:
        return {}
    rng = random.Random(seed)

    with engine().connect() as c:
        satirlar = [dict(r._mapping) for r in c.execute(
            select(sample.c.item_id, sample.c.stratum))]

    per_dil = {}
    for s in satirlar:
        per_dil.setdefault(s["stratum"], []).append(s["item_id"])

    atamalar = []
    for lang, ids in per_dil.items():
        ids = sorted(ids)
        rng.shuffle(ids)
        n_ort = int(round(len(ids) * ortusme_orani))
        ortusen, kalan = ids[:n_ort], ids[n_ort:]

        for iid in ortusen:
            for k in kodlayici_listesi:
                atamalar.append({"item_id": iid, "coder": k, "kind": "overlap"})
        for i, iid in enumerate(kalan):
            atamalar.append({"item_id": iid,
                             "coder": kodlayici_listesi[i % len(kodlayici_listesi)],
                             "kind": "primary"})

    # Kodlayiciya ozel sira
    per_coder = {}
    for a in atamalar:
        per_coder.setdefault(a["coder"], []).append(a)
    for k, liste in per_coder.items():
        yerel = random.Random(f"{seed}-{k}")
        yerel.shuffle(liste)
        for i, a in enumerate(liste):
            a["sira"] = i

    with engine().begin() as c:
        c.execute(delete(assignments))
    _upsert(assignments, atamalar)

    return {k: {"toplam": len(v),
                "ortusme": sum(1 for a in v if a["kind"] == "overlap")}
            for k, v in per_coder.items()}


def sonraki_atama(coder):
    """Bu kodlayicinin kodlamadigi ilk atanmis kayit (kendi sirasina gore)."""
    q = (select(items.c.item_id, items.c.question, items.c.lang_file,
                items.c.topic, items.c.was_truncated, items.c.fulltext_ok,
                assignments.c.kind, assignments.c.sira)
         .select_from(assignments.join(items, items.c.item_id == assignments.c.item_id))
         .where(assignments.c.coder == coder)
         .where(~assignments.c.item_id.in_(
             select(gold.c.item_id).where(gold.c.coder == coder)))
         .order_by(assignments.c.sira).limit(1))
    with engine().connect() as c:
        r = c.execute(q).fetchone()
    return dict(r._mapping) if r else None


def gold_yaz(item_id, coder, payload, saniye=None):
    return _upsert(gold, [{"item_id": item_id, "coder": coder,
                           "payload": json.dumps(payload, ensure_ascii=False),
                           "saniye": saniye}],
                   guncelle=["payload", "saniye"])


def ekip_durumu():
    """Kodlayici basina ilerleme."""
    with engine().connect() as c:
        atanan = {r.coder: r.n for r in c.execute(
            select(assignments.c.coder, func.count().label("n")).group_by(
                assignments.c.coder))}
        biten = {r.coder: r.n for r in c.execute(
            select(gold.c.coder, func.count().label("n")).group_by(gold.c.coder))}
        sure = {r.coder: r.s for r in c.execute(
            select(gold.c.coder, func.avg(gold.c.saniye).label("s")).group_by(
                gold.c.coder))}
    return [{"kodlayici": k, "atanan": v, "biten": biten.get(k, 0),
             "kalan": v - biten.get(k, 0),
             "yuzde": round(biten.get(k, 0) / v * 100, 1) if v else 0,
             "ort_saniye": round(sure.get(k) or 0, 1)}
            for k, v in sorted(atanan.items())]


def ortusme_kodlamalari():
    """
    Ortusme havuzunda EN AZ IKI kodlayicinin bitirdigi kayitlar.
    Donen: {coder: {item_id: kodlama}}
    """
    with engine().connect() as c:
        ort = {r[0] for r in c.execute(
            select(assignments.c.item_id).where(assignments.c.kind == "overlap"))}
        cikti = {}
        for r in c.execute(select(gold.c.item_id, gold.c.coder, gold.c.payload)):
            if r.item_id not in ort:
                continue
            try:
                p = json.loads(r.payload)
            except json.JSONDecodeError:
                continue
            if p.get("_atlandi"):
                continue
            cikti.setdefault(r.coder, {})[r.item_id] = p
    return cikti


def kodlamalar_ham(model=None, lang=None, limit=None):
    """
    Model kodlamalarini kayit metniyle birlikte dondurur (inceleme icin).
    payload alani JSON metnidir; ayristirmayi cagiran taraf yapar.
    """
    q = (select(codings.c.item_id, codings.c.model, codings.c.ok,
                codings.c.payload, codings.c.tokens,
                items.c.lang_file, items.c.question, items.c.topic,
                items.c.was_truncated, items.c.fulltext_ok)
         .select_from(codings.join(items, items.c.item_id == codings.c.item_id)))
    if model:
        q = q.where(codings.c.model == model)
    if lang:
        q = q.where(items.c.lang_file == lang)
    if limit:
        q = q.limit(int(limit))
    with engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(q)]


def modeller():
    with engine().connect() as c:
        return [r[0] for r in c.execute(
            select(codings.c.model).distinct().order_by(codings.c.model))]


def ozet():
    with engine().connect() as c:
        toplam = c.execute(select(func.count()).select_from(items)).scalar()
        per_lang = {r.lang_file: r.n for r in c.execute(
            select(items.c.lang_file, func.count().label("n")).group_by(
                items.c.lang_file))}
        per_model = {r.model: (r.ok, r.hata) for r in c.execute(
            select(codings.c.model,
                   func.sum(func.cast(codings.c.ok, Integer)).label("ok"),
                   func.sum(1 - func.cast(codings.c.ok, Integer)).label("hata")
                   ).group_by(codings.c.model))}
        gold_n = c.execute(select(func.count(func.distinct(gold.c.item_id)))).scalar()
        ornek_n = c.execute(select(func.count()).select_from(sample)).scalar()
        atama_n = c.execute(select(func.count()).select_from(assignments)).scalar()
        tam = c.execute(select(func.count()).select_from(items).where(
            items.c.fulltext_ok == True)).scalar()
        kesik = c.execute(select(func.count()).select_from(items).where(
            (items.c.was_truncated == True) &
            ((items.c.fulltext_ok == False) | (items.c.fulltext_ok.is_(None))))).scalar()
    return {"toplam": toplam, "dil": per_lang, "model": per_model, "gold": gold_n,
            "ornek": ornek_n, "atama": atama_n, "tam_metin": tam,
            "kesik_kalan": kesik, "backend": DB_URL.split("://")[0]}