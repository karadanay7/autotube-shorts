# AutoTube-12

Automated YouTube Shorts pipeline with a local admin panel. Generate scripts with **Ollama**, voice with **ElevenLabs**, render vertical videos with **MoviePy**, then schedule and upload to **YouTube** — one channel per Google account.

```
Topic → LLM script → TTS + timestamps → video render → schedule → YouTube upload
```

## Features

- **Multi-channel** — separate OAuth tokens, queues, and voices per channel
- **Web admin panel** — add topics, run production, edit SEO, schedule, upload
- **AI topic generation** — weekly topic ideas per channel niche and tone
- **Daily scheduling** — one slot per channel per day (configurable timezone)
- **Manual upload control** — production and upload are separate steps
- **Local LLM** — no paid AI API required when using Ollama

## Requirements

| Tool | Purpose |
|------|---------|
| Python 3.10+ | Runtime |
| [Ollama](https://ollama.com/) | Local LLM (e.g. `deepseek-r1:8b`) |
| [FFmpeg](https://ffmpeg.org/) | Video encoding (MoviePy dependency) |
| ElevenLabs API key | Text-to-speech |
| Google Cloud project | YouTube Data API v3 + OAuth |
| Pexels API key (optional) | Stock background footage |

## Quick start

```bash
git clone https://github.com/karadanay7/autotube-shorts.git
cd autotube-shorts

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — see sections below

cp config/client_secrets.json.example config/client_secrets.json
# Edit with your Google OAuth credentials

ollama serve
ollama pull deepseek-r1:8b

python app.py
```

Open **http://127.0.0.1:5000** — the admin panel loads with example channels from `config/channels_config.json`.

---

## Environment variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `OLLAMA_BASE_URL` | Ollama API URL (default `http://127.0.0.1:11434`) |
| `OLLAMA_MODEL` | Model name (default `deepseek-r1:8b`) |
| `ELEVENLABS_API_KEY` | From [ElevenLabs](https://elevenlabs.io/) → Profile → API keys |
| `ELEVENLABS_DEFAULT_VOICE_ID` | Default voice when a channel has no voice set |
| `PEXELS_API_KEY` | From [Pexels API](https://www.pexels.com/api/) (optional) |
| `GOOGLE_CLIENT_SECRETS` | Path to OAuth JSON (default `config/client_secrets.json`) |
| `OAUTH_REDIRECT_URI` | Must match Google Console exactly |
| `PORT` | Flask port (default `5000`) — must match OAuth redirect URI |
| `SCHEDULE_DISPLAY_TIMEZONE` | Timezone for daily auto-schedule (e.g. `Europe/Istanbul`) |
| `SCHEDULE_DAILY_HOUR` / `SCHEDULE_DAILY_MINUTE` | Daily publish time (e.g. `20` / `0` → 20:00 in that timezone) |

**Never commit `.env` or real API keys.**

---

## Google Cloud setup (YouTube OAuth)

You need a Google Cloud project with **YouTube Data API v3** enabled and an **OAuth 2.0 Web client**.

### 1. Create a project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. **Select a project** → **New project** → name it (e.g. `autotube-youtube`)
3. Open the project

### 2. Enable YouTube Data API v3

1. **APIs & Services** → **Library**
2. Search **YouTube Data API v3** → **Enable**

### 3. OAuth consent screen

1. **APIs & Services** → **OAuth consent screen**
2. User type: **External** (for personal channels) or **Internal** (Google Workspace only)
3. Fill in app name, support email, developer contact
4. **Scopes** → Add:
   - `https://www.googleapis.com/auth/youtube.upload`
   - `https://www.googleapis.com/auth/youtube.readonly`
   - `https://www.googleapis.com/auth/youtube.force-ssl`
5. **Test users** (required while app is in *Testing*):
   - Add the Google account(s) that own your YouTube channels
   - Each account you connect must be listed here until you publish the app
6. Save

> While status is **Testing**, only test users can authorize. For public use you must submit for verification; for personal channels, testing mode with test users is usually enough.

### 4. Create OAuth credentials

1. **APIs & Services** → **Credentials** → **Create credentials** → **OAuth client ID**
2. Application type: **Web application**
3. Name: e.g. `AutoTube local`
4. **Authorized redirect URIs** — add exactly:

   ```
   http://127.0.0.1:5000/oauth/youtube/callback
   ```

   Must match `PORT` in `.env` and `OAUTH_REDIRECT_URI`. Use `127.0.0.1`, not `localhost`, if that is what you configured.

5. **Create** → download JSON or copy **Client ID** and **Client secret**

### 5. Install `client_secrets.json`

```bash
cp config/client_secrets.json.example config/client_secrets.json
```

Paste your values into `config/client_secrets.json`:

```json
{
  "web": {
    "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
    "project_id": "your-project-id",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret": "YOUR_CLIENT_SECRET",
    "redirect_uris": [
      "http://127.0.0.1:5000/oauth/youtube/callback"
    ]
  }
}
```

Or rename the file downloaded from Google Console to `config/client_secrets.json` and ensure `redirect_uris` includes the callback above.

---

## ElevenLabs API key

1. Sign up at [elevenlabs.io](https://elevenlabs.io/)
2. **Profile** → **API keys** → create a key
3. Add to `.env`:

   ```
   ELEVENLABS_API_KEY=your_key_here
   ```

`config/voices.json` is only the **voice catalog** (IDs and labels for dropdowns). **Default voice per niche** lives in `config/niches.json` (`elevenlabs_voice_id` on each niche). In the panel, **Channels & settings → Channel voice** you can override the niche default for a single channel; leave “Use niche default” selected otherwise. Last-resort fallback: `ELEVENLABS_DEFAULT_VOICE_ID` in `.env`.

---

## Pexels API key (optional)

1. Create a free account at [pexels.com/api](https://www.pexels.com/api/)
2. Copy your API key into `.env`:

   ```
   PEXELS_API_KEY=your_pexels_key
   ```

If omitted, use your own background MP4 files under `assets/backgrounds/<niche>/`.

---

## Niche profiles (voice + AI rules)

Voice, tone rules, and extra LLM instructions are defined **per niche** in `config/niches.json`:

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
      "extra_prompt": "Optional extra LLM rules for this niche…"
    }
  }
}
```

| Field | Purpose |
|-------|---------|
| **label** | Shown in the “new channel” dropdown |
| **elevenlabs_voice_id** | TTS voice for every channel with this niche (e.g. motivation → Liam, beauty → Jessica) |
| **tone_rules** | Main LLM style instructions |
| **extra_prompt** | Optional second block (topic ideas, forbidden phrases, visual hints) |

When you add a channel in the panel, you only pick **panel name** + **niche**. Voice and rules come from this file automatically.

### Adding a new niche

1. Add an entry to `config/niches.json` (new slug, e.g. `"finance"`).
2. Pick a voice ID from `config/voices.json` (or ElevenLabs dashboard).
3. Write `tone_rules` (and optional `extra_prompt`) for your content style.
4. Create folder `assets/backgrounds/<slug>/` and add MP4 background clips.
5. *(Optional)* Add subtitle colors in `config/template_styles.json` under the same slug.
6. Restart the app — the niche appears in **New channel**.

You can run multiple YouTube channels on the same niche (e.g. two motivation channels); they share voice and AI rules but have separate queues and OAuth accounts.

---

## Channels configuration (seed only)

On first run, example channels are imported from `config/channels_config.json` if the database is empty:

```json
{
  "channels": [
    { "channel_name": "Motivation Channel", "niche": "motivation" },
    { "channel_name": "Beauty Channel", "niche": "beauty" }
  ]
}
```

- **channel_name** — label in the admin panel (your YouTube brand name)
- **niche** — must match a slug in `config/niches.json`

Copy `config/channels_config.json.example` for a minimal seed, or add channels in the panel (see below).

### Built-in niches (dropdown)

| Niche slug | Default voice (ElevenLabs) |
|------------|----------------------------|
| `motivation` | Liam |
| `beauty` | Jessica |
| `finance` | Adam |
| `tech` | Daniel |
| `health` | Rachel |
| `gaming` | Josh |

Edit voices and AI rules in `config/niches.json`. Add more niches anytime (see [Adding a new niche](#adding-a-new-niche)).

---

## Add another YouTube channel

**One panel channel = one YouTube account** (separate queue, OAuth token, and optional voice override).

The header **channel dropdown** only switches between existing channels — it does not create new ones.

### Add a 3rd (or more) YouTube account

1. Open **Channels & settings** (bottom section of the panel).
2. Under **YouTube accounts**, read the list of connected channels.
3. In the purple **Add another channel** box:
   - Enter a **panel name** (label for you, e.g. `Finance Channel`).
   - Pick a **niche** from the dropdown (voice + AI rules come from `config/niches.json`).
   - Leave **Connect YouTube after create** checked.
4. Click **+ Create** → Google account picker opens.
5. Sign in with the **other** Google account that owns the target YouTube channel.

### Connect vs switch account

| Action | Where | What it does |
|--------|--------|----------------|
| **Connect** | Next to a channel with no OAuth | Links that panel channel to a YouTube account |
| **Switch account** | Next to a connected channel | Replaces OAuth on the **same** panel channel |
| **Remove** | Red link on each channel row | Deletes the panel channel, queue, and OAuth token (YouTube uploads stay online) |
| **Add another channel** | Purple box under YouTube accounts | Creates a **new** panel slot, then you Connect a new Google account |

You can run two channels on the same niche (e.g. two motivation brands); they share niche voice/rules but have separate queues and YouTube logins.

---

## Connect YouTube (per channel)

1. Start the app: `python app.py`
2. Open **Channels & settings**
3. Click **Connect** next to a channel (or create one first — see above)
4. Google opens an account picker — choose the Google account that owns that YouTube channel
5. Approve permissions → you are redirected back to the panel

Each channel stores its token in `config/creds/` (gitignored).

No email is entered in the UI — OAuth uses Google's account picker (`select_account`).

---

## How to use (panel workflow)

Open **http://127.0.0.1:5000** after `python app.py`. Use **EN / TR** in the top-right to switch language.

### Daily flow

```
Add topics → Produce → Ready (SEO) → Schedule → Upload → Sync
```

| Step | Button / section | What happens |
|------|------------------|--------------|
| 1 | Channel dropdown | Switch between channels (separate queue & YouTube account each) |
| 2 | **Production — add topics** | Add one topic, bulk lines, or AI weekly topics |
| 3 | **Produce** | Runs jobs **one by one**: LLM script → ElevenLabs TTS → video render |
| 4 | **Ready videos** | Preview MP4, edit title/description (≤100 chars), set publish time |
| 5 | **Schedule** (header) | Assigns the next daily slot to all ready videos without a time |
| 6 | **Upload** (header) | Uploads scheduled videos to YouTube (private/scheduled) |
| 7 | **Sync** (header) | Reads real publish times from YouTube into the database |

The panel **auto-refreshes** while production or upload runs (stats, queue, ready/YouTube lists).

### Rules

- Only **Ready** videos are scheduled — **Pending** queue jobs are ignored until rendered.
- **Produce** runs **pending** jobs only (failed jobs are skipped).
- **Failed** jobs do not retry automatically — use **Retry** on the row, **Retry failed** in the header, or **Retry selected** in the queue toolbar.
- **Produce** / **Retry** process jobs **one by one**; per-row **Run** / **Retry** is for a single job.
- Videos target **30–60 seconds** (configure via `MIN_VIDEO_SECONDS` / `MAX_VIDEO_SECONDS` in `.env`).
- Each channel needs its own **Connect** OAuth (Google account picker).

---

## Publishing schedule

The panel header shows the **active auto-schedule rule** (read from your `.env`). Changing the default time is done in `.env`, not in a dropdown — restart `python app.py` after edits.

### Three ways to set a publish time

| Method | Where | What it does |
|--------|-------|----------------|
| **Schedule** (header) | Top bar | Assigns the next auto slot to every **Ready** video that has no time yet (active channel) |
| **Edit & schedule** | Ready videos → expand row | Pick a date/time for **one** video (`datetime-local`). Leave empty and submit → same as auto slot for that video only |
| **Sync** (header) | Top bar | Reads real publish times from YouTube into the database (does not upload) |

Flow: **Produce** → **Ready** → **Schedule** → **Upload** → **Sync**.

### Default mode: daily fixed time (recommended)

When `SCHEDULE_US_PEAK_HOURS=false` (default in `.env.example`):

- Each **channel** gets **at most one publish per calendar day**.
- Time is **`SCHEDULE_DAILY_HOUR:SCHEDULE_DAILY_MINUTE`** in **`SCHEDULE_DISPLAY_TIMEZONE`**.
- Example from `.env.example`: **20:00 UTC** every day.
- If you use `SCHEDULE_DISPLAY_TIMEZONE=Europe/Istanbul` and `SCHEDULE_DAILY_HOUR=20`, slots are **20:00 Istanbul time**.
- Days that already have a scheduled or published video (YouTube API + local DB) are **skipped** — the next free day is used.
- Several ready videos → consecutive days at the **same clock time** (e.g. Mon 20:00, Tue 20:00, Wed 20:00).
- Slots must be at least **`SCHEDULE_MIN_LEAD_MINUTES`** in the future (default 60 minutes).

### Alternative: US peak hours

Set `SCHEDULE_US_PEAK_HOURS=true` in `.env`. Auto-schedule picks the next slot inside US viewing peaks (`SCHEDULE_TIMEZONE`, default Eastern), varying by weekday (Mon–Sun). Useful when your audience is mostly US-based.

### How to change the default “every day at this time”

Edit `.env` (only these three lines are required for daily scheduling):

```env
SCHEDULE_DISPLAY_TIMEZONE=Europe/Istanbul
SCHEDULE_DAILY_HOUR=18
SCHEDULE_DAILY_MINUTE=30
```

Restart the app. The panel header updates to show the new rule (e.g. `Daily 18:30 Europe/Istanbul`).

Optional advanced vars (defaults in `config/settings.py`): `SCHEDULE_MIN_LEAD_MINUTES`, `SCHEDULE_US_PEAK_HOURS`, `SCHEDULE_TIMEZONE`.

**Per-video override** does not require restart: open **Ready videos → Edit & schedule** and choose any date/time.

### Why no schedule dropdown in the panel?

Global defaults live in `.env` so they stay stable across restarts and match the CLI (`python main.py schedule`). A panel dropdown would need to write config and restart the server; for now, `.env` is the single source of truth. The header shows the current rule; per-video times use the datetime picker in **Ready**.

---

## CLI (optional)

```bash
python main.py run              # Process all pending jobs
python main.py run --job-id 3   # Process one job
python main.py schedule         # Auto-assign publish times
python main.py upload           # Upload scheduled ready videos
python main.py daemon           # Continuous production loop
```

The web panel is the recommended interface for day-to-day use.

---

## Project layout

```
autotube-shorts/
├── app.py                 # Flask admin panel
├── main.py                # CLI orchestrator
├── config/
│   ├── channels_config.json
│   ├── client_secrets.json.example
│   ├── voices.json
│   └── creds/             # OAuth tokens (gitignored)
├── core/                  # LLM, TTS, video, YouTube, scheduler
├── templates/dashboard.html
├── assets/
│   ├── backgrounds/<niche>/   # Background MP4 files
│   ├── outputs/                 # Rendered videos
│   └── temp/                    # Audio, timestamps
└── data/                  # SQLite DB (gitignored)
```

---

## Security — do not commit

These files contain secrets or personal data and are listed in `.gitignore`:

| Path | Contents |
|------|----------|
| `.env` | API keys |
| `config/client_secrets.json` | Google OAuth client secret |
| `config/creds/*` | YouTube OAuth tokens |
| `data/` | SQLite database with job history |
| `assets/outputs/*` | Rendered videos |

Before publishing to GitHub, verify:

```bash
git status
# Should NOT list .env, client_secrets.json, creds/, or data/
```

---

## Troubleshooting

### `redirect_uri_mismatch`

- Redirect URI in Google Console must **exactly** match `OAUTH_REDIRECT_URI` in `.env`
- Default: `http://127.0.0.1:5000/oauth/youtube/callback`
- `PORT` in `.env` must be `5000` if that is your redirect URI
- Restart `python app.py` after changing `.env`

### `Access blocked` / app not verified

- Add your Google account under **OAuth consent screen → Test users**
- Or publish the app (verification required for external users)

### Ollama connection error

```bash
ollama serve
ollama pull deepseek-r1:8b
```

Check `OLLAMA_BASE_URL` and `OLLAMA_MODEL` in `.env`.

### Production stuck

Use **Reset stuck** in the panel, or wait for automatic stale recovery (~25 minutes).

### YouTube `uploadLimitExceeded`

YouTube limits how many scheduled/private uploads a channel can have. Publish or delete some scheduled videos in YouTube Studio, then try again.

### FFmpeg not found

Install FFmpeg and ensure it is on your `PATH`:

```bash
# macOS
brew install ffmpeg

# Ubuntu
sudo apt install ffmpeg
```

---

## License

MIT — see [LICENSE](LICENSE) if included, or add your preferred open-source license before publishing.

## Contributing

Issues and pull requests welcome. Please do not include API keys, OAuth secrets, or personal channel data in submissions.
