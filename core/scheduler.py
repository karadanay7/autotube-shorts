"""
Multi-channel publish scheduler — default: fixed daily slot (e.g. 20:00).
Optional: US peak-hours mode (SCHEDULE_US_PEAK_HOURS=true).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from config.settings import (
    SCHEDULE_DAILY_HOUR,
    SCHEDULE_DAILY_MINUTE,
    SCHEDULE_DISPLAY_TIMEZONE,
    SCHEDULE_INTERVAL_HOURS,
    SCHEDULE_MIN_LEAD_MINUTES,
    SCHEDULE_TIMEZONE,
    SCHEDULE_US_PEAK_HOURS,
)
from core.channels import channel_display_name
from core.database import (
    VideoJob,
    VideoJobStatus,
    get_channel,
    list_channels,
    list_video_jobs,
    update_job_fields,
)

# US Eastern peak viewing windows (hour, minute) — typical for Shorts
_WEEKDAY_PEAKS = [(14, 0), (18, 30), (20, 30)]  # Tue–Fri afternoon/evening
_MONDAY_PEAKS = [(18, 30), (20, 30)]
_SATURDAY_PEAKS = [(10, 0), (14, 0), (19, 0)]
_SUNDAY_PEAKS = [(10, 0), (19, 30)]


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _schedule_tz() -> ZoneInfo:
    """Timezone used to compute US peak-hour slots."""
    try:
        return ZoneInfo(SCHEDULE_TIMEZONE)
    except Exception:
        return ZoneInfo("America/New_York")


def _display_tz() -> ZoneInfo:
    """Timezone shown in the admin panel."""
    try:
        return ZoneInfo(SCHEDULE_DISPLAY_TIMEZONE)
    except Exception:
        return ZoneInfo("UTC")


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_display(dt: datetime) -> str:
    return dt.astimezone(_display_tz()).strftime("%Y-%m-%d %H:%M %Z")


def _calendar_day(dt: datetime, tz: ZoneInfo) -> date:
    return dt.astimezone(tz).date()


def _day_has_schedule(
    channel_id: int,
    day: date,
    *,
    tz: ZoneInfo,
    exclude_job_id: int | None = None,
) -> bool:
    """Whether this calendar day already has a scheduled publish for the channel."""
    for job in list_video_jobs():
        if job.channel_id != channel_id:
            continue
        if exclude_job_id and job.id == exclude_job_id:
            continue
        if not job.scheduled_time:
            continue
        if job.status not in (
            VideoJobStatus.READY_TO_UPLOAD,
            VideoJobStatus.COMPLETED,
        ):
            continue
        try:
            sched = _parse_dt(job.scheduled_time)
        except ValueError:
            continue
        if _calendar_day(sched, tz) == day:
            return True
    return False


def _occupied_days(
    channel_id: int,
    *,
    tz: ZoneInfo,
    from_day: date | None = None,
) -> set[date]:
    """
    Calendar days that already have a schedule — from today onward.
    Merges YouTube API (if connected) with ready/pending jobs in the DB.
    Skips old COMPLETED rows so stale dates do not block slots.
    """
    occupied: set[date] = set()
    start = from_day or _calendar_day(_now_utc(), tz)

    channel = get_channel(channel_id)
    if channel:
        try:
            from core.youtube_uploader import fetch_channel_videos, is_connected

            if is_connected(channel):
                for info in fetch_channel_videos(channel):
                    if not info.scheduled_publish_at:
                        continue
                    try:
                        sched = _parse_dt(info.scheduled_publish_at)
                    except ValueError:
                        continue
                    day = _calendar_day(sched, tz)
                    if day >= start:
                        occupied.add(day)
        except Exception:
            pass

    for job in list_video_jobs():
        if job.channel_id != channel_id or not job.scheduled_time:
            continue
        # Only ready videos block a day — PENDING queue jobs should not
        if job.status not in (
            VideoJobStatus.READY_TO_UPLOAD,
            VideoJobStatus.COMPLETED,
        ):
            continue
        try:
            sched = _parse_dt(job.scheduled_time)
        except ValueError:
            continue
        day = _calendar_day(sched, tz)
        if day >= start:
            occupied.add(day)

    return occupied


def _last_known_publish(channel_id: int) -> datetime | None:
    """
    Latest known publish time for the channel — YouTube API + DB.
    Auto-scheduling starts on the day after this timestamp.
    """
    latest: datetime | None = None

    channel = get_channel(channel_id)
    if channel:
        try:
            from core.youtube_uploader import fetch_channel_videos, is_connected

            if is_connected(channel):
                for info in fetch_channel_videos(channel):
                    for raw in (info.scheduled_publish_at, info.published_at):
                        if not raw:
                            continue
                        try:
                            dt = _parse_dt(raw)
                        except ValueError:
                            continue
                        if latest is None or dt > latest:
                            latest = dt
        except Exception:
            pass

    for job in list_video_jobs():
        if job.channel_id != channel_id or not job.scheduled_time:
            continue
        if job.status not in (
            VideoJobStatus.READY_TO_UPLOAD,
            VideoJobStatus.COMPLETED,
        ):
            continue
        try:
            dt = _parse_dt(job.scheduled_time)
        except ValueError:
            continue
        if latest is None or dt > latest:
            latest = dt

    return latest


def _next_daily_slot(
    channel_id: int,
    *,
    after: datetime | None = None,
    occupied: set[date] | None = None,
) -> datetime:
    """
    Next publish at SCHEDULE_DAILY_HOUR:MINUTE in the display timezone.
    Skips occupied days; never shifts the hour.
    """
    tz = _display_tz()
    now_local = _now_utc().astimezone(tz)
    occupied = occupied if occupied is not None else _occupied_days(channel_id, tz=tz)

    if after:
        cursor_day = _calendar_day(after, tz) + timedelta(days=1)
    else:
        last = _last_known_publish(channel_id)
        if last:
            cursor_day = _calendar_day(last, tz) + timedelta(days=1)
        else:
            cursor_day = now_local.date()

    while cursor_day in occupied:
        cursor_day += timedelta(days=1)

    slot_local = datetime.combine(
        cursor_day,
        time(SCHEDULE_DAILY_HOUR, SCHEDULE_DAILY_MINUTE),
        tzinfo=tz,
    )
    slot_utc = slot_local.astimezone(timezone.utc)

    min_utc = _now_utc() + timedelta(minutes=SCHEDULE_MIN_LEAD_MINUTES)
    if slot_utc < min_utc:
        cursor_day = _calendar_day(min_utc, tz) + timedelta(days=1)
        while cursor_day in occupied:
            cursor_day += timedelta(days=1)
        slot_local = datetime.combine(
            cursor_day,
            time(SCHEDULE_DAILY_HOUR, SCHEDULE_DAILY_MINUTE),
            tzinfo=tz,
        )
        slot_utc = slot_local.astimezone(timezone.utc)

    return slot_utc


def _peaks_for_weekday(weekday: int) -> list[tuple[int, int]]:
    if weekday == 0:
        return _MONDAY_PEAKS
    if weekday == 5:
        return _SATURDAY_PEAKS
    if weekday == 6:
        return _SUNDAY_PEAKS
    return _WEEKDAY_PEAKS


def _next_us_peak_slot(after: datetime | None = None) -> datetime:
    """Next publish slot during US (default Eastern) peak hours."""
    tz = _schedule_tz()
    base = (after or _now_utc()).astimezone(tz)
    min_local = base + timedelta(minutes=SCHEDULE_MIN_LEAD_MINUTES)

    for day_offset in range(14):
        day = (min_local.date() + timedelta(days=day_offset))
        peaks = _peaks_for_weekday(day.weekday())
        for hour, minute in peaks:
            candidate = datetime.combine(day, time(hour, minute), tzinfo=tz)
            if candidate >= min_local:
                return candidate.astimezone(timezone.utc)

    fallback = min_local + timedelta(hours=SCHEDULE_INTERVAL_HOURS)
    return fallback.astimezone(timezone.utc)


def _next_interval_slot(after: datetime | None = None) -> datetime:
    """Legacy logic — fixed interval + default 18:00 UTC anchor."""
    base = after or _now_utc()
    candidate = base + timedelta(hours=SCHEDULE_INTERVAL_HOURS)
    min_utc = _now_utc() + timedelta(minutes=SCHEDULE_MIN_LEAD_MINUTES)
    if candidate < min_utc:
        candidate = min_utc
    return candidate


def compute_next_publish_time(
    channel_id: int,
    *,
    after: datetime | None = None,
) -> datetime:
    """Compute the next suitable publish time for a channel."""
    if SCHEDULE_US_PEAK_HOURS:
        return _next_us_peak_slot(after)
    if SCHEDULE_DAILY_HOUR is not None:
        return _next_daily_slot(channel_id, after=after)
    return _next_interval_slot(after)


def _sort_jobs_by_schedule(jobs: list[VideoJob]) -> list[VideoJob]:
    """Sort by publish date — nearest first."""

    def _key(job: VideoJob) -> tuple[int, str]:
        if not job.scheduled_time:
            return (1, "")
        try:
            return (0, job.scheduled_time)
        except ValueError:
            return (1, "")

    return sorted(jobs, key=_key)


def parse_schedule_form_value(
    value: str,
    *,
    tz_name: str | None = None,
) -> str:
    """
    Parse a datetime-local form value (no timezone) into UTC ISO string.
    Browser sends local time; uses panel timezone when tz_name is omitted.
    """
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Empty schedule time")

    try:
        local_dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid schedule time: {raw}") from exc

    tz = ZoneInfo(tz_name or SCHEDULE_DISPLAY_TIMEZONE)
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=tz)
    return local_dt.astimezone(timezone.utc).isoformat()


def assign_schedule_to_job(
    job_id: int,
    scheduled_time: datetime | str | None = None,
) -> str:
    """Assign a publish time to a single ready video (manual or auto slot)."""
    job = next((j for j in list_video_jobs() if j.id == job_id), None)
    if not job:
        raise ValueError(f"Job {job_id} not found")
    if job.status != VideoJobStatus.READY_TO_UPLOAD:
        raise ValueError("Only ready videos can be scheduled")

    if scheduled_time is None:
        slot = compute_next_publish_time(job.channel_id)
    elif isinstance(scheduled_time, datetime):
        slot = scheduled_time
        if slot.tzinfo is None:
            slot = slot.replace(tzinfo=timezone.utc)
        else:
            slot = slot.astimezone(timezone.utc)
    else:
        slot = _parse_dt(scheduled_time)

    iso = slot.isoformat()
    update_job_fields(job_id, scheduled_time=iso)
    return iso


def auto_schedule_ready_jobs(
    channel_id: int | None = None,
) -> int:
    """
    Auto-schedule READY_TO_UPLOAD videos.
    Sequential daily slots after the last known YouTube publish time.
    PENDING queue jobs are not scheduled (re-run after render completes).
    Returns: number of jobs scheduled or rescheduled.
    """
    jobs = [
        j
        for j in list_video_jobs()
        if j.status == VideoJobStatus.READY_TO_UPLOAD
        and (channel_id is None or j.channel_id == channel_id)
    ]
    if not jobs:
        return 0

    by_channel: dict[int, list[VideoJob]] = {}
    for job in jobs:
        by_channel.setdefault(job.channel_id, []).append(job)

    scheduled = 0
    for cid, channel_jobs in by_channel.items():
        channel_jobs.sort(key=lambda j: j.id)
        after: datetime | None = None
        for job in channel_jobs:
            if job.scheduled_time and not after:
                try:
                    after = _parse_dt(job.scheduled_time)
                    continue
                except ValueError:
                    pass
            slot = compute_next_publish_time(cid, after=after)
            update_job_fields(job.id, scheduled_time=slot.isoformat())
            after = slot
            scheduled += 1
    return scheduled


def clear_schedule_for_non_ready() -> int:
    """Clear scheduled_time on jobs that are not ready (PENDING, FAILED, in production)."""
    cleared = 0
    for job in list_video_jobs():
        if job.status == VideoJobStatus.READY_TO_UPLOAD:
            continue
        if job.status == VideoJobStatus.COMPLETED:
            continue
        if not job.scheduled_time:
            continue
        update_job_fields(job.id, scheduled_time=None)
        cleared += 1
    return cleared


def sync_all_channels_from_youtube() -> int:
    """Sync YouTube schedule into the DB for all connected channels."""
    total = 0
    for channel in list_channels():
        total += sync_channel_from_youtube(channel.id)
    return total


def sync_channel_from_youtube(channel_id: int) -> int:
    """Sync one channel's YouTube schedule into the DB."""
    from core.youtube_uploader import sync_channel_schedule_from_youtube

    channel = get_channel(channel_id)
    if not channel:
        return 0
    try:
        return sync_channel_schedule_from_youtube(channel)
    except Exception:
        return 0


