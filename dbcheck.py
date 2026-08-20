"""
Veritabani baglanti teshis araci.

    python dbcheck.py
    python dbcheck.py "postgresql://postgres.abc:parola@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"

Katman katman test eder: DNS -> TCP -> TLS -> Postgres kimlik dogrulama.
Hangi katmanda kirildigini gosterir; ust katmanlarin hatasini alt katmanin
sorunu sanmayasiniz diye.
"""

import os
import socket
import ssl
import sys
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

load_dotenv()

YESIL, KIRMIZI, SARI, GRI, BITIS = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"


def ok(m):
    print(f"  {YESIL}[OK]{BITIS} {m}")


def hata(m):
    print(f"  {KIRMIZI}[HATA]{BITIS} {m}")


def uyari(m):
    print(f"  {SARI}[!]{BITIS} {m}")


def bilgi(m):
    print(f"  {GRI}{m}{BITIS}")


def baslik(m):
    print(f"\n{'='*68}\n{m}\n{'='*68}")


def tcp_dene(host, port, timeout=8):
    """(basarili, aciklama) dondurur."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "baglanti kuruldu"
    except socket.timeout:
        return False, "zaman asimi (paket dusuruluyor - guvenlik duvari filtresi)"
    except ConnectionRefusedError:
        return False, "reddedildi (RST - sunucu kapali ya da port engelli)"
    except socket.gaierror as e:
        return False, f"DNS hatasi: {e}"
    except OSError as e:
        return False, f"{type(e).__name__}: {e}"


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else os.getenv("DB_URL", "")
    if not url:
        print("DB_URL bulunamadi. .env dosyasina ekleyin ya da parametre verin.")
        return
    if url.startswith("sqlite"):
        print("SQLite kullaniliyor; ag teshisine gerek yok.")
        return

    temiz = url.replace("+psycopg", "").replace("+psycopg2", "")
    p = urlparse(temiz)
    host, port = p.hostname, p.port or 5432
    kullanici = unquote(p.username or "")
    parola = unquote(p.password or "")
    vt = (p.path or "/postgres").lstrip("/")

    baslik("BAGLANTI BILGILERI")
    bilgi(f"host      : {host}")
    bilgi(f"port      : {port}")
    bilgi(f"kullanici : {kullanici}")
    bilgi(f"veritabani: {vt}")
    bilgi(f"parola    : {'*' * len(parola)} ({len(parola)} karakter)")

    # Supabase'e ozgu bicim kontrolleri
    if host and "pooler.supabase.com" in host:
        if "." not in kullanici:
            uyari("Pooler kullaniyorsunuz ama kullanici adi 'postgres.<proje-ref>' "
                  "bicimde degil. Parola hatasi alirsiniz.")
        else:
            ok("Pooler kullanici adi bicimi dogru")
        if port == 6543:
            uyari("Transaction pooler (6543). Session pooler (5432) daha sorunsuz.")
    elif host and host.startswith("db.") and "supabase" in host:
        uyari("Dogrudan baglanti (db.<ref>.supabase.co) kullaniyorsunuz. "
              "Bu host IPv6-only; pooler dizesine gecin.")

    if any(c in parola for c in "@/#?&"):
        uyari("Parolada URL'de anlami olan karakter var (@ / # ? &). "
              "Kodlanmamissa dize yanlis ayristirilir: @ -> %40")

    # --- 1. DNS ---------------------------------------------------------
    baslik("1. DNS COZUMLEME")
    v4 = v6 = []
    try:
        v4 = sorted({x[4][0] for x in socket.getaddrinfo(host, None, socket.AF_INET)})
        ok(f"IPv4: {v4}")
    except socket.gaierror:
        v4 = []
        uyari("IPv4 (A) kaydi yok")
    try:
        v6 = sorted({x[4][0] for x in socket.getaddrinfo(host, None, socket.AF_INET6)})
        ok(f"IPv6: {v6}")
    except socket.gaierror:
        v6 = []
        bilgi("IPv6 (AAAA) kaydi yok")

    if not v4 and not v6:
        hata("Host hic cozumlenmiyor. Proje duraklatilmis/silinmis olabilir.")
        return
    if v6 and not v4:
        hata("Yalnizca IPv6. Aginiz IPv6 desteklemiyorsa baglanamazsiniz.")
        print("\n  COZUM: Supabase panel -> Project Settings -> Database ->")
        print("  Connection string -> Session pooler dizesini kullanin.")
        return

    # --- 2. TCP ---------------------------------------------------------
    baslik("2. TCP ERISIMI")
    sonuc = {}
    for pt in sorted({port, 5432, 6543}):
        b, aciklama = tcp_dene(host, pt)
        sonuc[pt] = b
        (ok if b else hata)(f"port {pt}: {aciklama}")

    # Ag genelinde 5432 engelli mi? Baska bir Postgres sunucusuyla kiyasla
    if not sonuc.get(5432):
        bilgi("\n  Karsilastirma testi: baska bir sunucuda 443 ve 5432...")
        b443, _ = tcp_dene(host, 443, timeout=6)
        bilgi(f"  ayni host port 443 : {'acik' if b443 else 'kapali'}")

    if not any(sonuc.values()):
        hata("Hicbir veritabani portuna erisilemiyor.")
        print(f"""
  Iki olasilik var:

  A) SUPABASE PROJESI DURAKLATILMIS
     Ucretsiz katmanda proje bir hafta kullanilmazsa duraklatilir ve
     baglantilari reddeder. Panelde proje adinin yaninda "Paused" yaziyorsa
     "Restore" deyin, birkac dakika bekleyin, tekrar deneyin.

  B) AGINIZ VERITABANI PORTLARINI ENGELLIYOR
     Universite, kurum ve bazi ISS aglari 5432/6543 giden trafigi keser.
     Test: telefonunuzun mobil hotspot'una baglanip tekrar calistirin.
     Calisirsa sorun agdadir.

     Bu durumda EN IYI COZUM herkesin veritabanina baglanmasi degil,
     UYGULAMAYI TEK BIR SUNUCUDA CALISTIRMAKTIR:
       - Streamlit Community Cloud (ucretsiz) uzerine dagitin
       - DB_URL'i "Secrets" bolumune koyun
       - Ekip sadece tarayiciyla baglanir, kimse 5432'ye erisim istemez
     Bu ayni zamanda es zamanlilik ve yedekleme acisindan da daha saglam.
