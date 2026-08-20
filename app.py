"""
Prompt Coder - cok dilli sorgu korpusu icin kodlama arayuzu.

Calistirma:  streamlit run app.py
"""

import json
import os
import random
import time

import pandas as pd
import streamlit as st

import agreement
import engine
import store as db
from codebook import ALANLAR, CODEBOOK

st.set_page_config(page_title="Prompt Coder", layout="wide")
db.kur()

st.title("Prompt Coder")
st.caption("Cok dilli akademik sorgu korpusu icin LLM + insan kodlama araci")

# ---- Kimlik: kim kodluyor? Tum ekran bu secime bagli. -------------------
with st.sidebar:
    st.header("Kimlik")
    mevcut = [c["coder"] for c in db.kodlayicilar()]
    ben = st.selectbox("Kodlayici", mevcut + ["+ yeni ekle"],
                       index=0 if mevcut else 0)
    if ben == "+ yeni ekle":
        yeni = st.text_input("Ad (kisa, benzersiz)")
        if yeni and st.button("Ekle"):
            db.kodlayici_ekle(yeni.strip())
            st.rerun()
        ben = None
    st.divider()
    if st.button("Baglantiyi test et"):
        _ok, _msg = db.baglanti_testi()
        (st.success if _ok else st.error)(_msg)
    try:
        _o = db.ozet()
    except Exception as _e:
        _ok, _msg = db.baglanti_testi()
        st.error(_msg if not _ok else str(_e))
        st.stop()
    # Parolayi gostermeden hangi sunucuya bagli oldugunu belirt
    _hedef = db.DB_URL.split("@")[-1] if "@" in db.DB_URL else db.DB_URL
    st.caption(f"Arka uc: **{_o['backend']}**")
    st.caption(f"`{_hedef}`")
    if _o["backend"] == "sqlite":
        st.warning("Yalniz calisma kipi. Ekip icin DB_URL ile Postgres kullanin "
                   "(bkz. TEAM_SETUP.md). SQLite dosyasini bulut klasorunde "
                   "PAYLASMAYIN.")
    st.metric("Kayit", _o["toplam"])
    st.metric("Atama", _o["atama"])

sekmeler = st.tabs(
    ["1. Veri", "2. Model kodlama", "3. Elle kodlama", "4. Uyum raporu",
     "5. Disa aktar", "6. Ekip"]
)

