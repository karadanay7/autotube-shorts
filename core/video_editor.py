"""
MoviePy video editor — katmanlı şablon: arka plan, blur, glass, watermark, altyazı.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# MoviePy 1.x + Pillow 10+: ANTIALIAS removed — use LANCZOS
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

from config.settings import (
    BACKGROUNDS_DIR,
    BRANDING_DIR,
    FONTS_DIR,
    OUTPUTS_DIR,
    TEMPLATE_STYLES_FILE,
    VIDEO_FPS,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
SUBTITLE_CANVAS_HEIGHT = 200


class VideoEditorError(Exception):
    pass


def list_backgrounds(niche: str) -> list[Path]:
    """List available background videos for a niche (local pool)."""
    niche_dir = BACKGROUNDS_DIR / niche
    if not niche_dir.exists():
        return []

    files = [
        p
        for p in niche_dir.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    ]
    return sorted(files)


def pick_background(
    niche: str,
    preferred: Optional[str] = None,
) -> Optional[Path]:
    """Select background — preferred path or random from local niche pool."""
    import random

    if preferred:
        candidate = Path(preferred)
        if not candidate.is_absolute():
            candidate = BACKGROUNDS_DIR / preferred
        if candidate.exists():
            return candidate

    pool = list_backgrounds(niche)
    return random.choice(pool) if pool else None


def _load_template_style(niche: str) -> dict[str, Any]:
    """Load niche-specific template overrides merged with default."""
    default: dict[str, Any] = {
        "subtitle_color": [255, 255, 255],
        "accent_color": [255, 255, 255],
        "stroke_color": [0, 0, 0],
        "stroke_width": 6,
        "blur_sigma": 2,
        "darken_opacity": 0.42,
        "font_size": 76,
        "subtitle_y_ratio": 0.62,
    }
    if not TEMPLATE_STYLES_FILE.exists():
        return default

    try:
        data = json.loads(TEMPLATE_STYLES_FILE.read_text(encoding="utf-8"))
        base = data.get("default", {})
        niche_style = data.get(niche, {})
        merged = {**default, **base, **niche_style}
        return merged
    except (json.JSONDecodeError, OSError):
        return default


def _load_timestamps(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("words", [])
    except Exception as exc:
        raise VideoEditorError(f"Failed to read timestamps: {exc}") from exc


def _resolve_font(size: int = 72) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        FONTS_DIR / "Montserrat-Bold.ttf",
        FONTS_DIR / "Arial-Bold.ttf",
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for font_path in candidates:
        if font_path.exists():
            try:
                return ImageFont.truetype(str(font_path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _make_subtitle_image(
    text: str,
    style: dict[str, Any],
    *,
    emphasized: bool = False,
) -> np.ndarray:
    """White text with black outline — readable on any background without a box."""
    width = VIDEO_WIDTH
    font_size = int(style.get("font_size", 76))
    if emphasized:
        font_size = int(font_size * 1.12)

    font = _resolve_font(font_size)
    img = Image.new("RGBA", (width, SUBTITLE_CANVAS_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    canvas_h = SUBTITLE_CANVAS_HEIGHT
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (width - text_w) // 2 - bbox[0]
    y = (canvas_h - text_h) // 2 - bbox[1]

    stroke_rgb = tuple(style.get("stroke_color", [0, 0, 0]))
    fill_rgb = tuple(style.get("subtitle_color", [255, 255, 255]))
    stroke_width = int(style.get("stroke_width", 6))

    draw.text(
        (x, y),
        text,
        font=font,
        fill=fill_rgb + (255,),
        stroke_width=stroke_width,
        stroke_fill=stroke_rgb + (255,),
    )
    return np.array(img)


def _find_watermark(niche: str, channel_id: Optional[int] = None) -> Optional[Path]:
    """Locate channel/niche branding PNG."""
    candidates = []
    if channel_id:
        candidates.append(BRANDING_DIR / f"channel_{channel_id}" / "logo.png")
    candidates.extend([
        BRANDING_DIR / niche / "logo.png",
        BRANDING_DIR / niche / "watermark.png",
        BRANDING_DIR / "default" / "logo.png",
    ])
    for path in candidates:
        if path.exists():
            return path
    return None


def _create_gradient_background(duration: float, niche: str):
    from moviepy.editor import ColorClip

    colors = {
        "motivation": (20, 30, 60),
        "finance": (10, 40, 30),
        "health": (15, 50, 35),
        "tech": (25, 20, 50),
        "gaming": (40, 10, 50),
        "beauty": (55, 32, 48),
    }
    rgb = colors.get(niche, (30, 30, 40))
    return ColorClip(size=(VIDEO_WIDTH, VIDEO_HEIGHT), color=rgb, duration=duration)


def _fit_background_clip(clip):
    target_ratio = VIDEO_WIDTH / VIDEO_HEIGHT
    clip_ratio = clip.w / clip.h

    if clip_ratio > target_ratio:
        new_w = int(clip.h * target_ratio)
        x1 = (clip.w - new_w) // 2
        clip = clip.crop(x1=x1, width=new_w)
    else:
        new_h = int(clip.w / target_ratio)
        y1 = (clip.h - new_h) // 2
        clip = clip.crop(y1=y1, height=new_h)

    return clip.resize((VIDEO_WIDTH, VIDEO_HEIGHT))


def _apply_background_effects(bg, style: dict[str, Any], duration: float):
    """Blur + darken overlay on background layer."""
    from moviepy.editor import ColorClip, CompositeVideoClip
    import moviepy.video.fx.all as vfx

    sigma = float(style.get("blur_sigma", 2))
    if sigma > 0:
        try:
            bg = bg.fx(vfx.blur, sigma)
        except Exception:
            pass

    darken = float(style.get("darken_opacity", 0.42))
    if darken > 0:
        overlay = (
            ColorClip(size=(VIDEO_WIDTH, VIDEO_HEIGHT), color=(0, 0, 0))
            .set_opacity(darken)
            .set_duration(duration)
        )
        bg = CompositeVideoClip([bg, overlay], size=(VIDEO_WIDTH, VIDEO_HEIGHT))

    return bg


def render_video(
    *,
    job_id: int,
    audio_path: Path,
    timestamps_path: Path,
    niche: str,
    background_video: Optional[str] = None,
    channel_id: Optional[int] = None,
) -> Path:
    """
    Compose final 9:16 MP4 with layered template:
    - Background (Pexels / local / gradient)
    - Blur + darken
    - White outlined subtitles (no background box)
    - Channel watermark
    """
    try:
        from moviepy.editor import (
            AudioFileClip,
            CompositeVideoClip,
            ImageClip,
            VideoFileClip,
            concatenate_videoclips,
        )
    except ImportError as exc:
        raise VideoEditorError("MoviePy is not installed. Run: pip install moviepy") from exc

    if not audio_path.exists():
        raise VideoEditorError(f"Audio file not found: {audio_path}")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUTS_DIR / f"job_{job_id}_final.mp4"
    style = _load_template_style(niche)

    try:
        audio = AudioFileClip(str(audio_path))
        duration = audio.duration
        words = _load_timestamps(timestamps_path)

        bg_path = None
        if background_video:
            candidate = Path(background_video)
            if not candidate.is_absolute():
                candidate = BACKGROUNDS_DIR / background_video
            if candidate.exists():
                bg_path = candidate

        if bg_path:
            bg = VideoFileClip(str(bg_path))
            if bg.duration < duration:
                loops = int(duration / bg.duration) + 1
                bg = concatenate_videoclips([bg] * loops)
            bg = bg.subclip(0, duration)
            bg = _fit_background_clip(bg)
            bg = bg.without_audio()
            bg = _apply_background_effects(bg, style, duration)
        else:
            bg = _create_gradient_background(duration, niche)

        layers = [bg]

        subtitle_center_y = VIDEO_HEIGHT * float(style.get("subtitle_y_ratio", 0.62))
        text_top = int(subtitle_center_y - SUBTITLE_CANVAS_HEIGHT / 2)

        for i, word_data in enumerate(words):
            word = str(word_data.get("word", "")).strip()
            if not word:
                continue
            start = float(word_data.get("start", 0))
            end = float(word_data.get("end", start + 0.3))
            clip_duration = max(end - start, 0.15)
            emphasized = i % 3 == 0

            arr = _make_subtitle_image(word.upper(), style, emphasized=emphasized)
            txt_clip = (
                ImageClip(arr, ismask=False, transparent=True)
                .set_duration(clip_duration)
                .set_start(start)
                .set_position(("center", text_top))
            )
            layers.append(txt_clip)

        watermark_path = _find_watermark(niche, channel_id)
        if watermark_path:
            logo_clip = (
                ImageClip(str(watermark_path), transparent=True)
                .resize(width=int(VIDEO_WIDTH * 0.14))
                .set_duration(duration)
                .set_position((VIDEO_WIDTH - int(VIDEO_WIDTH * 0.16), int(VIDEO_HEIGHT * 0.03)))
                .set_opacity(0.85)
            )
            layers.append(logo_clip)

        final = CompositeVideoClip(layers, size=(VIDEO_WIDTH, VIDEO_HEIGHT))
        final = final.set_audio(audio)
        final = final.set_duration(duration)

        final.write_videofile(
            str(output_path),
            fps=VIDEO_FPS,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            threads=4,
            logger=None,
        )

        audio.close()
        if bg_path:
            bg.close()
        final.close()

        return output_path
    except VideoEditorError:
        raise
    except Exception as exc:
        raise VideoEditorError(f"Video render failed: {exc}") from exc