def list_scheduled_jobs() -> list[dict]:
    """All scheduled publishes with channel metadata."""
    rows: list[dict] = []
    channels = {c.id: c for c in list_channels()}
    for job in list_video_jobs():
        if not job.scheduled_time:
            continue
        if job.status not in (
            VideoJobStatus.READY_TO_UPLOAD,
            VideoJobStatus.COMPLETED,
        ):
            continue
        channel = channels.get(job.channel_id)
        try:
            sched = _parse_dt(job.scheduled_time)
            display = _format_display(sched)
        except ValueError:
            display = job.scheduled_time
        rows.append(
            {
                "job": job,
                "channel": channel,
                "channel_name": channel_display_name(channel),
                "display_time": display,
            }
        )
    rows.sort(key=lambda r: r["job"].scheduled_time or "")
    return rows


def peak_hours_summary() -> str:
    """Short UI summary of peak-hour scheduling."""
    if not SCHEDULE_US_PEAK_HOURS:
        tz = _display_tz()
        return (
            f"Daily {SCHEDULE_DAILY_HOUR:02d}:{SCHEDULE_DAILY_MINUTE:02d} "
            f"{tz.key}"
        )
    tz = _schedule_tz()
    peaks = ", ".join(f"{h:02d}:{m:02d}" for h, m in _WEEKDAY_PEAKS[:2])
    return f"US peaks ({tz.key}): {peaks}…"