# ------------------------------------------------------------------ 1. VERI
with sekmeler[0]:
    st.subheader("Excel dosyalarini yukle")
    st.write(
        "`*_fulltext.xlsx` dosyalarini yukleyin. Bu dosyalarda **question_full** "
        "sutunu var ve kodlama o sutundan yapilir — API'nin 280 karakterde kestigi "
        "`question` sutunu degil."
    )

    dosyalar = st.file_uploader(
        "sci_bot_recent_answers_*_fulltext.xlsx", type=["xlsx"],
        accept_multiple_files=True
    )
    if dosyalar and st.button("Veritabanina aktar"):
        toplam_yeni = toplam_guncel = 0
        for f in dosyalar:
            # Dosya adindan dil kodu: ..._en_fulltext.xlsx -> en ; ...tr.xlsx -> tr
            ad = f.name.rsplit(".", 1)[0].replace("_fulltext", "")
            lang = ad.split("_")[-1].lower()[:2]
            d = pd.read_excel(f).drop_duplicates("handle")

            tam_var = "question_full" in d.columns
            if not tam_var:
                st.warning(
                    f"**{f.name}**: `question_full` sutunu yok. Bu dosya kirpik "
                    "metin iceriyor; `fulltext.py merge` ciktisini yukleyin. "
                    "Yine de aktariliyor, ama kodlama eksik metinle yapilacak."
                )

            def al(r, kolon, varsayilan=""):
                v = getattr(r, kolon, varsayilan)
                return "" if pd.isna(v) else v

            kayitlar, guncellemeler = [], []
            for r in d.itertuples():
                tam = str(al(r, "question_full")) if tam_var else str(r.question)
                if not tam.strip():
                    continue
                api = str(al(r, "question_api", r.question))
                kesik = int(bool(al(r, "was_truncated", False)))
                ok = int(bool(al(r, "fulltext_ok", False)))
                kayitlar.append((str(r.handle), lang, tam, str(al(r, "topic")),
                                 str(al(r, "answeredAt_UTC")), api, kesik, ok))
                guncellemeler.append((tam, api, kesik, ok, str(r.handle)))

            yeni = db.items_ekle(kayitlar)
            # Onceden kirpik metinle eklenmis kayitlari tam metne yukselt
            degisen = db.items_guncelle_fulltext(guncellemeler)
            toplam_yeni += yeni
            toplam_guncel += degisen

            kesik_n = sum(k[6] for k in kayitlar)
            ok_n = sum(k[7] for k in kayitlar)
            st.write(
                f"**{f.name}** → dil `{lang}` | {len(kayitlar)} satir | "
                f"{yeni} yeni | kirpikti: {kesik_n} | tam metni kurtarilan: {ok_n}"
                + (f" | **{degisen} kayit tam metne yukseltildi**" if degisen else "")
            )

        st.success(f"{toplam_yeni} yeni kayit eklendi.")
        if toplam_guncel:
            st.warning(
                f"{toplam_guncel} kaydin metni degisti. Bu kayitlarin ESKI MODEL "
                "KODLAMALARI silindi (kirpik metinle uretilmislerdi). Elle "
                "kodlamalar korundu — onlari kendiniz gozden gecirin."
            )

    o = db.ozet()
    m1, m2, m3 = st.columns(3)
    m1.metric("Veritabanindaki kayit", o["toplam"])
    m2.metric("Tam metni kurtarilan", o.get("tam_metin", 0))
    m3.metric("Hala kirpik", o.get("kesik_kalan", 0))
    if o.get("kesik_kalan"):
        st.warning(
            f"{o['kesik_kalan']} kayit hala 280 karakterde kesik. Bunlari "
            "kodlamak `task_type` ve `academic_level` alanlarinda hatali etiket "
            "uretir — asil talep cogu zaman ikinci cumlede."
        )
    if o["dil"]:
        st.write("Dile gore:", o["dil"])

    st.divider()
    st.subheader("Altin standart ornegi sec")
    st.write(
        "Elle kodlanacak katmanli ornek. Her dilden esit sayida cekilir; "
        "guvenilirlik olcumu bu ornek uzerinden yapilir."
    )
    per_dil = st.number_input("Dil basina kayit", 20, 500, 150, step=10)
    if st.button("Ornegi olustur"):
        with db.baglan(DB) as con:
            con.execute("DELETE FROM sample")
            diller = [r["lang_file"] for r in
                      con.execute("SELECT DISTINCT lang_file FROM items")]
            n = 0
            for lang in diller:
                ids = [r["item_id"] for r in con.execute(
                    "SELECT item_id FROM items WHERE lang_file=?", (lang,))]
                sec = random.sample(ids, min(per_dil, len(ids)))
                con.executemany("INSERT OR IGNORE INTO sample VALUES (?,?)",
                                [(i, lang) for i in sec])
                n += len(sec)
        st.success(f"{n} kayit ornege alindi.")

