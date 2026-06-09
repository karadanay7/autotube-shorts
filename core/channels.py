"""Channel display helpers."""

from __future__ import annotations

from typing import Optional

from core.database import Channel


def channel_display_name(channel: Optional[Channel]) -> str:
    """Panel label — prefer connected YouTube channel name."""
    if not channel:
        return "—"
    yt = (channel.youtube_channel_name or "").strip()
    if yt:
        return yt
    local = (channel.channel_name or "").strip()
    if local:
        return local
    return f"Channel #{channel.id}"
