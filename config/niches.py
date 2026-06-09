"""Niche profiles — voice, tone rules, and LLM extras (single source of truth)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from config.settings import ELEVENLABS_DEFAULT_VOICE_ID

NICHES_FILE = Path(__file__).resolve().parent / "niches.json"


def _load_data() -> dict[str, Any]:
    if not NICHES_FILE.exists():
        return {}
    try:
        return json.loads(NICHES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def list_niches() -> list[dict[str, str]]:
    """All niche profiles for UI dropdowns (slug + label)."""
    niches = _load_data().get("niches", {})
    rows: list[dict[str, str]] = []
    for slug in sorted(niches.keys()):
        entry = niches[slug] or {}
        rows.append(
            {
                "slug": slug,
                "label": entry.get("label") or slug.replace("_", " ").title(),
            }
        )
    return rows


def list_niche_profiles(*, tone_preview_len: int = 140) -> list[dict[str, str]]:
    """Niche rows with voice label and tone preview for the admin UI."""
    from config.voices import voice_label

    profiles: list[dict[str, str]] = []
    for row in list_niches():
        slug = row["slug"]
        tone = niche_tone_rules(slug)
        voice_id = niche_voice_id(slug)
        if len(tone) > tone_preview_len:
            tone_preview = tone[:tone_preview_len].rstrip() + "…"
        else:
            tone_preview = tone
        profiles.append(
            {
                **row,
                "voice_id": voice_id,
                "voice_label": voice_label(voice_id),
                "tone_preview": tone_preview,
            }
        )
    return profiles


def get_niche(slug: Optional[str]) -> Optional[dict[str, Any]]:
    if not slug:
        return None
    key = slug.strip().lower()
    entry = _load_data().get("niches", {}).get(key)
    if not entry:
        return None
    return {"slug": key, **entry}


def niche_voice_id(niche: Optional[str]) -> str:
    """Voice for a niche slug (config/niches.json), else env ELEVENLABS_DEFAULT_VOICE_ID."""
    profile = get_niche(niche)
    if profile and profile.get("elevenlabs_voice_id"):
        return str(profile["elevenlabs_voice_id"])
    return ELEVENLABS_DEFAULT_VOICE_ID


def channel_voice_override(channel) -> Optional[str]:
    raw = getattr(channel, "elevenlabs_voice_id", None) if channel else None
    return str(raw).strip() if raw and str(raw).strip() else None


def niche_tone_rules(niche: Optional[str]) -> str:
    profile = get_niche(niche)
    if profile:
        return str(profile.get("tone_rules") or "").strip()
    return ""


def niche_extra_prompt(niche: Optional[str]) -> str:
    profile = get_niche(niche)
    if profile:
        return str(profile.get("extra_prompt") or "").strip()
    return ""


def effective_tone_rules(channel) -> str:
    """Niche config first; DB tone_rules fallback for legacy/custom slugs."""
    from_db = (getattr(channel, "tone_rules", None) or "").strip()
    from_niche = niche_tone_rules(getattr(channel, "niche", None))
    return from_niche or from_db


def channel_voice_id(channel) -> str:
    """
    Resolved TTS voice: channel override → niche profile → env default.
  """
    override = channel_voice_override(channel)
    if override:
        return override
    if channel:
        return niche_voice_id(getattr(channel, "niche", None))
    return ELEVENLABS_DEFAULT_VOICE_ID


def niche_default_voice_id(channel) -> str:
    """Niche profile voice only (ignores per-channel override)."""
    if not channel:
        return ELEVENLABS_DEFAULT_VOICE_ID
    return niche_voice_id(getattr(channel, "niche", None))
