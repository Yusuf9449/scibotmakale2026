"""
Kodlama semasi (codebook).

Her alan, onceki analizlerde ortaya cikan somut bir arastirma sorusuna karsilik
gelir. Yeni alan eklerken ayni yapiyi koru: LLM'e giden JSON semasi ve elle
kodlama arayuzu bu sozlukten otomatik uretilir.
"""

CODEBOOK = {
    "language_actual": {
        "soru": "Metin gercekte hangi dilde yazilmis?",
        "aciklama": (
            "Platformun etiketi degil, metnin kendisi. Arapca dosyasindaki Farsca "
            "kontaminasyonunu yakalamak icin kritik alan."
        ),
        "secenekler": ["Turkish", "English", "Spanish", "German", "Russian",
                       "Arabic", "Persian", "Chinese", "other", "unclear"],
    },
    "speech_act": {
        "soru": "Sorgunun baskin soz edimi nedir?",
        "aciklama": (
            "command = kullaniciya is buyurma ('yaz', 'ozetle', 'hazirla'). "
            "question = bilgi sorma. topic = sadece konu basligi atma, fiil yok. "
            "mixed = hem soru hem talimat esit agirlikta."
        ),
        "secenekler": ["command", "question", "topic", "mixed"],
    },
    "task_type": {
        "soru": "Kullanici sistemden ne uretmesini istiyor?",
        "aciklama": (
            "literature_search = kaynak/makale bulma. explanation = kavram aciklama. "
            "text_production = kullanici adina metin yazma (giris, taslak, boliim). "
            "data_analysis = veri/hesap isleme. definition = kisa tanim. "
            "other = digerleri."
        ),
        "secenekler": ["literature_search", "explanation", "text_production",
                       "data_analysis", "definition", "other"],
    },
    "source_request": {
        "soru": "Acikca kaynak, atif, makale veya referans isteniyor mu?",
        "aciklama": "Ima degil, acik talep. 'kaynaklariyla', 'with citations' gibi.",
        "secenekler": ["yes", "no"],
    },
    "discipline": {
        "soru": "Sorgunun gercek disiplini nedir?",
        "aciklama": (
            "Platformun 'general' kovasini acmak icin. Beseri bilimler ve sosyal "
            "bilimler ayri secenek: platform bunlari 'general'a atiyor."
        ),
        "secenekler": ["bio", "chem", "phys", "math", "compsci", "earth", "eco",
                       "neuro", "medicine", "humanities", "social_science",
                       "engineering", "law", "education", "other"],
    },
    "academic_level": {
        "soru": "Metinden anlasilan akademik duzey nedir?",
        "aciklama": (
            "Ipuclari: 'odevim', 'tezim', 'hausarbeit', 'makalem', terminoloji "
            "yogunlugu, metodoloji dili. Ipucu yoksa unclear."
        ),
        "secenekler": ["school", "undergrad", "graduate", "researcher", "unclear"],
    },
    "assignment_disclosure": {
        "soru": "Kullanici bunun odev/tez/makale icin oldugunu acikca soyluyor mu?",
        "aciklama": "'odevim icin', 'for my thesis', 'para mi tesis' gibi acik ifade.",
        "secenekler": ["yes", "no"],
    },
    "is_valid": {
        "soru": "Bu gecerli bir akademik sorgu mu?",
        "aciklama": (
            "no = anlamsiz karakter dizisi, test girisi, bos icerik, spam. "
            "Analiz disi birakilacak kayitlari isaretlemek icin."
        ),
        "secenekler": ["yes", "no"],
    },
}

# Elle kodlamada gosterilecek sira
ALANLAR = list(CODEBOOK.keys())


def json_semasi() -> str:
    """LLM'e gonderilecek cikti semasinin metin hali."""
    satirlar = []
    for alan, tanim in CODEBOOK.items():
        secenekler = " | ".join(tanim["secenekler"])
        satirlar.append(f'  "{alan}": <{secenekler}>')
    return "{\n" + ",\n".join(satirlar) + ',\n  "confidence": <0.0-1.0>\n}'


def sistem_promptu() -> str:
    bolumler = []
    for alan, tanim in CODEBOOK.items():
        bolumler.append(
            f"### {alan}\n{tanim['soru']}\n{tanim['aciklama']}\n"
            f"Secenekler: {', '.join(tanim['secenekler'])}"
        )
    return f"""Sen bir akademik icerik analizi kodlayicisisin. Sana bir arama motoruna
girilmis tek bir kullanici sorgusu verilecek. Gorevin bu sorguyu asagidaki kodlama
semasina gore etiketlemek.

KURALLAR:
- Sadece metinde OLAN'a bak. Cikarim yapma, tahmin uretme.
- Emin olamadigin alanlarda 'unclear' / 'other' kullan; zorlama etiket verme.
- Sorgunun dilini bilmiyorsan bile diger alanlari kodlamaya calis.
- Cevabin SADECE gecerli JSON olsun. Aciklama, on soz, markdown backtick YOK.

KODLAMA SEMASI:

{chr(10).join(bolumler)}

CIKTI FORMATI (tam olarak bu anahtarlar, baska anahtar ekleme):
{json_semasi()}

confidence: kendi kodlamana duydugun guven (0.0-1.0). Metin kisa, belirsiz ya da
anlamsizsa dusuk ver."""
