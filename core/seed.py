"""Seed channels from channels_config.json on first run."""

from __future__ import annotations

import json

from config.niches import get_niche
from config.settings import CHANNELS_CONFIG, CREDS_DIR
from core.database import create_channel, list_channels


def seed_channels_from_config() -> int:
    """Import channels from JSON config if database is empty."""
    if list_channels():
        return 0

    if not CHANNELS_CONFIG.exists():
        return 0

    try:
        data = json.loads(CHANNELS_CONFIG.read_text(encoding="utf-8"))
        channels = data.get("channels", [])
    except (json.JSONDecodeError, OSError):
        return 0

    CREDS_DIR.mkdir(parents=True, exist_ok=True)
    created = 0

    for ch in channels:
        niche = (ch.get("niche") or "").strip()
        if not niche:
            continue
        profile = get_niche(niche)
        tone = (ch.get("tone_rules") or "").strip() or (
            str(profile.get("tone_rules", "")) if profile else ""
        )
        if not tone:
            continue
        creds_path = f"config/creds/channel_placeholder_{created + 1}.json"
        create_channel(
            channel_name=ch["channel_name"],
            niche=niche,
            tone_rules=tone,
            youtube_credentials_path=creds_path,
            elevenlabs_voice_id=None,
        )
        created += 1

    return created
