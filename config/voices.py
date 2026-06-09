"""ElevenLabs voice catalog — labels only. Default voice per niche: config/niches.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

VOICES_FILE = Path(__file__).resolve().parent / "voices.json"


def load_voices() -> list[dict]:
    """All voices from voices.json (for dropdown labels)."""
    if not VOICES_FILE.exists():
        return []
    try:
        data = json.loads(VOICES_FILE.read_text(encoding="utf-8"))
        return data.get("voices", [])
    except (json.JSONDecodeError, OSError):
        return []


def voice_label(voice_id: Optional[str]) -> str:
    if not voice_id:
        return "—"
    for v in load_voices():
        if v["id"] == voice_id:
            return v.get("label", v.get("name", voice_id))
    return voice_id
