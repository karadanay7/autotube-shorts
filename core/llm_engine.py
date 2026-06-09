"""
LLM engine — script and SEO generation via local Ollama (DeepSeek).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

import requests

from config.settings import (
    CONTENT_LANGUAGE,
    MAX_SCRIPT_WORDS,
    MAX_SHORTS_DESCRIPTION_CHARS,
    MAX_VIDEO_SECONDS,
    MIN_SCRIPT_WORDS,
    MIN_VIDEO_SECONDS,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
)

MAX_SCRIPT_RETRIES = 3
from config.niches import effective_tone_rules, niche_extra_prompt
from core.database import Channel

SYSTEM_PROMPT = """You are a YouTube Shorts script writer. Respond ONLY with valid JSON.
No markdown, no explanation, no code fences.

JSON schema:
{
  "video_title": "string, max 70 chars",
  "youtube_description": "string, short hook only, NO hashtags here",
  "hashtags": ["string", "3-5 tags without #, max {max_desc} chars total with youtube_description"],
  "video_script": "string, spoken voiceover only, {min_words}-{max_words} words",
  "gorsel_etiketler": ["english stock-video keyword", "..."]
}

Duration target: {min_seconds}-{max_seconds} seconds when read aloud at natural pace.
video_script MUST be long enough to fill that window — not a teaser, a complete Short.

Global rules:
- Output language: use ONLY the language given in the user message (ignore other languages in tone notes).
- video_script: spoken words only. No stage directions, brackets, or labels.
- youtube_description + hashtags must fit in {max_desc} characters when combined.
- Match channel tone (energy, style) but never copy channel name into video_script.
- gorsel_etiketler: 3-5 English Pexels search keywords matching the topic visually.

