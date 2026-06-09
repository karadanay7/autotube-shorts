# AutoTube Shorts

Automated YouTube Shorts pipeline — Ollama scripts, ElevenLabs voice, MoviePy render, YouTube scheduling.

**Documentation**

| Language | File |
|----------|------|
| English | [README.en.md](README.en.md) |
| Türkçe | [README.tr.md](README.tr.md) |

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cp config/client_secrets.json.example config/client_secrets.json
ollama serve && ollama pull deepseek-r1:8b
python app.py
```

Open **http://127.0.0.1:5000** — panel language: **EN** / **TR** (top right).

## Pipeline

```
Topic → LLM → TTS → Render → Schedule → YouTube upload
```

See the full setup guide (Google OAuth, API keys, workflow, troubleshooting) in [README.en.md](README.en.md) or [README.tr.md](README.tr.md).

**Scheduling:** default is one video per day at a fixed time (`.env`). Details: [README.en.md — Publishing schedule](README.en.md#publishing-schedule) · [README.tr.md — Yayın planlaması](README.tr.md#yayın-planlaması).

**Multi-channel:** one panel channel = one YouTube account. To add more, use **Channels & settings → Add another channel** (not the header dropdown). Details: [README.en.md — Add another YouTube channel](README.en.md#add-another-youtube-channel) · [README.tr.md — Başka YouTube kanalı ekleme](README.tr.md#başka-youtube-kanalı-ekleme).

## License

MIT — see [LICENSE](LICENSE).
