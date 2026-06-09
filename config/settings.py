import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Paths
OUTPUTS_DIR = PROJECT_ROOT / "assets" / "outputs"
TEMP_DIR = PROJECT_ROOT / "assets" / "temp"
BACKGROUNDS_DIR = PROJECT_ROOT / "assets" / "backgrounds"
BRANDING_DIR = PROJECT_ROOT / "assets" / "branding"
FONTS_DIR = PROJECT_ROOT / "assets" / "fonts"
TEMPLATE_STYLES_FILE = PROJECT_ROOT / "config" / "template_styles.json"
CREDS_DIR = PROJECT_ROOT / "config" / "creds"
# Server
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "5001"))
# Ollama + DeepSeek (local LLM, no API key)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-r1:8b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))

# Pexels stock video
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PEXELS_VIDEOS_PER_TAG = int(os.getenv("PEXELS_VIDEOS_PER_TAG", "3"))

# ElevenLabs
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_DEFAULT_VOICE_ID = os.getenv(
    "ELEVENLABS_DEFAULT_VOICE_ID", "TX3LPaxmHKxFdv7VOQHJ"
)
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2_5")
CONTENT_LANGUAGE = os.getenv("CONTENT_LANGUAGE", "English")

# YouTube
GOOGLE_CLIENT_SECRETS = Path(
    os.getenv("GOOGLE_CLIENT_SECRETS", str(PROJECT_ROOT / "config" / "client_secrets.json"))
)
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.readonly",
]
OAUTH_REDIRECT_URI = os.getenv(
    "OAUTH_REDIRECT_URI", f"http://{HOST}:{PORT}/oauth/youtube/callback"
)
# Local dev: http://127.0.0.1 callback (oauthlib expects HTTPS otherwise)
if OAUTH_REDIRECT_URI.startswith("http://"):
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

# Video
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 30
MIN_VIDEO_SECONDS = int(os.getenv("MIN_VIDEO_SECONDS", "30"))
MAX_VIDEO_SECONDS = int(os.getenv("MAX_VIDEO_SECONDS", "60"))
SPEECH_WORDS_PER_MINUTE = int(os.getenv("SPEECH_WORDS_PER_MINUTE", "150"))
# ~75 words @ 30s, ~150 words @ 60s at default WPM (override via env if needed)
MIN_SCRIPT_WORDS = int(
    os.getenv(
        "MIN_SCRIPT_WORDS",
        str(max(1, int(MIN_VIDEO_SECONDS * SPEECH_WORDS_PER_MINUTE / 60))),
    )
)
MAX_SCRIPT_WORDS = int(
    os.getenv(
        "MAX_SCRIPT_WORDS",
        str(max(MIN_SCRIPT_WORDS + 1, int(MAX_VIDEO_SECONDS * SPEECH_WORDS_PER_MINUTE / 60))),
    )
)
MAX_SHORTS_DESCRIPTION_CHARS = int(os.getenv("MAX_SHORTS_DESCRIPTION_CHARS", "100"))
YOUTUBE_DECLARE_SYNTHETIC_MEDIA = os.getenv(
    "YOUTUBE_DECLARE_SYNTHETIC_MEDIA", "true"
).lower() in ("1", "true", "yes")

# Publishing schedule — daily fixed time is the default (see README)
SCHEDULE_DISPLAY_TIMEZONE = os.getenv("SCHEDULE_DISPLAY_TIMEZONE", "Europe/Istanbul")
SCHEDULE_DAILY_HOUR = int(os.getenv("SCHEDULE_DAILY_HOUR", "20"))
SCHEDULE_DAILY_MINUTE = int(os.getenv("SCHEDULE_DAILY_MINUTE", "0"))
SCHEDULE_MIN_LEAD_MINUTES = int(os.getenv("SCHEDULE_MIN_LEAD_MINUTES", "60"))
# Advanced / optional (not needed for daily Istanbul-style scheduling)
SCHEDULE_US_PEAK_HOURS = os.getenv("SCHEDULE_US_PEAK_HOURS", "false").lower() in (
    "1",
    "true",
    "yes",
)
SCHEDULE_TIMEZONE = os.getenv("SCHEDULE_TIMEZONE", "America/New_York")
SCHEDULE_INTERVAL_HOURS = int(os.getenv("SCHEDULE_INTERVAL_HOURS", "24"))
DAEMON_INTERVAL_SECONDS = int(os.getenv("DAEMON_INTERVAL_SECONDS", "300"))

# OAuth state (dev)
OAUTH_STATE_FILE = PROJECT_ROOT / "data" / "oauth_state.json"


def ensure_dirs() -> None:
    for path in (OUTPUTS_DIR, TEMP_DIR, BACKGROUNDS_DIR, BRANDING_DIR, FONTS_DIR, CREDS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def check_ollama_available() -> bool:
    """Ping local Ollama server."""
    try:
        import requests

        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def api_status() -> dict[str, bool]:
    return {
        "ollama": check_ollama_available(),
        "pexels": bool(PEXELS_API_KEY),
        "elevenlabs": bool(ELEVENLABS_API_KEY),
        "youtube_oauth": GOOGLE_CLIENT_SECRETS.exists(),
    }