# --------------------------------------------------------- 2. MODEL KODLAMA
with sekmeler[1]:
    st.subheader("9router uzerinden toplu kodlama")

    if not engine.API_KEY:
        st.error("ROUTER_API_KEY tanimli degil. .env dosyasini olusturun.")
    st.caption(f"Endpoint: {engine.BASE_URL}")

    c1, c2, c3 = st.columns(3)
    model = c1.text_input("Model", "anthropic/claude-sonnet-4.5")
    esz = c2.slider("Es zamanli istek", 1, 32, 8)
    kapsam = c3.selectbox("Kapsam", ["Sadece altin standart ornegi", "Tum korpus"])

    diller = sorted(db.ozet()["dil"])
    dil_sec = st.multiselect("Diller (bos = hepsi)", diller)
    limit = st.number_input("Azami kayit (0 = sinirsiz)", 0, 100000, 0, step=100)

    if st.button("Kodlamayi baslat", type="primary"):
        bekleyen = []
        for lang in (dil_sec or [None]):
            bekleyen += db.kodlanmamis(model, lang)
        if kapsam.startswith("Sadece"):
            with db.baglan(DB) as con:
                ornek = {r["item_id"] for r in con.execute("SELECT item_id FROM sample")}
            bekleyen = [b for b in bekleyen if b["item_id"] in ornek]
        if limit:
            bekleyen = bekleyen[:limit]

        if not bekleyen:
            st.info("Bu model icin kodlanmamis kayit yok.")
        else:
            st.write(f"{len(bekleyen)} kayit kodlanacak.")
            bar = st.progress(0.0)
            durum = st.empty()

            def ilerleme(tamam, toplam):
                bar.progress(tamam / toplam)
                durum.write(f"{tamam} / {toplam}")

            try:
                engine.calistir_sync(model, bekleyen, esz, ilerleme)
                st.success("Tamamlandi.")
            except Exception as e:
                st.error(f"Hata: {e}")

    st.divider()
    o = db.ozet()
    if o["model"]:
        st.write("Model bazinda durum (basarili / hatali):")
        st.dataframe(pd.DataFrame(
            [{"model": m, "basarili": v[0], "hatali": v[1]} for m, v in o["model"].items()]
        ), use_container_width=True)

    with st.expander("Hatali kayitlari incele"):
        ham = db.kodlamalar_ham()
        hatalar = pd.DataFrame([h for h in ham if not h["ok"]])
        if len(hatalar):
            st.dataframe(hatalar[["model", "item_id", "payload"]].head(50),
                         use_container_width=True)
        else:
            st.write("Hatali kayit yok.")

    # ------------------------------------------------- SONUCLARI INCELE
    st.divider()
    st.subheader("Kodlama sonuclari")

    if not db.modeller():
        st.info("Henuz kodlama yok.")
    else:
        if st.button("Sonuclari yukle / yenile"):
            st.session_state.ham_kodlamalar = db.kodlamalar_ham()

        ham = st.session_state.get("ham_kodlamalar")
        if ham is None:
            st.caption("Yukarıdaki butona basarak sonuclari getirin.")
        else:
            satirlar = []
            for h in ham:
                if not h["ok"]:
                    continue
                try:
                    p = json.loads(h["payload"])
                except (json.JSONDecodeError, TypeError):
                    continue
                satirlar.append({
                    "item_id": h["item_id"], "model": h["model"],
                    "dil_dosya": h["lang_file"], "platform_topic": h["topic"],
                    "uzunluk": len(h["question"] or ""),
                    "question": h["question"],
                    **{a: p.get(a) for a in ALANLAR},
                    "confidence": p.get("confidence"),
                })
            df = pd.DataFrame(satirlar)

            if df.empty:
                st.warning("Ayristirilabilir kodlama bulunamadi.")
            else:
                alt = st.tabs(["Kayitlar", "Dagilimlar", "Modeller arasi fark",
                               "Dil kontaminasyonu"])

                # --- Kayitlar -------------------------------------------
                with alt[0]:
                    f1, f2, f3 = st.columns(3)
                    m_sec = f1.multiselect("Model", sorted(df.model.unique()),
                                           sorted(df.model.unique()))
                    d_sec = f2.multiselect("Dil dosyasi",
                                           sorted(df.dil_dosya.unique()),
                                           sorted(df.dil_dosya.unique()))
                    alan_sec = f3.selectbox("Alana gore filtrele",
                                            ["(yok)"] + ALANLAR)
                    g = df[df.model.isin(m_sec) & df.dil_dosya.isin(d_sec)]

                    if alan_sec != "(yok)":
                        degerler = sorted(x for x in g[alan_sec].dropna().unique())
                        secili = st.multiselect(f"{alan_sec} degeri", degerler,
                                                degerler)
                        g = g[g[alan_sec].isin(secili)]

                    esik = st.slider("Azami confidence (dusuk olanlari gor)",
                                     0.0, 1.0, 1.0, 0.05)
                    g = g[(g.confidence.isna()) | (g.confidence <= esik)]

                    st.caption(f"{len(g)} kayit")
                    st.dataframe(
                        g[["dil_dosya", "platform_topic", "uzunluk", "confidence"]
                          + ALANLAR + ["question"]].head(500),
                        use_container_width=True, height=420)

                    st.write("**Tek kaydi incele**")
                    if len(g):
                        sec_id = st.selectbox("item_id",
                                              g.item_id.unique()[:500])
                        kayit = g[g.item_id == sec_id]
                        st.text_area("Sorgu metni",
                                     kayit.question.iloc[0], height=200,
                                     disabled=True)
                        st.caption(f"https://sci-bot.ru/{sec_id}")
                        st.dataframe(
                            kayit[["model", "confidence"] + ALANLAR].set_index("model"),
                            use_container_width=True)

                # --- Dagilimlar -----------------------------------------
                with alt[1]:
                    model_d = st.selectbox("Model", sorted(df.model.unique()),
                                           key="dag_model")
                    gd = df[df.model == model_d]
                    alan_d = st.selectbox("Alan", ALANLAR, key="dag_alan")
                    ct = pd.crosstab(gd.dil_dosya, gd[alan_d], normalize="index") * 100
                    st.write(f"**{alan_d}** — dile gore yuzde dagilim")
                    st.dataframe(ct.round(1), use_container_width=True)
                    st.write("Ham sayilar")
                    st.dataframe(pd.crosstab(gd.dil_dosya, gd[alan_d]),
                                 use_container_width=True)

                    bos = gd[ALANLAR].isna().mean() * 100
                    st.write("**Bos birakilan / sema disi deger orani (%)**")
                    st.dataframe(bos.round(1).to_frame("bos_%").T,
                                 use_container_width=True)
                    st.caption("Yuksek oran, modelin o alani anlamadigini "
                               "gosterir — codebook tanimini netlestirin.")

                # --- Modeller arasi fark --------------------------------
                with alt[2]:
                    ms = sorted(df.model.unique())
                    if len(ms) < 2:
                        st.info("Karsilastirma icin en az iki model gerekiyor. "
                                "Ayni kayitlari ikinci bir modelle kodlatin.")
                    else:
                        a1, a2 = st.columns(2)
                        ma = a1.selectbox("Model A", ms, index=0)
                        mb = a2.selectbox("Model B", ms, index=1)
                        A = df[df.model == ma].set_index("item_id")
                        B = df[df.model == mb].set_index("item_id")
                        ortak = A.index.intersection(B.index)
                        st.metric("Iki modelin de kodladigi kayit", len(ortak))

                        if len(ortak):
                            ozet_f = []
                            for alan in ALANLAR:
                                va, vb = A.loc[ortak, alan], B.loc[ortak, alan]
                                gecerli = va.notna() & vb.notna()
                                n = int(gecerli.sum())
                                uy = float((va[gecerli] == vb[gecerli]).mean() * 100) \
                                    if n else float("nan")
                                ozet_f.append({"alan": alan, "n": n,
                                               "uyum_%": round(uy, 1)})
                            st.dataframe(pd.DataFrame(ozet_f),
                                         use_container_width=True)
                            st.caption("Dusuk uyum = alan belirsiz tanimlanmis. "
                                       "Model degistirmek degil, codebook'u "
                                       "duzeltmek gerekir.")

                            alan_f = st.selectbox("Ayrisan kayitlari gor",
                                                  ALANLAR, key="fark_alan")
                            va, vb = A.loc[ortak, alan_f], B.loc[ortak, alan_f]
                            ayri = ortak[(va != vb) & va.notna() & vb.notna()]
                            st.caption(f"{len(ayri)} kayitta ayrisma")
                            if len(ayri):
                                st.dataframe(pd.DataFrame({
                                    "dil": A.loc[ayri, "dil_dosya"],
                                    ma: va.loc[ayri], mb: vb.loc[ayri],
                                    "question": A.loc[ayri, "question"].str[:200],
                                }).head(300), use_container_width=True, height=380)

                # --- Dil kontaminasyonu ---------------------------------
                with alt[3]:
                    st.write(
                        "Dosya dili (platformun etiketi) ile modelin tespit "
                        "ettigi gercek dil. Kosegen disindaki her hucre "
                        "platformun dil siniflandirmasindaki hatadir."
                    )
                    model_k = st.selectbox("Model", sorted(df.model.unique()),
                                           key="kont_model")
                    gk = df[df.model == model_k]
                    ct = pd.crosstab(gk.dil_dosya, gk.language_actual)
                    st.dataframe(ct, use_container_width=True)

                    yuzde = pd.crosstab(gk.dil_dosya, gk.language_actual,
                                        normalize="index") * 100
                    st.write("Satir yuzdesi")
                    st.dataframe(yuzde.round(1), use_container_width=True)

                    esles = {"tr": "Turkish", "en": "English", "es": "Spanish",
                             "de": "German", "ru": "Russian", "ar": "Arabic",
                             "zh": "Chinese"}
                    satir = []
                    for dosya, beklenen in esles.items():
                        alt_k = gk[gk.dil_dosya == dosya]
                        if not len(alt_k):
                            continue
                        yanlis = (alt_k.language_actual.notna() &
                                  (alt_k.language_actual != beklenen)).sum()
                        satir.append({"dosya": dosya, "beklenen": beklenen,
                                      "n": len(alt_k), "uyusmayan": int(yanlis),
                                      "hata_%": round(yanlis / len(alt_k) * 100, 1)})
                    if satir:
                        st.write("**Dosya bazinda kontaminasyon**")
                        st.dataframe(pd.DataFrame(satir), use_container_width=True)

