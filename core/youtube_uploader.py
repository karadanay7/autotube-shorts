"""
YouTube OAuth2 uploader with scheduled publishing support.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Optional
from zoneinfo import ZoneInfo

from config.settings import (
    CREDS_DIR,
    GOOGLE_CLIENT_SECRETS,
    MAX_SHORTS_DESCRIPTION_CHARS,
    OAUTH_REDIRECT_URI,
    OAUTH_STATE_FILE,
    SCHEDULE_DAILY_HOUR,
    SCHEDULE_DAILY_MINUTE,
    SCHEDULE_DISPLAY_TIMEZONE,
    YOUTUBE_DECLARE_SYNTHETIC_MEDIA,
    YOUTUBE_SCOPES,
)
from core.database import Channel, update_channel

TOKEN_FILENAME = "token.json"


def oauth_redirect_status() -> dict[str, Any]:
    """OAuth redirect URI status for the admin panel."""
    from config.settings import GOOGLE_CLIENT_SECRETS, OAUTH_REDIRECT_URI

    registered: list[str] = []
    if GOOGLE_CLIENT_SECRETS.exists():
        try:
            data = json.loads(GOOGLE_CLIENT_SECRETS.read_text(encoding="utf-8"))
            registered = list(data.get("web", {}).get("redirect_uris", []) or [])
        except (json.JSONDecodeError, OSError):
            pass

    aligned = OAUTH_REDIRECT_URI in registered
    return {
        "redirect_uri": OAUTH_REDIRECT_URI,
        "registered_in_secrets": registered,
        "aligned": aligned,
    }


class YouTubeUploaderError(Exception):
    pass


def _token_path(channel: Channel) -> Path:
    rel = Path(channel.youtube_credentials_path)
    if rel.is_absolute():
        return rel
    return Path(__file__).resolve().parent.parent / rel


def _client_secrets_path() -> Path:
    if not GOOGLE_CLIENT_SECRETS.exists():
        raise YouTubeUploaderError(
            f"Google client secrets not found at {GOOGLE_CLIENT_SECRETS}. "
            "Download from Google Cloud Console and place the file there."
        )
    return GOOGLE_CLIENT_SECRETS


def _load_oauth_pending() -> dict[str, dict[str, str]]:
    if not OAUTH_STATE_FILE.exists():
        return {}
    try:
        data = json.loads(OAUTH_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_oauth_pending(channel_id: int, code_verifier: str) -> None:
    pending = _load_oauth_pending()
    pending[str(channel_id)] = {"code_verifier": code_verifier}
    OAUTH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    OAUTH_STATE_FILE.write_text(json.dumps(pending, indent=2), encoding="utf-8")


def _pop_oauth_pending(channel_id: int) -> Optional[str]:
    pending = _load_oauth_pending()
    entry = pending.pop(str(channel_id), None)
    OAUTH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if pending:
        OAUTH_STATE_FILE.write_text(json.dumps(pending, indent=2), encoding="utf-8")
    elif OAUTH_STATE_FILE.exists():
        OAUTH_STATE_FILE.unlink()
    if not entry:
        return None
    return entry.get("code_verifier")


def get_oauth_flow(*, code_verifier: Optional[str] = None):
    """Build Google OAuth flow for YouTube authorization."""
    try:
        from google_auth_oauthlib.flow import Flow

        return Flow.from_client_secrets_file(
            str(_client_secrets_path()),
            scopes=YOUTUBE_SCOPES,
            redirect_uri=OAUTH_REDIRECT_URI,
            code_verifier=code_verifier,
            autogenerate_code_verifier=code_verifier is None,
        )
    except YouTubeUploaderError:
        raise
    except Exception as exc:
        raise YouTubeUploaderError(f"OAuth flow init failed: {exc}") from exc


def get_authorization_url(
    channel_id: int,
    *,
    login_hint: Optional[str] = None,
) -> tuple[str, str]:
    """Return (auth_url, state) for browser-based OAuth."""
    try:
        flow = get_oauth_flow()
        auth_kwargs: dict[str, str] = {
            "access_type": "offline",
            "include_granted_scopes": "true",
            # Always show Google account picker when redirect_uri is valid
            "prompt": "select_account consent",
            "state": str(channel_id),
        }
        if login_hint:
            auth_kwargs["login_hint"] = login_hint.strip().lower()
        auth_url, state = flow.authorization_url(**auth_kwargs)
        if not flow.code_verifier:
            raise YouTubeUploaderError("OAuth PKCE code_verifier missing after auth URL")
        _save_oauth_pending(channel_id, flow.code_verifier)
        return auth_url, state
    except YouTubeUploaderError:
        raise
    except Exception as exc:
        raise YouTubeUploaderError(f"Failed to build auth URL: {exc}") from exc


def _normalize_oauth_callback_url(url: str) -> str:
    """Strip iss= query param Google sometimes adds before token exchange."""
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != "iss"]
    return urlunparse(parsed._replace(query=urlencode(query)))


def save_oauth_credentials(channel_id: int, authorization_response_url: str) -> Path:
    """Exchange OAuth code for tokens and persist per channel."""
    try:
        code_verifier = _pop_oauth_pending(channel_id)
        if not code_verifier:
            raise YouTubeUploaderError(
                "OAuth session expired. Click Connect YouTube again."
            )
        flow = get_oauth_flow(code_verifier=code_verifier)
        callback_url = _normalize_oauth_callback_url(authorization_response_url)
        flow.fetch_token(authorization_response=callback_url)
        creds = flow.credentials

        CREDS_DIR.mkdir(parents=True, exist_ok=True)
        token_file = CREDS_DIR / f"channel_{channel_id}_{TOKEN_FILENAME}"
        token_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes or []),
        }
        token_file.write_text(json.dumps(token_data, indent=2), encoding="utf-8")

        rel_path = f"config/creds/channel_{channel_id}_{TOKEN_FILENAME}"
        update_channel(
            channel_id,
            youtube_credentials_path=rel_path,
            youtube_connected=True,
        )
        return token_file
    except YouTubeUploaderError:
        raise
    except Exception as exc:
        raise YouTubeUploaderError(f"OAuth token exchange failed: {exc}") from exc


def _load_credentials(channel: Channel):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        raise YouTubeUploaderError(
            "Google auth libraries missing. Run: pip install google-auth-oauthlib"
        ) from exc

    token_file = _token_path(channel)
    if not token_file.exists():
        raise YouTubeUploaderError(
            f"YouTube not connected for channel '{channel.channel_name}'. "
            "Connect via admin panel first."
        )

    try:
        data = json.loads(token_file.read_text(encoding="utf-8"))
        creds = Credentials(
            token=data.get("token"),
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            scopes=data.get("scopes") or YOUTUBE_SCOPES,
        )

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            data["token"] = creds.token
            token_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        return creds
    except YouTubeUploaderError:
        raise
    except Exception as exc:
        raise YouTubeUploaderError(f"Failed to load credentials: {exc}") from exc


def _build_youtube_service(channel: Channel):
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise YouTubeUploaderError(
            "google-api-python-client missing. Run: pip install google-api-python-client"
        ) from exc

    creds = _load_credentials(channel)
    return build("youtube", "v3", credentials=creds)


@dataclass
class YouTubeChannelProfile:
    title: str
    thumbnail_url: str
    youtube_channel_id: str


def fetch_channel_info(channel: Channel) -> YouTubeChannelProfile:
    """Fetch YouTube channel name, avatar and persist to database."""
    try:
        youtube = _build_youtube_service(channel)
        response = youtube.channels().list(part="snippet", mine=True).execute()
        items = response.get("items", [])
        if not items:
            raise YouTubeUploaderError("No YouTube channel found for this account")

        snippet = items[0]["snippet"]
        thumbnails = snippet.get("thumbnails", {})
        thumb = (
            thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url")
            or ""
        )
        title = snippet.get("title", "Unknown")
        yt_id = items[0].get("id", "")

        update_channel(
            channel.id,
            youtube_channel_name=title,
            youtube_channel_thumbnail=thumb,
            youtube_connected=True,
        )
        return YouTubeChannelProfile(
            title=title,
            thumbnail_url=thumb,
            youtube_channel_id=yt_id,
        )
    except YouTubeUploaderError:
        raise
    except Exception as exc:
        raise YouTubeUploaderError(f"Failed to fetch channel info: {exc}") from exc


def is_connected(channel: Channel) -> bool:
    return _token_path(channel).exists()


def disconnect_youtube(channel: Channel) -> None:
    """Delete the channel OAuth token file so the user can reconnect."""
    token_file = _token_path(channel)
    if token_file.exists():
        token_file.unlink()
    update_channel(
        channel.id,
        youtube_connected=False,
        youtube_channel_name="",
        youtube_channel_thumbnail="",
    )


@dataclass
class YouTubeVideoInfo:
    video_id: str
    title: str
    publish_at: datetime
    privacy_status: str


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _same_instant(a: Optional[str], b: Optional[str]) -> bool:
    """Compare ISO timestamps as the same UTC instant."""
    if not a or not b:
        return False
    try:
        da = datetime.fromisoformat(a.replace("Z", "+00:00"))
        db = datetime.fromisoformat(b.replace("Z", "+00:00"))
        if da.tzinfo is None:
            da = da.replace(tzinfo=timezone.utc)
        if db.tzinfo is None:
            db = db.replace(tzinfo=timezone.utc)
        return int(da.timestamp()) == int(db.timestamp())
    except ValueError:
        return a == b


def _norm_title(title: str) -> str:
    return " ".join((title or "").lower().split())


def _display_tz() -> ZoneInfo:
    try:
        return ZoneInfo(SCHEDULE_DISPLAY_TIMEZONE)
    except Exception:
        return ZoneInfo("Europe/Istanbul")


def _parse_api_dt(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_canonical_publish_slot(dt: datetime) -> bool:
    """True when publish time matches the configured daily slot (API may return stale times)."""
    tr = dt.astimezone(_display_tz())
    return tr.hour == SCHEDULE_DAILY_HOUR and tr.minute == SCHEDULE_DAILY_MINUTE


def _item_to_video_info(item: dict[str, Any]) -> Optional[YouTubeVideoInfo]:
    status = item.get("status", {})
    snippet = item.get("snippet", {})
    raw = status.get("publishAt") or snippet.get("publishedAt")
    if not raw:
        return None
    return YouTubeVideoInfo(
        video_id=item["id"],
        title=(snippet.get("title") or "").strip() or item["id"],
        publish_at=_parse_api_dt(raw),
        privacy_status=status.get("privacyStatus") or "",
    )


def _resolve_publish_at(
    youtube: Any,
    video_id: str,
    *,
    attempts: int = 3,
) -> Optional[YouTubeVideoInfo]:
    """
    YouTube API may return conflicting publishAt values for the same video.
    Prefer the reading that matches the configured daily schedule slot.
    """
    readings: list[YouTubeVideoInfo] = []
    for attempt in range(attempts):
        if attempt:
            time.sleep(0.25)
        resp = youtube.videos().list(part="status,snippet", id=video_id).execute()
        items = resp.get("items", [])
        if not items:
            return None
        info = _item_to_video_info(items[0])
        if info:
            readings.append(info)

    if not readings:
        return None

    canonical = [r for r in readings if _is_canonical_publish_slot(r.publish_at)]
    if canonical:
        return min(canonical, key=lambda r: r.publish_at)
    return readings[0]


def fetch_channel_videos(
    channel: Channel,
    *,
    max_videos: int = 100,
) -> list[YouTubeVideoInfo]:
    """List channel videos from YouTube API (scheduled + published times)."""
    try:
        youtube = _build_youtube_service(channel)
        ch_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
        items = ch_resp.get("items", [])
        if not items:
            return []

        uploads_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        video_ids: list[str] = []
        page_token: Optional[str] = None

        while len(video_ids) < max_videos:
            pl = youtube.playlistItems().list(
                part="contentDetails",
                playlistId=uploads_id,
                maxResults=min(50, max_videos - len(video_ids)),
                pageToken=page_token,
            ).execute()
            for row in pl.get("items", []):
                vid = row.get("contentDetails", {}).get("videoId")
                if vid:
                    video_ids.append(vid)
            page_token = pl.get("nextPageToken")
            if not page_token:
                break

        if not video_ids:
            return []

        results: list[YouTubeVideoInfo] = []
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i : i + 50]
            v_resp = youtube.videos().list(
                part="status,snippet",
                id=",".join(batch),
            ).execute()
            for item in v_resp.get("items", []):
                info = _item_to_video_info(item)
                if not info:
                    continue
                if (
                    info.privacy_status == "private"
                    and item.get("status", {}).get("publishAt")
                    and not _is_canonical_publish_slot(info.publish_at)
                ):
                    resolved = _resolve_publish_at(youtube, info.video_id)
                    if resolved:
                        info = resolved
                results.append(info)

        results.sort(key=lambda v: v.publish_at)
        return results
    except YouTubeUploaderError:
        raise
    except Exception as exc:
        raise YouTubeUploaderError(f"Failed to read YouTube schedule: {exc}") from exc


def sync_channel_schedule_from_youtube(channel: Channel) -> int:
    """
    YouTube kaynak doğrudur:
    - Silinmiş videoların DB bağlantısını kaldır
    - publishAt zamanlarını güncelle
    - Başlık eşleşmesiyle yeniden bağla (duplicate silme sonrası)
    """
    from core.database import VideoJobStatus, list_video_jobs, update_job_fields

    videos = fetch_channel_videos(channel)
    by_id = {v.video_id: v for v in videos}
    yt_ids = set(by_id.keys())
    updated = 0
    unlinked = 0
    relinked = 0

    for job in list_video_jobs():
        if job.channel_id != channel.id or not job.youtube_video_id:
            continue
        if job.youtube_video_id in yt_ids:
            continue
        update_job_fields(job.id, clear_youtube_video_id=True)
        unlinked += 1

    for job in list_video_jobs():
        if job.channel_id != channel.id or not job.youtube_video_id:
            continue
        info = by_id.get(job.youtube_video_id)
        if not info:
            continue
        iso = _utc_iso(info.publish_at)
        if not _same_instant(job.scheduled_time, iso):
            update_job_fields(job.id, scheduled_time=iso)
            updated += 1

    linked_ids = {
        j.youtube_video_id
        for j in list_video_jobs()
        if j.channel_id == channel.id and j.youtube_video_id
    }
    orphans = [
        j
        for j in list_video_jobs()
        if j.channel_id == channel.id
        and j.status == VideoJobStatus.COMPLETED
        and not j.youtube_video_id
    ]
    for info in videos:
        if info.video_id in linked_ids:
            continue
        norm = _norm_title(info.title)
        matches = [
            j for j in orphans if _norm_title(j.title or j.raw_topic) == norm
        ]
        if len(matches) != 1:
            continue
        job = matches[0]
        orphans.remove(job)
        linked_ids.add(info.video_id)
        update_job_fields(
            job.id,
            youtube_video_id=info.video_id,
            scheduled_time=_utc_iso(info.publish_at),
        )
        relinked += 1

    return updated + unlinked + relinked


def upload_and_schedule(
    channel: Channel,
    *,
    video_path: Path,
    title: str,
    description: str,
    scheduled_time: Optional[datetime | str] = None,
    privacy: str = "private",
    tags: Optional[list[str]] = None,
) -> str:
    """
    Upload video to YouTube. If scheduled_time is set, use publishAt for future publish.
    Returns YouTube video ID.
    """
    if not video_path.exists():
        raise YouTubeUploaderError(f"Video file not found: {video_path}")

    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise YouTubeUploaderError("google-api-python-client not installed") from exc

    try:
        youtube = _build_youtube_service(channel)

        status_body: dict[str, Any] = {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        }
        if YOUTUBE_DECLARE_SYNTHETIC_MEDIA:
            status_body["containsSyntheticMedia"] = True

        if scheduled_time:
            if isinstance(scheduled_time, str):
                dt = datetime.fromisoformat(scheduled_time.replace("Z", "+00:00"))
            else:
                dt = scheduled_time
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            publish_at = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            status_body["privacyStatus"] = "private"
            status_body["publishAt"] = publish_at

        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:MAX_SHORTS_DESCRIPTION_CHARS],
                "categoryId": "22",
                "tags": tags or [],
            },
            "status": status_body,
        }

        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            resumable=True,
            chunksize=1024 * 1024,
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                pass  # progress available via status.progress()

        video_id = response["id"]
        return video_id
    except YouTubeUploaderError:
        raise
    except Exception as exc:
        raise YouTubeUploaderError(f"YouTube upload failed: {exc}") from exc
