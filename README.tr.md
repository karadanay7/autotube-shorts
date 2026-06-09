# AutoTube Shorts

Ollama ile script, ElevenLabs ile ses, MoviePy ile render ve YouTube planlama — çok kanallı YouTube Shorts otomasyonu.

```
Konu → LLM → TTS → Video → Planlama → YouTube yükleme
```

## Özellikler

- **Çoklu kanal** — kanal başına ayrı OAuth, kuyruk ve ses
- **Web paneli** — konu ekleme, üretim, SEO, planlama, yükleme
- **AI konu üretimi** — kanal niche/tone'a göre haftalık konular
- **Günlük planlama** — kanal başına günde bir slot (saat dilimi ayarlanabilir)
- **Manuel yükleme kontrolü** — üretim ve YouTube yüklemesi ayrı adımlar
- **Yerel LLM** — Ollama ile ücretli AI API gerekmez
- **TR / EN arayüz** — panel sağ üstten dil seçimi

## Gereksinimler

| Araç | Amaç |
|------|------|
| Python 3.10+ | Çalışma ortamı |
| [Ollama](https://ollama.com/) | Yerel LLM (`deepseek-r1:8b`) |
| [FFmpeg](https://ffmpeg.org/) | Video kodlama |
| ElevenLabs API | Text-to-speech |
| Google Cloud | YouTube Data API v3 + OAuth |
| Pexels API (isteğe bağlı) | Stok arka plan videosu |

## Hızlı kurulum

```bash
git clone https://github.com/karadanay7/autotube-shorts.git
cd autotube-shorts

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# .env dosyasını düzenleyin

cp config/client_secrets.json.example config/client_secrets.json
# Google OAuth bilgilerini girin

ollama serve
ollama pull deepseek-r1:8b

python app.py
```

Tarayıcıda **http://127.0.0.1:5000** — sağ üstten **EN** veya **TR** seçin.

---

## Ortam değişkenleri (`.env`)

```bash
cp .env.example .env
```

| Değişken | Açıklama |
|----------|----------|
| `OLLAMA_BASE_URL` | Ollama adresi (varsayılan `http://127.0.0.1:11434`) |
| `OLLAMA_MODEL` | Model adı |
| `ELEVENLABS_API_KEY` | [ElevenLabs](https://elevenlabs.io/) API anahtarı |
| `PEXELS_API_KEY` | [Pexels API](https://www.pexels.com/api/) (isteğe bağlı) |
| `GOOGLE_CLIENT_SECRETS` | OAuth JSON yolu |
| `OAUTH_REDIRECT_URI` | Google Console ile birebir aynı olmalı |
| `PORT` | Flask portu (varsayılan `5000`) |
| `MIN_VIDEO_SECONDS` / `MAX_VIDEO_SECONDS` | Video süresi hedefi (varsayılan 30–60 sn) |
| `SCHEDULE_DISPLAY_TIMEZONE` / `SCHEDULE_DAILY_HOUR` / `SCHEDULE_DAILY_MINUTE` | Otomatik planlama saati (ör. İstanbul 20:00) |
| `YOUTUBE_DECLARE_SYNTHETIC_MEDIA` | `true` = YouTube yüklemesinde yapay/sentetik içerik bildirimi |

**`.env` ve gerçek API anahtarlarını asla commit etmeyin.**

---

## Google Cloud kurulumu (YouTube OAuth)

### 1. Proje oluştur

1. [Google Cloud Console](https://console.cloud.google.com/)
2. Yeni proje → ad verin
3. Projeyi seçin

### 2. YouTube Data API v3 etkinleştir

**APIs & Services → Library** → **YouTube Data API v3** → **Enable**

### 3. OAuth consent screen

1. **OAuth consent screen** → **External**
2. Uygulama adı, destek e-postası
3. **Scopes** ekleyin:
   - `youtube.upload`
   - `youtube.readonly`
   - `youtube.force-ssl`
4. **Test users** — YouTube kanallarınızın Google hesaplarını ekleyin (Testing modunda zorunlu)
5. Kaydedin

### 4. OAuth istemcisi

1. **Credentials → Create credentials → OAuth client ID**
2. Tür: **Web application**
3. **Authorized redirect URIs**:

   ```
   http://127.0.0.1:5000/oauth/youtube/callback
   ```

4. JSON indirin → **`config/client_secrets.json`** olarak kaydedin (`config/creds/` içine değil)

`config/creds/` farklıdır: panelde **Bağla** dedikten sonra uygulama `channel_<id>_token.json` yazar. Bu token dosyaları yerelde görünür, gitignore’dadır, GitHub’da yoktur.

---

## Panel kullanımı (iş akışı)

### Günlük akış

```
Konu ekle → Üret → Hazır (SEO) → Planla → Yükle → Senkron
```

| Adım | Panel | Ne olur |
|------|-------|---------|
| 1 | Kanal seçici | Kanallar arası geçiş (her kanalın kuyruğu ve YouTube hesabı ayrı) |
| 2 | **Üretim — konu ekle** | Tek konu, toplu satırlar veya AI haftalık konular |
| 3 | **Üret** | İşler **sırayla**: script → ses → video render |
| 4 | **Hazır videolar** | Önizleme, başlık/açıklama (≤100 karakter), yayın saati |
| 5 | **Planla** (üst) | Hazır videolara günlük slot atar |
| 6 | **Yükle** (üst) | Planlı videoları YouTube'a yükler |
| 7 | **Senkron** (üst) | YouTube'daki gerçek yayın saatlerini DB'ye yazar |

Panel, üretim veya yükleme sırasında **otomatik yenilenir** (istatistikler, kuyruk, hazır/YouTube listeleri).

### Kurallar

- Sadece **Hazır** videolar planlanır — **Bekleyen** kuyruk işleri render bitene kadar planlanmaz.
- **Üret** yalnızca **bekleyen** işleri çalıştırır (hatalı işler dahil değildir).
- **Hatalı** işler otomatik yeniden denenmez — satırdaki **Yeniden dene**, üstteki **Hatalıları yeniden dene** veya kuyruk araç çubuğundaki **Seçilenleri yeniden dene** kullanın.
- **Üret** / **Yeniden dene** işleri **sırayla** işler; satırdaki **Çalıştır** / **Yeniden dene** tek iş içindir.
- Videolar hedef **30–60 saniye** (`.env` ile ayarlanır).
- Her kanal için ayrı **Bağla** (Google hesap seçici).

---

## Yayın planlaması

Varsayılan saat: `.env` → `SCHEDULE_DISPLAY_TIMEZONE`, `SCHEDULE_DAILY_HOUR`, `SCHEDULE_DAILY_MINUTE` (sonra `python app.py` yeniden başlat). Üst çubukta aktif kural görünür.

### Yayın saati üç yolla ayarlanır

| Yöntem | Nerede | Ne yapar |
|--------|--------|----------|
| **Planla** (üst) | Üst çubuk | Saati olmayan tüm **Hazır** videolara sıradaki otomatik slotu atar (seçili kanal) |
| **Düzenle & planla** | Hazır videolar → satırı aç | **Tek** video için tarih/saat seç (`datetime-local`). Boş bırakıp kaydet → o video için otomatik slot |
| **Senkron** (üst) | Üst çubuk | YouTube'daki gerçek yayın saatlerini veritabanına yazar (yükleme yapmaz) |

Akış: **Üret** → **Hazır** → **Planla** → **Yükle** → **Senkron**.

### Varsayılan: her gün sabit saat

`SCHEDULE_US_PEAK_HOURS=false` iken (`.env.example` varsayılanı):

- **Kanal başına takvim gününde en fazla bir** yayın.
- Saat: **`SCHEDULE_DAILY_HOUR:SCHEDULE_DAILY_MINUTE`**, saat dilimi: **`SCHEDULE_DISPLAY_TIMEZONE`**.
- Örnek: `SCHEDULE_DISPLAY_TIMEZONE=Europe/Istanbul` ve `SCHEDULE_DAILY_HOUR=20` → **her gün 20:00 (İstanbul)**.
- O gün YouTube veya yerel DB'de zaten planlı/yayınlanmış video varsa **o gün atlanır**, sonraki boş güne yazılır.
- Birden fazla hazır video → **ardışık günlerde aynı saat** (ör. Pazartesi 20:00, Salı 20:00).
- Slot en az **`SCHEDULE_MIN_LEAD_MINUTES`** dakika sonrası olmalı (varsayılan 60).

### Alternatif: ABD yoğun saatleri

`.env` içinde `SCHEDULE_US_PEAK_HOURS=true` yapın. Otomatik planlama, `SCHEDULE_TIMEZONE` (varsayılan Doğu ABD) içinde haftanın gününe göre farklı yoğun saat pencerelerinden seçer. Hedef kitleniz çoğunlukla ABD ise uygundur.

### “Her gün şu saatte planla” nasıl değiştirilir?

`.env` dosyasını düzenleyin (günlük planlama için yalnızca bu üç satır yeterli):

```env
SCHEDULE_DISPLAY_TIMEZONE=Europe/Istanbul
SCHEDULE_DAILY_HOUR=18
SCHEDULE_DAILY_MINUTE=30
```

Uygulamayı yeniden başlatın. Panel üstünde yeni kural görünür (ör. `Daily 18:30 Europe/Istanbul`).

**Tek video:** **Hazır videolar → Düzenle & planla** (yeniden başlatma gerekmez).

---

## Başka YouTube kanalı ekleme

**Bir panel kanalı = bir YouTube hesabı** (ayrı kuyruk, OAuth token, isteğe bağlı ses override).

Üstteki **kanal dropdown** sadece mevcut kanallar arasında geçiş yapar; yeni kanal eklemez.

### 3. (veya daha fazla) YouTube hesabı

1. Panelde **Kanal & ayarlar** bölümünü açın (alttaki panel).
2. **YouTube hesapları** listesinde bağlı kanalları görün.
3. Mor çerçeveli **Yeni kanal ekle** kutusunda:
   - **Panel adı** yazın (ör. `Finance Channel`).
   - **Niche** seçin (ses ve AI kuralları `config/niches.json`'dan gelir).
   - **Oluşturunca YouTube bağla** işaretli kalsın.
4. **+ Oluştur** → Google hesap seçici açılır.
5. Hedef YouTube kanalının sahibi **farklı** Google hesabını seçin.

### Bağla vs hesap değiştir

| İşlem | Nerede | Ne yapar |
|--------|--------|----------|
| **Bağla** | OAuth yokken kanal satırında | Panel kanalını YouTube'a bağlar |
| **Hesap değiştir** | Bağlı kanalda | **Aynı** panel kanalında OAuth'u değiştirir |
| **Kaldır** | Kanal satırında kırmızı link | Panel kanalını, kuyruğu ve OAuth token'ı siler (YouTube'daki videolar kalır) |
| **Yeni kanal ekle** | YouTube hesapları altındaki mor kutu | **Yeni** panel slotu açar, sonra yeni Google hesabı bağlanır |

Aynı niche'te iki kanal çalıştırabilirsiniz (ör. iki motivation markası); ses/kurallar ortaktır, kuyruk ve YouTube girişi ayrıdır.

### Hazır niche'ler (dropdown)

| Niche | Varsayılan ses |
|-------|----------------|
| `motivation` | Liam |
| `beauty` | Jessica |
| `finance` | Adam |
| `tech` | Daniel |
| `health` | Rachel |
| `gaming` | Josh |

Ses ve kurallar: `config/niches.json`. Yeni niche: aşağıdaki [Yeni niche ekleme](#yeni-niche-ekleme) bölümü.

---

## YouTube bağlantısı

1. `python app.py` çalıştırın
2. **Kanal & ayarlar** bölümünü açın
3. **Bağla** → Google hesap seçici açılır (önce kanal yoksa yukarıdaki **Yeni kanal ekle** ile oluşturun)
4. İzinleri onaylayın

**Bağla** sonrası: `config/creds/channel_<id>_token.json` (kanal başına bir dosya). Google Console JSON’unu buraya koymayın — sadece uygulamanın ürettiği token’lar.

---

## Niche profilleri (ses + AI kuralları)

Ses, ton kuralları ve ek LLM talimatları **niche başına** `config/niches.json` dosyasında tanımlanır:

```json
{
  "niches": {
    "motivation": {
      "label": "Motivation",
      "elevenlabs_voice_id": "TX3LPaxmHKxFdv7VOQHJ",
      "tone_rules": "Energetic, short, motivating…",
      "extra_prompt": ""
    },
    "beauty": {
      "label": "Beauty",
      "elevenlabs_voice_id": "cgSgspJ2msm6clMCkdW9",
      "tone_rules": "Warm, elegant…",
      "extra_prompt": "İsteğe bağlı ek LLM kuralları…"
    }
  }
}
```

Panelden kanal eklerken sadece **panel adı** ve **niche** seçilir; ses ve kurallar bu dosyadan otomatik gelir.

`config/voices.json` yalnızca **ses kataloğu**dur (dropdown etiketleri). Varsayılan ses her niche için `config/niches.json` içindedir. Tek bir kanal için farklı ses istiyorsanız panelde **Kanal & ayarlar → Kanal sesi** bölümünden override seçin; “Niche varsayılanı” seçili kalırsa `niches.json` geçerlidir. Son çare: `.env` içindeki `ELEVENLABS_DEFAULT_VOICE_ID`.

### Yeni niche ekleme

1. `config/niches.json` içine yeni slug ekleyin (ör. `"finance"`).
2. `config/voices.json` listesinden bir `elevenlabs_voice_id` seçin.
3. `tone_rules` (ve isteğe bağlı `extra_prompt`) yazın.
4. `assets/backgrounds/<slug>/` klasörü oluşturup MP4 arka plan ekleyin.
5. *(İsteğe bağlı)* `config/template_styles.json` altında aynı slug için altyazı renkleri.
6. Uygulamayı yeniden başlatın — niche **Yeni kanal** listesinde görünür.

Aynı niche'te birden fazla YouTube kanalı çalıştırabilirsiniz; ses ve AI kuralları ortaktır, kuyruk ve OAuth hesabı ayrıdır.

---

## CLI (isteğe bağlı)

```bash
python main.py run              # Bekleyen işleri üret
python main.py run --job-id 3   # Tek iş
python main.py schedule         # Otomatik planlama
python main.py upload           # YouTube'a yükle
python main.py daemon           # Sürekli üretim döngüsü
```

Günlük kullanım için web paneli önerilir.

---

## Proje yapısı

```
autotube-shorts/
├── app.py              # Flask panel
├── main.py             # CLI
├── config/
│   ├── niches.json     # Niche ses + AI kuralları
│   ├── voices.json     # Ses kataloğu
│   ├── template_styles.json   # Niche altyazı renkleri
│   ├── client_secrets.json          # SİZ: Google OAuth JSON (gitignore)
│   ├── client_secrets.json.example
│   └── creds/                       # UYGULAMA: channel_*_token.json (gitignore)
├── core/
├── templates/dashboard.html
├── assets/backgrounds/ # MP4 arka planlar (yerelde ekle)
├── assets/outputs/     # Render çıktıları (gitignore)
└── data/               # pipeline.db + oauth_state.json (gitignore, çalışınca oluşur)
```

---

## Güvenlik

Commit etmeyin: `.env`, `client_secrets.json`, `config/creds/*`, `data/`, `assets/outputs/*`

```bash
git status   # gizli dosyalar listede olmamalı
```

---

## Sorun giderme

### `redirect_uri_mismatch`

- Google Console redirect URI = `.env` içindeki `OAUTH_REDIRECT_URI`
- Varsayılan: `http://127.0.0.1:5000/oauth/youtube/callback`
- `PORT=5000` olmalı

### `Access blocked`

- OAuth consent → **Test users** listesine hesabınızı ekleyin

### Ollama bağlantı hatası

```bash
ollama serve
ollama pull deepseek-r1:8b
```

### Üretim takıldı

Panelde **Takılı sıfırla** veya ~25 dakika bekleyin.

### Video çok kısa

`.env`: `MIN_VIDEO_SECONDS=30`, `MAX_VIDEO_SECONDS=60` — script yeniden üretilir.

### `uploadLimitExceeded`

YouTube Studio'dan bazı planlı videoları yayınlayın veya silin.

---

## Lisans

MIT — [LICENSE](LICENSE)

## Katkı

API anahtarı veya kişisel kanal verisi içermeyen PR'lar memnuniyetle karşılanır.