# ---------------------------------------------------------- 3. ELLE KODLAMA
with sekmeler[2]:
    st.subheader("Elle kodlama")

    if not ben:
        st.info("Once kenar cubugundan kodlayici secin ya da ekleyin.")
    else:
        it = None
        if st.session_state.get("aktif_kodlayici") != ben:
            st.session_state.aktif_kodlayici = ben
            st.session_state.aktif_item = None
            st.session_state.baslangic = None

        if st.session_state.get("aktif_item") is None:
            st.session_state.aktif_item = db.sonraki_atama(ben)
            st.session_state.baslangic = time.time()

        it = st.session_state.aktif_item

        durum = [d for d in db.ekip_durumu() if d["kodlayici"] == ben]
        if durum:
            d0 = durum[0]
            st.progress(d0["biten"] / d0["atanan"] if d0["atanan"] else 0.0)
            st.caption(f"{d0['biten']} / {d0['atanan']} kodlandi "
                       f"(kalan {d0['kalan']})")

        if it is None:
            st.success("Size atanmis bekleyen kayit yok.")
            st.caption("Atama yapilmadiysa 6. sekmeden olusturun.")
        else:
            # KORLEME: baska kodlayicilarin etiketleri hicbir yerde gosterilmez.
            # Kayit 'overlap' havuzundan bile olsa bunu belli etmiyoruz, cunku
            # "bu kayit kontrol ediliyor" bilgisi kodlama davranisini degistirir.
            uzunluk = len(it["question"])
            rozet = []
            if it.get("fulltext_ok"):
                rozet.append("tam metin")
            elif it.get("was_truncated"):
                rozet.append("HALA KIRPIK")
            st.info(f"**Dil:** {it['lang_file']}  |  "
                    f"**Platform etiketi:** {it['topic']}  |  "
                    f"**{uzunluk} karakter**"
                    + (f"  |  {' / '.join(rozet)}" if rozet else ""))

            if it.get("was_truncated") and not it.get("fulltext_ok"):
                st.error("Bu kaydin tam metni kurtarilamamis; metin 280 "
                         "karakterde kesik. Siteden kontrol edin ya da atlayin.")

            yukseklik = min(600, max(160, 30 + uzunluk // 3))
            st.text_area("Sorgu", it["question"], height=yukseklik, disabled=True)
            st.caption(f"Sitede ac: https://sci-bot.ru/{it['item_id']}")

            secimler = {}
            sutunlar = st.columns(2)
            for i, alan in enumerate(ALANLAR):
                with sutunlar[i % 2]:
                    secimler[alan] = st.selectbox(
                        f"{alan} — {CODEBOOK[alan]['soru']}",
                        CODEBOOK[alan]["secenekler"],
                        index=None, placeholder="seciniz...",
                        key=f"sec_{ben}_{it['item_id']}_{alan}",
                        help=CODEBOOK[alan]["aciklama"])

            eksik = [a for a, v in secimler.items() if v is None]
            k1, k2 = st.columns([3, 1])
            if k1.button("Kaydet ve sonraki", type="primary", disabled=bool(eksik)):
                sure = time.time() - (st.session_state.get("baslangic") or time.time())
                db.gold_yaz(it['item_id'], ben, secimler, sure)
                st.session_state.aktif_item = None
                st.rerun()
            if k2.button("Atla"):
                db.gold_yaz(it['item_id'], ben, {'_atlandi': True})
                st.session_state.aktif_item = None
                st.rerun()
            if eksik:
                st.warning(f"Bekleyen alanlar: {', '.join(eksik)}")

# ----------------------------------------------------------- 4. UYUM RAPORU
with sekmeler[3]:
    st.subheader("Kodlayicilar arasi uyum")
    st.write(
        "Krippendorff alfa >= 0,80 guvenilir; 0,667-0,80 on sonuc icin kabul "
        "edilebilir; altinda sema ya da prompt gozden gecirilmeli."
    )

    with db.baglan(DB) as con:
        kaynaklar = [f"model:{r['model']}" for r in
                     con.execute("SELECT DISTINCT model FROM codings WHERE ok=1")]
        kaynaklar += [f"insan:{r['coder']}" for r in
                      con.execute("SELECT DISTINCT coder FROM gold")]

    secili = st.multiselect("Karsilastirilacak kaynaklar", kaynaklar, kaynaklar[:3])

    if len(secili) >= 2 and st.button("Uyumu hesapla"):
        kodlamalar = {}
        with db.baglan(DB) as con:
            for k in secili:
                tur, ad = k.split(":", 1)
                if tur == "model":
                    rows = con.execute(
                        "SELECT item_id, payload FROM codings WHERE model=? AND ok=1",
                        (ad,))
                else:
                    rows = con.execute(
                        "SELECT item_id, payload FROM gold WHERE coder=?", (ad,))
                d = {}
                for r in rows:
                    try:
                        p = json.loads(r["payload"])
                    except json.JSONDecodeError:
                        continue
                    if not p.get("_atlandi"):
                        d[r["item_id"]] = p
                kodlamalar[k] = d

        ortak = set.intersection(*[set(v) for v in kodlamalar.values()])
        st.metric("Ortak kodlanmis kayit", len(ortak))

        if len(ortak) < 10:
            st.warning("Ortak kayit sayisi cok dusuk; once ayni ornegi kodlatin.")
        else:
            rapor = agreement.alan_raporu(kodlamalar, ALANLAR)
            for s in rapor:
                s["yorum"] = agreement.yorum(s["krippendorff_alpha"])
            st.dataframe(pd.DataFrame(rapor), use_container_width=True)

            st.write("Ikili Cohen kappa:")
            st.dataframe(pd.DataFrame(
                agreement.ikili_kappa(kodlamalar, ALANLAR)).T, use_container_width=True)

# ------------------------------------------------------------ 5. DISA AKTAR
with sekmeler[4]:
    st.subheader("Sonuclari Excel'e aktar")
    with db.baglan(DB) as con:
        modeller = [r["model"] for r in
                    con.execute("SELECT DISTINCT model FROM codings WHERE ok=1")]
    ana = st.selectbox("Ana kodlayici model", modeller) if modeller else None

    if ana and st.button("Excel uret"):
        with db.baglan(DB) as con:
            rows = con.execute(
                """SELECT i.item_id, i.lang_file, i.question, i.topic, i.answered,
                          i.question_api, i.was_truncated, i.fulltext_ok,
                          c.payload FROM items i
                   JOIN codings c ON c.item_id=i.item_id AND c.model=? AND c.ok=1""",
                (ana,)).fetchall()
        kayitlar = []
        for r in rows:
            p = json.loads(r["payload"])
            kayitlar.append({
                "item_id": r["item_id"], "lang_file": r["lang_file"],
                "url": f"https://sci-bot.ru/{r['item_id']}",
                "question_full": r["question"], "question_api": r["question_api"],
                "len_full": len(r["question"] or ""),
                "was_truncated": r["was_truncated"], "fulltext_ok": r["fulltext_ok"],
                "platform_topic": r["topic"], "answeredAt_UTC": r["answered"],
                **{a: p.get(a) for a in ALANLAR},
                "confidence": p.get("confidence"),
            })
        df = pd.DataFrame(kayitlar)
        yol = f"kodlanmis_{ana.replace('/', '_')}.xlsx"
        df.to_excel(yol, index=False)
        st.success(f"{len(df)} satir -> {yol}")
        st.download_button("Indir", open(yol, "rb").read(), yol)

        st.write("Hizli capraz tablo: dosya dili x gercek dil")
        st.dataframe(pd.crosstab(df.lang_file, df.language_actual),
                     use_container_width=True)


# ---------------------------------------------------------------- 6. EKIP
with sekmeler[5]:
    st.subheader("Ekip ve is bolumu")

    st.write("**Kodlayicilar**")
    mevcut = [c["coder"] for c in db.kodlayicilar()]
    st.write(", ".join(mevcut) if mevcut else "Henuz kodlayici yok.")

    st.divider()
    st.write("**1. Altin standart ornegi**")
    c1, c2 = st.columns(2)
    per_dil = c1.number_input("Dil basina kayit", 20, 500, 150, step=10)
    seed = c2.number_input("Rastgelelik tohumu", 0, 9999, 42,
                           help="Ayni tohum ayni ornegi uretir — yeniden "
                                "uretilebilirlik icin makalede raporlayin.")
    if st.button("Ornegi olustur (mevcut atamalari siler)"):
        n = db.ornek_olustur(int(per_dil), int(seed))
        st.success(f"{n} kayit ornege alindi. Simdi atama uretin.")

    st.divider()
    st.write("**2. Atama**")
    st.caption(
        "Ortusme havuzu HERKESE atanir (guvenilirlik olcumu icin), kalan "
        "kayitlar bolusulur. Her kodlayici her dilden esit sayida kayit alir — "
        "dil kodlayiciya sabitlenirse kodlayici etkisi dil etkisiyle karisir."
    )
    secili_ekip = st.multiselect("Ekip", mevcut, mevcut)
    ortusme = st.slider("Ortusme orani", 0.10, 1.00, 0.30, 0.05,
                        help="0.30 = kayitlarin %30'unu herkes kodlar. "
                             "Alfa'nin dar guven araligi icin en az 100-150 "
                             "ortusen kayit hedefleyin.")
    if secili_ekip:
        with db.engine().connect() as _c:
            from sqlalchemy import func as _f, select as _s
            _n = _c.execute(_s(_f.count()).select_from(db.sample)).scalar() or 0
        n_ort = int(round(_n * ortusme))
        n_kisi = len(secili_ekip)
        st.caption(f"Tahmin: {_n} kayit → {n_ort} ortusen (herkese) + "
                   f"{_n - n_ort} bolusulen → kisi basi yaklasik "
                   f"{n_ort + (_n - n_ort)//n_kisi} kayit")

    if secili_ekip and st.button("Atamayi uret", type="primary"):
        ozet = db.atama_uret(secili_ekip, float(ortusme), int(seed))
        st.success("Atama tamamlandi.")
        st.dataframe(pd.DataFrame([
            {"kodlayici": k, "toplam": v["toplam"], "ortusme": v["ortusme"],
             "tek_basina": v["toplam"] - v["ortusme"]}
            for k, v in ozet.items()]), use_container_width=True)

    st.divider()
    st.write("**3. Ilerleme**")
    durum = db.ekip_durumu()
    if durum:
        st.dataframe(pd.DataFrame(durum), use_container_width=True)
        toplam_biten = sum(d["biten"] for d in durum)
        toplam_atanan = sum(d["atanan"] for d in durum)
        st.progress(toplam_biten / toplam_atanan if toplam_atanan else 0.0)
        st.caption(f"Ekip toplami: {toplam_biten} / {toplam_atanan}")
    else:
        st.info("Henuz atama yok.")

    st.divider()
    st.write("**4. Canli guvenilirlik (ortusme havuzu)**")
    st.caption("Kodlama surerken alfa'yi izleyin. Bir alan surekli dusuk "
               "kaliyorsa durun ve codebook tanimini netlestirin — daha fazla "
               "kayit kodlamak dusuk alfa'yi duzeltmez.")
    if st.button("Alfa'yi hesapla"):
        kodlamalar = db.ortusme_kodlamalari()
        kodlamalar = {k: v for k, v in kodlamalar.items() if v}
        if len(kodlamalar) < 2:
            st.warning("En az iki kodlayicinin ortusme havuzundan kayit "
                       "bitirmesi gerekiyor.")
        else:
            ortak = set.intersection(*[set(v) for v in kodlamalar.values()])
            st.metric("Herkesin kodladigi kayit", len(ortak))
            if len(ortak) < 10:
                st.warning("Cok az ortak kayit; alfa henuz anlamli degil.")
            else:
                rapor = agreement.alan_raporu(kodlamalar, ALANLAR)
                for r in rapor:
                    r["yorum"] = agreement.yorum(r["krippendorff_alpha"])
                st.dataframe(pd.DataFrame(rapor), use_container_width=True)
                st.write("Ikili Cohen kappa:")
                st.dataframe(pd.DataFrame(
                    agreement.ikili_kappa(kodlamalar, ALANLAR)).T,
                    use_container_width=True)