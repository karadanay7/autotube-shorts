"""
ElevenLabs TTS engine with word-level timestamp extraction.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests

from config.settings import (
    ELEVENLABS_API_KEY,
    ELEVENLABS_DEFAULT_VOICE_ID,
    ELEVENLABS_MODEL,
    MAX_VIDEO_SECONDS,
    MIN_VIDEO_SECONDS,
    TEMP_DIR,
)
from core.database import Channel

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"


class TTSEngineError(Exception):
    pass


@dataclass
class TTSResult:
    audio_path: Path
    timestamps_path: Path
    words: list[dict[str, Any]]


def _parse_alignment(alignment: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert ElevenLabs character alignment to word-level timestamps."""
    chars = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])

    if not chars or not starts or not ends:
        return []

    words: list[dict[str, Any]] = []
    current = ""
    word_start: float | None = None
    word_end: float | None = None

    for i, ch in enumerate(chars):
        if ch in (" ", "\n", "\t"):
            if current.strip():
                words.append(
                    {
                        "word": current.strip(),
                        "start": word_start or 0.0,
                        "end": word_end or 0.0,
                    }
                )
            current = ""
            word_start = None
            word_end = None
            continue

        if not current:
            word_start = starts[i]
        current += ch
        word_end = ends[i]

    if current.strip():
        words.append(
            {
                "word": current.strip(),
                "start": word_start or 0.0,
                "end": word_end or 0.0,
            }
        )

    return words


def resolve_voice_id(
    channel: Channel,
    job_voice_id: Optional[str] = None,
) -> str:
    """Channel override → niche profile → env default (see config/niches.json)."""
    from config.niches import channel_voice_id

    return channel_voice_id(channel) or ELEVENLABS_DEFAULT_VOICE_ID


def synthesize_speech(
    channel: Channel,
    script: str,
    job_id: int,
    *,
    voice_id: Optional[str] = None,
) -> TTSResult:
    """Generate MP3 + timestamp JSON via ElevenLabs."""
    if not ELEVENLABS_API_KEY:
        raise TTSEngineError("ELEVENLABS_API_KEY is not configured")

    voice_id = resolve_voice_id(channel, voice_id)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    audio_path = TEMP_DIR / f"job_{job_id}_audio.mp3"
    timestamps_path = TEMP_DIR / f"job_{job_id}_timestamps.json"

    url = f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}/with-timestamps"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "text": script,
        "model_id": ELEVENLABS_MODEL,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise TTSEngineError(f"ElevenLabs request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise TTSEngineError(f"ElevenLabs returned invalid JSON: {exc}") from exc

    try:
        audio_b64 = data.get("audio_base64")
        if not audio_b64:
            raise TTSEngineError("ElevenLabs response missing audio_base64")

        audio_bytes = base64.b64decode(audio_b64)
        audio_path.write_bytes(audio_bytes)

        alignment = data.get("alignment") or data.get("normalized_alignment") or {}
        words = _parse_alignment(alignment)

        if words:
            audio_duration = float(words[-1].get("end", 0))
            if audio_duration < MIN_VIDEO_SECONDS - 2:
                raise TTSEngineError(
                    f"Audio too short ({audio_duration:.1f}s, min ~{MIN_VIDEO_SECONDS}s). "
                    f"Regenerate the script with more content."
                )
            if audio_duration > MAX_VIDEO_SECONDS + 5:
                raise TTSEngineError(
                    f"Audio too long ({audio_duration:.1f}s, max ~{MAX_VIDEO_SECONDS}s). "
                    f"Shorten the script."
                )

        timestamp_data = {
            "job_id": job_id,
            "voice_id": voice_id,
            "words": words,
            "alignment": alignment,
        }
        timestamps_path.write_text(
            json.dumps(timestamp_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return TTSResult(
            audio_path=audio_path,
            timestamps_path=timestamps_path,
            words=words,
        )
    except TTSEngineError:
        raise
    except Exception as exc:
        raise TTSEngineError(f"Failed to save TTS output: {exc}") from exc