video_script rules (most important):
1. First sentence IS the hook. No warmup, no greeting, no channel intro.
2. Forbidden phrases: welcome, hey guys, subscribe, like and subscribe, thanks for watching, my channel, demo channel.
3. Never say the channel name or any creator intro/outro.
4. Short punchy sentences. Every line must teach, surprise, or inspire the viewer.
5. Structure: hook → 2-3 facts or tips → memorable closing line. Do not end abruptly.
6. Plain text only: letters, numbers, spaces. Punctuation allowed: . , ? !
7. Forbidden characters: quotes, dashes, emojis, asterisks, hashtags, brackets.
"""


@dataclass
class ScriptResult:
    video_title: str
    youtube_description: str
    hashtags: list[str]
    video_script: str
    gorsel_etiketler: list[str]

    @property
    def full_description(self) -> str:
        return format_shorts_description(
            self.youtube_description,
            self.hashtags,
            max_chars=MAX_SHORTS_DESCRIPTION_CHARS,
        )


def format_shorts_description(
    body: str,
    hashtags: list[str],
    *,
    max_chars: int = MAX_SHORTS_DESCRIPTION_CHARS,
) -> str:
    """Pack hook + hashtags into a Shorts-friendly description (default max 100 chars)."""
    body = body.strip()
    tag_parts = [
        tag if tag.startswith("#") else f"#{tag.strip()}"
        for tag in hashtags
        if str(tag).strip()
    ][:5]
    tag_str = " ".join(tag_parts)

    if not tag_str:
        return body[:max_chars]
    if not body:
        return tag_str[:max_chars]

    combined = f"{body} {tag_str}"
    if len(combined) <= max_chars:
        return combined

    room = max_chars - len(tag_str) - 1
    if room < 8:
        return tag_str[:max_chars]
    trimmed = body[:room].rstrip(" ,.;!")
    return f"{trimmed} {tag_str}"


def extract_youtube_tags(description: str) -> list[str]:
    """Pull hashtag tokens for YouTube snippet tags field."""
    tags = []
    for token in description.split():
        if token.startswith("#") and len(token) > 1:
            clean = token.lstrip("#").strip(",.;!")
            if clean and clean not in tags:
                tags.append(clean[:30])
    return tags[:15]


_SCRIPT_INTRO_NOISE = re.compile(
    r"\b("
    r"welcome(?:\s+to)?(?:\s+my)?|"
    r"hey\s+guys|what'?s\s+up|"
    r"subscribe|like\s+and\s+subscribe|"
    r"thanks?\s+for\s+watching|"
    r"demo\s+channel|my\s+channel|"
    r"hit\s+the\s+(?:bell|subscribe)"
    r")\b",
    re.IGNORECASE,
)


def _channel_label(channel: Channel) -> str:
    """Prefer connected YouTube name for tone context (never spoken in script)."""
    if channel.youtube_channel_name and channel.youtube_channel_name.strip():
        return channel.youtube_channel_name.strip()
    return channel.channel_name


def _plain_spoken_text(text: str) -> str:
    """Strip quotes, dashes, and symbols from spoken text."""
    t = text.strip()
    if not t:
        return t

    for ch in ('"', "'", "\u201c", "\u201d", "\u2018", "\u2019", "«", "»", "`"):
        t = t.replace(ch, "")

    for ch in ("—", "–", "-"):
        t = t.replace(ch, " ")

    t = re.sub(r"[*#@~|\\/<>()[\]{}]", " ", t)
    t = re.sub(r"[^0-9A-Za-z\u00C0-\u024F\s.,!?]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s+([.,!?])", r"\1", t)
    return t


def _sanitize_script(script: str) -> str:
    """Drop intro/CTA sentences and normalize plain spoken text."""
    text = _plain_spoken_text(script)
    if not text:
        return script.strip()

    parts = re.split(r"(?<=[.!?])\s+", text)
    kept: list[str] = []
    for i, sentence in enumerate(parts):
        s = sentence.strip()
        if not s:
            continue
        if i < 2 and _SCRIPT_INTRO_NOISE.search(s):
            continue
        if _SCRIPT_INTRO_NOISE.search(s) and len(s.split()) <= 12:
            continue
        kept.append(s)

    cleaned = " ".join(kept).strip()
    return cleaned if cleaned else text


_CTA_NOISE = re.compile(
    r"\b("
    r"subscribe(?:\s+now|\s+for\s+more)?|"
    r"like\s+and\s+subscribe|"
    r"hit\s+that\s+subscribe|"
    r"watch\s+now|"
    r"daily\s+motivation"
    r")\b.*",
    re.IGNORECASE,
)


def _trim_hook(text: str, max_len: int) -> str:
    hook = text.strip().rstrip(".!?")
    if len(hook) <= max_len:
        return hook
    cut = hook[:max_len]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.strip(" ,.;!-")


def condense_shorts_description(
    raw: str,
    *,
    title: str = "",
    max_chars: int = MAX_SHORTS_DESCRIPTION_CHARS,
) -> str:
    """Shrink a legacy long description into a Shorts-safe line (hook + hashtags)."""
    text = (raw or "").strip()
    if not text and not title.strip():
        return format_shorts_description("Shorts", ["shorts"], max_chars=max_chars)

    hash_tags = re.findall(r"#\w+", text)
    body = text
    for tag in hash_tags:
        body = body.replace(tag, "")
    body = re.sub(r"\s+", " ", body).strip()
    body = _CTA_NOISE.sub("", body).strip(" ,.;!-")

    sentences = re.split(r"(?<=[.!?])\s+", body)
    body_hook = _trim_hook(sentences[0] if sentences else body, 48)
    title_hook = _trim_hook(title, 48)

    tag_names = [t.lstrip("#") for t in hash_tags[:3]]
    if not tag_names:
        tag_names = ["shorts"]

    hook = title_hook or body_hook
    while hook:
        condensed = format_shorts_description(hook, tag_names, max_chars=max_chars)
        if len(condensed) <= max_chars:
            return condensed
        if " " in hook:
            hook = hook.rsplit(" ", 1)[0]
        else:
            break

    return format_shorts_description(
        _trim_hook(title or body_hook, 30),
        tag_names[:2],
        max_chars=max_chars,
    )


class LLMEngineError(Exception):
    pass


_THINK_BLOCK = re.compile(
    r"<\s*" + "think" + r"\s*>.*?<\s*/\s*" + "think" + r"\s*>",
    re.DOTALL | re.IGNORECASE,
)


def _parse_json_dict(raw: str) -> dict[str, Any]:
    text = raw.strip()
    text = _THINK_BLOCK.sub("", text).strip()

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start : end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMEngineError(f"LLM returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMEngineError("LLM JSON must be an object")
    return data


def _extract_json(raw: str) -> dict[str, Any]:
    data = _parse_json_dict(raw)

    required = ("video_title", "youtube_description", "hashtags", "video_script")
    missing = [k for k in required if k not in data]
    if missing:
        raise LLMEngineError(f"LLM JSON missing fields: {missing}")

    tags = data.get("gorsel_etiketler", data.get("visual_tags", []))
    if not isinstance(tags, list):
        tags = []
    data["gorsel_etiketler"] = tags

    return data


TOPIC_IDEA_PROMPT = """You are a YouTube Shorts content strategist. Respond ONLY with valid JSON.
No markdown, no explanation.