def schedule_sort_key(scheduled_time: Optional[str]) -> float:
    """Sort key by publish time — nearest first."""
    if not scheduled_time:
        return float("inf")
    try:
        return _parse_dt(scheduled_time).timestamp()
    except ValueError:
        return float("inf")


def format_schedule_display(scheduled_time: Optional[str]) -> dict[str, str]:
    """Schedule labels for the admin panel."""
    empty = {"us": "", "utc": "", "short": "", "tz_label": ""}
    if not scheduled_time:
        return empty
    try:
        dt_utc = _parse_dt(scheduled_time)
        local = dt_utc.astimezone(_display_tz())
        us = dt_utc.astimezone(_schedule_tz()).strftime("%d %b %H:%M")
        utc = dt_utc.strftime("%d %b %H:%M UTC")
        short = local.strftime("%d %b %H:%M")
        tz_label = local.strftime("%Z")
        return {"us": us, "utc": utc, "short": short, "tz_label": tz_label}
    except ValueError:
        return {
            "us": scheduled_time,
            "utc": "",
            "short": scheduled_time,
            "tz_label": "",
        }


def parse_manual_schedule_time(
    value: str,
    tz_name: Optional[str] = None,
) -> datetime:
    """Parse datetime-local form value into UTC datetime."""
    iso = parse_schedule_form_value(value, tz_name=tz_name)
    return _parse_dt(iso)


auto_schedule_pending_jobs = auto_schedule_ready_jobs