""")
        return

    if not sonuc.get(port) and sonuc.get(6543 if port == 5432 else 5432):
        calisan = 6543 if port == 5432 else 5432
        uyari(f"Port {port} kapali ama {calisan} acik. DB_URL'de portu "
              f"{calisan} yapin.")

    # --- 3. Postgres ----------------------------------------------------
    baslik("3. POSTGRES KIMLIK DOGRULAMA")
    try:
        import psycopg
    except ImportError:
        hata("psycopg kurulu degil: pip install 'psycopg[binary]'")
        return

    for pt in [p for p in (port, 5432, 6543) if sonuc.get(p)]:
        try:
            with psycopg.connect(host=host, port=pt, user=kullanici,
                                 password=parola, dbname=vt,
                                 sslmode="require", connect_timeout=12) as con:
                with con.cursor() as cur:
                    cur.execute("select version()")
                    s = cur.fetchone()[0]
            ok(f"port {pt}: baglanti BASARILI")
            bilgi(f"       {s[:70]}")
            print(f"\n{YESIL}Calisan DB_URL:{BITIS}")
            print(f"  postgresql+psycopg://{kullanici}:<parola>@{host}:{pt}/{vt}")
            return
        except Exception as e:
            m = str(e)
            if "password authentication" in m or "SASL" in m:
                hata(f"port {pt}: parola reddedildi")
                bilgi("       Pooler'da kullanici 'postgres.<proje-ref>' olmali.")
            elif "does not exist" in m:
                hata(f"port {pt}: veritabani/kullanici yok -> {m[:120]}")
            else:
                hata(f"port {pt}: {m[:160]}")

    print("\nTCP acik ama Postgres kabul etmiyor: kimlik bilgilerini panelden "
          "yeniden kopyalayin.")


if __name__ == "__main__":
    main()
