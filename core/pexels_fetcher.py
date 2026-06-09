"""
Pexels API — görsel etiketlere göre dikey stok video arama ve indirme.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Optional

import requests

from config.settings import (
    BACKGROUNDS_DIR,
    PEXELS_API_KEY,
    PEXELS_VIDEOS_PER_TAG,
)
from core.video_editor import list_backgrounds, pick_background

PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"


class PexelsFetcherError(Exception):
    pass


def _headers() -> dict[str, str]:
    if not PEXELS_API_KEY:
        raise PexelsFetcherError("PEXELS_API_KEY is not configured")
    return {"Authorization": PEXELS_API_KEY}


def search_portrait_videos(keyword: str, per_page: int = 3) -> list[dict]:
    """Search Pexels for portrait-oriented stock videos."""
    try:
        response = requests.get(
            PEXELS_SEARCH_URL,
            headers=_headers(),
            params={
                "query": keyword,
                "orientation": "portrait",
                "per_page": per_page,
                "size": "medium",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("videos", [])
    except requests.RequestException as exc:
        raise PexelsFetcherError(f"Pexels search failed for '{keyword}': {exc}") from exc


def _pick_best_video_file(video: dict) -> Optional[str]:
    """Select highest-quality portrait MP4 link from a Pexels video object."""
    files = video.get("video_files", [])
    portrait = [
        f for f in files
        if f.get("file_type") == "video/mp4"
        and f.get("height", 0) >= f.get("width", 0)
    ]
    candidates = portrait or [
        f for f in files if f.get("file_type") == "video/mp4"
    ]
    if not candidates:
        return None

    candidates.sort(key=lambda f: f.get("height", 0), reverse=True)
    return candidates[0].get("link")


def download_video(url: str, dest: Path) -> Path:
    """Download a remote video to local path."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        fh.write(chunk)
        return dest
    except requests.RequestException as exc:
        raise PexelsFetcherError(f"Video download failed: {exc}") from exc


def fetch_video_for_tag(
    keyword: str,
    niche: str,
    job_id: int,
    *,
    per_page: int = PEXELS_VIDEOS_PER_TAG,
) -> Optional[Path]:
    """Search and download one portrait video for a keyword."""
    try:
        videos = search_portrait_videos(keyword, per_page=per_page)
        if not videos:
            return None

        random.shuffle(videos)
        niche_dir = BACKGROUNDS_DIR / niche
        niche_dir.mkdir(parents=True, exist_ok=True)

        safe_kw = "".join(c if c.isalnum() else "_" for c in keyword.lower())[:30]
        for video in videos:
            link = _pick_best_video_file(video)
            if not link:
                continue
            dest = niche_dir / f"pexels_job{job_id}_{safe_kw}_{video.get('id', 'vid')}.mp4"
            if dest.exists() and dest.stat().st_size > 0:
                return dest
            try:
                return download_video(link, dest)
            except PexelsFetcherError:
                continue
        return None
    except PexelsFetcherError:
        return None


def fetch_backgrounds_for_tags(
    tags: list[str],
    niche: str,
    job_id: int,
) -> Optional[Path]:
    """
    Try each visual tag against Pexels; return first successfully downloaded video.
    """
    if not PEXELS_API_KEY:
        return None

    for tag in tags:
        tag = tag.strip()
        if not tag:
            continue
        path = fetch_video_for_tag(tag, niche, job_id)
        if path:
            return path
    return None


def resolve_background(
    *,
    niche: str,
    job_id: int,
    visual_tags: Optional[list[str]] = None,
    preferred: Optional[str] = None,
) -> tuple[Optional[Path], str]:
    """
    Resolve background video with priority:
    1. User-preferred path
    2. Pexels auto-fetch via visual tags
    3. Local niche pool (fallback)
    4. None → gradient fallback in editor

    Returns (path_or_none, source_label).
    """
    if preferred:
        candidate = Path(preferred)
        if not candidate.is_absolute():
            candidate = BACKGROUNDS_DIR / preferred
        if candidate.exists():
            return candidate, "manual"

    if visual_tags and PEXELS_API_KEY:
        pexels_path = fetch_backgrounds_for_tags(visual_tags, niche, job_id)
        if pexels_path:
            return pexels_path, "pexels"

    local = pick_background(niche)
    if local:
        return local, "local_pool"

    return None, "gradient"
