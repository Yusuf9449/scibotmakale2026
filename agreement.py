"""
Kodlayicilar arasi uyum olcumleri.

Krippendorff alfa (nominal) tercih edilir cunku eksik veriye dayanikli ve
ikiden fazla kodlayiciyi ayni anda ele alir. Cohen kappa ikili karsilastirma
icin ek olarak raporlanir.
"""

import itertools
from collections import Counter, defaultdict

import numpy as np


def krippendorff_alpha(birimler):
    """
    birimler: {birim_id: [etiket, ...]} - her birim icin farkli kodlayicilarin
    verdigi etiketler (None'lar disarida birakilmis olmali).
    Nominal veri icin alfa dondurur.
    """
    birimler = {k: [x for x in v if x is not None] for k, v in birimler.items()}
    birimler = {k: v for k, v in birimler.items() if len(v) >= 2}
    if not birimler:
        return float("nan"), 0

    n_toplam = sum(len(v) for v in birimler.values())

    # Gozlenen uyusmazlik
    Do_pay = 0.0
    for etiketler in birimler.values():
        m = len(etiketler)
        c = Counter(etiketler)
        ayni = sum(v * (v - 1) for v in c.values())
        farkli = m * (m - 1) - ayni
        Do_pay += farkli / (m - 1)
    Do = Do_pay / n_toplam

    # Beklenen uyusmazlik
    genel = Counter(itertools.chain.from_iterable(birimler.values()))
    De_pay = sum(
        genel[a] * genel[b]
        for a, b in itertools.permutations(genel, 2)
    )
    De = De_pay / (n_toplam * (n_toplam - 1))

    if De == 0:
        return 1.0, len(birimler)
    return 1 - Do / De, len(birimler)


def cohen_kappa(a, b):
    """a, b: ayni uzunlukta etiket listeleri (None iceren ciftler atilir)."""
    ciftler = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not ciftler:
        return float("nan"), 0
    n = len(ciftler)
    po = sum(x == y for x, y in ciftler) / n
    ca, cb = Counter(x for x, _ in ciftler), Counter(y for _, y in ciftler)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if pe == 1:
        return 1.0, n
    return (po - pe) / (1 - pe), n


def alan_raporu(kodlamalar, alanlar):
    """
    kodlamalar: {kaynak_adi: {item_id: {alan: etiket}}}
      kaynak_adi ornegin 'gpt-5', 'claude', 'insan_yusuf'
    Her alan icin Krippendorff alfa ve yuzde uyum dondurur.
    """
    kaynaklar = list(kodlamalar)
    ortak = set.intersection(*[set(kodlamalar[k]) for k in kaynaklar]) \
        if kaynaklar else set()

    satirlar = []
    for alan in alanlar:
        birimler = {}
        for iid in ortak:
            birimler[iid] = [kodlamalar[k][iid].get(alan) for k in kaynaklar]
        alfa, n = krippendorff_alpha(birimler)

        tam = [v for v in birimler.values() if all(x is not None for x in v)]
        yuzde = (sum(len(set(v)) == 1 for v in tam) / len(tam)) if tam else float("nan")

        satirlar.append({
            "alan": alan, "n": n, "krippendorff_alpha": round(alfa, 3),
            "tam_uyum_%": round(yuzde * 100, 1) if tam else None,
        })
    return satirlar


def ikili_kappa(kodlamalar, alanlar):
    """Her alan icin tum kaynak ciftleri arasinda Cohen kappa."""
    kaynaklar = list(kodlamalar)
    ortak = set.intersection(*[set(kodlamalar[k]) for k in kaynaklar]) \
        if kaynaklar else set()
    ortak = sorted(ortak)

    cikti = defaultdict(dict)
    for a, b in itertools.combinations(kaynaklar, 2):
        for alan in alanlar:
            va = [kodlamalar[a][i].get(alan) for i in ortak]
            vb = [kodlamalar[b][i].get(alan) for i in ortak]
            k, n = cohen_kappa(va, vb)
            cikti[alan][f"{a} vs {b}"] = round(k, 3)
    return dict(cikti)


def yorum(alfa):
    """Krippendorff'un onerdigi esikler."""
    if alfa != alfa:
        return "hesaplanamadi"
    if alfa >= 0.80:
        return "guvenilir"
    if alfa >= 0.667:
        return "on sonuc icin kabul edilebilir"
    return "YETERSIZ - sema ya da prompt gozden gecirilmeli"
