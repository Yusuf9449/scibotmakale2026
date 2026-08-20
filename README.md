# Prompt Coder

Çok dilli akademik sorgu korpusunu LLM + insan kodlamasıyla etiketleme aracı.
`sci-bot.ru` verisi için yazıldı ama codebook değiştirilerek başka korpuslara uyarlanabilir.

## Kurulum

```bash
cd prompt-coder
pip install -r requirements.txt
cp .env.example .env      # ROUTER_API_KEY'i doldurun
streamlit run app.py
```

`.env` içeriği:

```
ROUTER_BASE_URL=https://api.9router.ai/v1
ROUTER_API_KEY=...
```

Endpoint OpenAI uyumlu `/chat/completions` bekliyor. 9router farklı bir yol
kullanıyorsa `engine.py` içindeki `_tek_istek` fonksiyonunda tek satır değişir.

## Akış

1. **Veri** — Excel dosyalarını yükle. Dil kodu dosya adının sonundan okunur
   (`..._en.xlsx` → `en`). Sonra altın standart örneğini oluştur (dil başına 150 önerilir).
2. **Model kodlama** — Model adını gir, kapsamı seç, başlat. Aynı kayıt aynı
   modele iki kez gönderilmez; kesinti olursa kaldığı yerden devam eder.
3. **Elle kodlama** — Örnekteki kayıtlar tek tek gelir, açılır menülerden kodlarsın.
   İki farklı kodlayıcı adıyla iki kez yapılırsa insan-insan güvenilirliği de ölçülür.
4. **Uyum raporu** — Krippendorff α ve ikili Cohen κ. Eşikler: ≥0,80 güvenilir,
   0,667–0,80 ön sonuç için kabul edilebilir, altı yetersiz.
5. **Dışa aktar** — Excel + dosya dili × gerçek dil çapraz tablosu.

## Kodlama şeması

`codebook.py` içinde 8 alan var. Her biri önceki analizlerde çıkan bir soruya bağlı:

| Alan | Ne için |
|---|---|
| `language_actual` | Arapça dosyadaki %31,7 Farsça kontaminasyonunu ölçmek |
| `discipline` | Platformun `general` kovasını açmak (beşeri/sosyal bilimler ayrı) |
| `speech_act` | Emir/soru ayrımı — regex ölçümünün yerine geçecek |
| `task_type` | "Üretim aracı mı erişim aracı mı" tezini test etmek |
| `source_request` | Kaynak talebi oranı |
| `academic_level` | Düzey farkı var mı |
| `assignment_disclosure` | Ödev/tez beyanı |
| `is_valid` | Anlamsız girişleri analiz dışı bırakmak |

Alan eklemek için `CODEBOOK` sözlüğüne yeni girdi yaz — hem LLM prompt'u hem
elle kodlama arayüzü otomatik güncellenir.

## Maliyet

~44.000 kayıt × ~250 token ≈ 11M giriş tokenı, model başına. Ucuz bir modelle
tüm korpusu, pahalı bir modelle sadece altın standart örneğini kodlamak
mantıklı bir bölüşüm.

## Önemli

LLM kodlaması insan kodlamasının yerine geçmez. En az iki farklı model +
insan altın standardı kullan; α değerini makalede raporla. α düşük çıkan alanı
kullanma, önce codebook tanımını netleştir.
