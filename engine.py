"""
9router (OpenAI uyumlu) uzerinden toplu kodlama motoru.

Tasarim notlari:
- Es zamanlilik semafor ile sinirli; 429 alinca ustel geri cekilme.
- Her basarili kodlama aninda SQLite'a yazilir -> cokme veri kaybettirmez.
- Ayni (item, model) cifti iki kez istenmez.
"""

import asyncio
import json
import os
import random
import re

import httpx
from dotenv import load_dotenv

import db
from codebook import CODEBOOK, sistem_promptu

load_dotenv()

BASE_URL = os.getenv("ROUTER_BASE_URL", "https://api.9router.ai/v1").rstrip("/")
API_KEY = os.getenv("ROUTER_API_KEY", "")

GECERLI = {a: set(t["secenekler"]) for a, t in CODEBOOK.items()}

# Tam metin kurtarildiktan sonra en uzun sorgu 15.231 karakter. 8000 sinir
# 48.059 kaydin sadece 4'unu etkiliyor; daha yuksek sinir bosuna token yakar.
MAX_PROMPT = 8000


def json_ayikla(metin):
    """Model bazen backtick ya da on soz ekler; ilk JSON blogunu cikar."""
    metin = re.sub(r"^```(?:json)?|```$", "", metin.strip(), flags=re.M).strip()
    try:
        return json.loads(metin)
    except json.JSONDecodeError:
        pass
    i, j = metin.find("{"), metin.rfind("}")
    if i != -1 and j > i:
        try:
            return json.loads(metin[i:j + 1])
        except json.JSONDecodeError:
            return None
    return None


def dogrula(kodlama):
    """Sema disi degerleri temizle. Eksik alan -> None."""
    if not isinstance(kodlama, dict):
        return None
    temiz = {}
    for alan, izin in GECERLI.items():
        deger = kodlama.get(alan)
        temiz[alan] = deger if deger in izin else None
    try:
        temiz["confidence"] = max(0.0, min(1.0, float(kodlama.get("confidence", 0))))
    except (TypeError, ValueError):
        temiz["confidence"] = None
    return temiz


async def _tek_istek(client, sem, model, item, sistem, deneme_max=5):
    bekleme = 5.0
    async with sem:
        for deneme in range(deneme_max):
            try:
                r = await client.post(
                    f"{BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {API_KEY}",
                             "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": sistem},
                            {"role": "user", "content": item["question"][:MAX_PROMPT]},
                        ],
                        "temperature": 0,
                        "max_tokens": 400,
                        "response_format": {"type": "json_object"},
                    },
                    timeout=90,
                )
            except httpx.RequestError as e:
                await asyncio.sleep(bekleme + random.uniform(0, 2))
                bekleme = min(bekleme * 2, 120)
                if deneme == deneme_max - 1:
                    return (item["item_id"], model, 0, f"AG HATASI: {e}", 0)
                continue

            if r.status_code == 429:
                ra = r.headers.get("Retry-After")
                sure = int(ra) + 2 if (ra and ra.isdigit()) else bekleme
                await asyncio.sleep(sure + random.uniform(0, 2))
                bekleme = min(bekleme * 2, 120)
                continue

            if r.status_code >= 500:
                await asyncio.sleep(bekleme)
                bekleme = min(bekleme * 2, 120)
                continue

            if r.status_code != 200:
                return (item["item_id"], model, 0,
                        f"HTTP {r.status_code}: {r.text[:200]}", 0)

            try:
                data = r.json()
                icerik = data["choices"][0]["message"]["content"]
                tok = data.get("usage", {}).get("total_tokens", 0)
            except (KeyError, IndexError, ValueError) as e:
                return (item["item_id"], model, 0, f"YANIT BICIMI: {e}", 0)

            kodlama = dogrula(json_ayikla(icerik))
            if kodlama is None:
                return (item["item_id"], model, 0,
                        f"JSON AYRISTIRILAMADI: {icerik[:200]}", tok)

            kodlama["_lang_file"] = item["lang_file"]
            return (item["item_id"], model, 1,
                    json.dumps(kodlama, ensure_ascii=False), tok)

        return (item["item_id"], model, 0, "MAKSIMUM DENEME ASILDI", 0)


async def calistir(model, items, esz=8, ilerleme=None, db_yol="coder.db"):
    """items: kodlanmamis() ciktisi. ilerleme: callback(tamam, toplam)."""
    if not API_KEY:
        raise RuntimeError("ROUTER_API_KEY tanimli degil (.env dosyasina ekleyin).")

    sistem = sistem_promptu()
    sem = asyncio.Semaphore(esz)
    tampon, tamam = [], 0

    async with httpx.AsyncClient() as client:
        gorevler = [_tek_istek(client, sem, model, it, sistem) for it in items]
        for gelecek in asyncio.as_completed(gorevler):
            tampon.append(await gelecek)
            tamam += 1
            if len(tampon) >= 20:                 # toplu yazim
                db.kodlama_yaz(tampon, db_yol)
                tampon.clear()
            if ilerleme and tamam % 5 == 0:
                ilerleme(tamam, len(items))
    if tampon:
        db.kodlama_yaz(tampon, db_yol)
    if ilerleme:
        ilerleme(tamam, len(items))
    return tamam


def calistir_sync(model, items, esz=8, ilerleme=None, db_yol="coder.db"):
    return asyncio.run(calistir(model, items, esz, ilerleme, db_yol))