JSON schema:
{"topics": ["string", "..."]}

Rules:
- Each topic: one punchy Shorts video idea (5-14 words), hook-friendly
- Match the channel niche and tone exactly
- All topics must be different angles, not rephrases
- Do NOT repeat or closely paraphrase topics in the avoid list
- Output language: use ONLY the language given in the user message
- No welcome/subscribe/meta topics
- No brand names, product placements, or buy-this CTAs unless channel tone explicitly allows
"""


def _call_ollama_chat(system: str, user_prompt: str, *, json_format: bool = True) -> str:
    """Call local Ollama chat API with custom system prompt."""
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload: dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }
    if json_format:
        payload["format"] = "json"

    try:
        response = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        content = data.get("message", {}).get("content", "")
        if not content:
            raise LLMEngineError("Ollama returned an empty response")
        return content
    except requests.ConnectionError as exc:
        raise LLMEngineError(
            f"Cannot connect to Ollama ({OLLAMA_BASE_URL}). "
            f"Run: ollama serve && ollama pull {OLLAMA_MODEL}"
        ) from exc
    except requests.RequestException as exc:
        raise LLMEngineError(f"Ollama error: {exc}") from exc


def _call_ollama(user_prompt: str) -> str:
    """Call local Ollama chat API."""
    system = (
        SYSTEM_PROMPT.replace("{min_words}", str(MIN_SCRIPT_WORDS))
        .replace("{max_words}", str(MAX_SCRIPT_WORDS))
        .replace("{min_seconds}", str(MIN_VIDEO_SECONDS))
        .replace("{max_seconds}", str(MAX_VIDEO_SECONDS))
        .replace("{max_desc}", str(MAX_SHORTS_DESCRIPTION_CHARS))
    )
    return _call_ollama_chat(system, user_prompt, json_format=True)


def generate_video_topics(
    channel: Channel,
    count: int = 7,
    *,
    avoid_topics: Optional[list[str]] = None,
) -> list[str]:
    """Generate Shorts topic ideas for a channel niche/tone via Ollama."""
    count = max(1, min(count, 14))
    avoid = avoid_topics or []
    avoid_block = "\n".join(f"- {t}" for t in avoid[:40]) if avoid else "(yok)"

    extra = niche_extra_prompt(channel.niche)
    extra_block = f"\n{extra}\n" if extra else ""
    tone = effective_tone_rules(channel)

    user_prompt = (
        f"Output language: {CONTENT_LANGUAGE}\n"
        f"Channel niche: {channel.niche}\n"
        f"Channel tone: {tone}\n"
        f"YouTube channel (context only): {_channel_label(channel)}\n"
        f"{extra_block}"
        f"Generate exactly {count} unique Shorts video topics.\n"
        f"Avoid duplicating these existing topics:\n{avoid_block}"
    )

    raw_response = _call_ollama_chat(TOPIC_IDEA_PROMPT, user_prompt, json_format=True)
    data = _parse_json_dict(raw_response)
    topics_raw = data.get("topics", [])
    if not isinstance(topics_raw, list) or not topics_raw:
        raise LLMEngineError("LLM did not return a topics array")

    seen: set[str] = set()
    topics: list[str] = []
    for item in topics_raw:
        t = str(item).strip()
        if not t or len(t) < 8:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        topics.append(t[:200])
        if len(topics) >= count:
            break

    if not topics:
        raise LLMEngineError("No valid topics generated")
    return topics


def _build_script_user_prompt(
    channel: Channel,
    raw_topic: str,
    *,
    retry_note: str = "",
) -> str:
    yt_name = _channel_label(channel)
    extra = niche_extra_prompt(channel.niche)
    extra_block = f"\n{extra}\n" if extra else ""
    tone = effective_tone_rules(channel)
    return (
        f"Output language: {CONTENT_LANGUAGE}\n"
        f"Topic: {raw_topic}\n"
        f"Niche: {channel.niche}\n"
        f"Channel tone (style only, never speak channel name): {tone}\n"
        f"YouTube channel label (never put in video_script): {yt_name}\n"
        f"{extra_block}"
        f"Write video_script for a {MIN_VIDEO_SECONDS}-{MAX_VIDEO_SECONDS} second Short "
        f"({MIN_SCRIPT_WORDS}-{MAX_SCRIPT_WORDS} words). "
        f"Hook in the first sentence, then develop the topic with detail, then a strong close."
        f"{retry_note}"
    )


def generate_script(channel: Channel, raw_topic: str) -> ScriptResult:
    """Generate title, description, hashtags and spoken script for a topic."""
    retry_note = ""

    try:
        for attempt in range(MAX_SCRIPT_RETRIES):
            user_prompt = _build_script_user_prompt(
                channel, raw_topic, retry_note=retry_note
            )
            raw_response = _call_ollama(user_prompt)
            data = _extract_json(raw_response)

            script = _sanitize_script(str(data["video_script"]).strip())
            word_count = len(script.split())

            if word_count < MIN_SCRIPT_WORDS:
                if attempt < MAX_SCRIPT_RETRIES - 1:
                    retry_note = (
                        f"\n\nRETRY: Your last script was only {word_count} words "
                        f"({MIN_SCRIPT_WORDS}-{MAX_SCRIPT_WORDS} required for "
                        f"{MIN_VIDEO_SECONDS}-{MAX_VIDEO_SECONDS}s). "
                        "Add more facts, context, and a closing line. Do not repeat the hook only."
                    )
                    continue
                raise LLMEngineError(
                    f"Script too short ({word_count} words, min {MIN_SCRIPT_WORDS} "
                    f"for ~{MIN_VIDEO_SECONDS}s)"
                )

            if word_count > MAX_SCRIPT_WORDS + 20:
                if attempt < MAX_SCRIPT_RETRIES - 1:
                    retry_note = (
                        f"\n\nRETRY: Your last script was {word_count} words "
                        f"(max ~{MAX_SCRIPT_WORDS}). Shorten while keeping the hook and close."
                    )
                    continue
                raise LLMEngineError(
                    f"Script too long ({word_count} words, max ~{MAX_SCRIPT_WORDS})"
                )

            hashtags = data["hashtags"]
            if not isinstance(hashtags, list):
                raise LLMEngineError("hashtags must be a JSON array")

            visual_tags = data.get("gorsel_etiketler", [])
            if not isinstance(visual_tags, list):
                visual_tags = []

            short_body = str(data["youtube_description"]).strip()
            tag_list = [str(h).strip().lstrip("#") for h in hashtags[:5]]
            formatted_desc = format_shorts_description(short_body, tag_list)

            if len(formatted_desc) > MAX_SHORTS_DESCRIPTION_CHARS + 5:
                raise LLMEngineError(
                    f"Description too long ({len(formatted_desc)} chars, "
                    f"max {MAX_SHORTS_DESCRIPTION_CHARS})"
                )

            return ScriptResult(
                video_title=_plain_spoken_text(str(data["video_title"]).strip())[:100],
                youtube_description=_plain_spoken_text(short_body)[:60],
                hashtags=tag_list,
                video_script=script,
                gorsel_etiketler=[str(t).strip() for t in visual_tags[:5]],
            )

        raise LLMEngineError("Script generation failed after retries")
    except LLMEngineError:
        raise
    except Exception as exc:
        raise LLMEngineError(f"Unexpected LLM error: {exc}") from exc
