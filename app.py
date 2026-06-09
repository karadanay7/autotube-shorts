"""AutoTube admin dashboard — full management UI."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from config.niches import (
    channel_voice_id,
    channel_voice_override,
    get_niche,
    list_niche_profiles,
    list_niches,
    niche_default_voice_id,
    niche_tone_rules,
)
from config.voices import load_voices, voice_label
from config.settings import (
    BACKGROUNDS_DIR,
    HOST,
    MAX_SHORTS_DESCRIPTION_CHARS,
    OLLAMA_MODEL,
    OUTPUTS_DIR,
    PORT,
    SCHEDULE_DISPLAY_TIMEZONE,
    SCHEDULE_TIMEZONE,
    SCHEDULE_US_PEAK_HOURS,
    YOUTUBE_DECLARE_SYNTHETIC_MEDIA,
    TEMP_DIR,
    api_status,
    ensure_dirs,
)
from core.channels import channel_display_name
from core.i18n import (
    SUPPORTED_LOCALES,
    get_locale,
    js_messages,
    status_label,
    translate,
)
from core.database import (
    PROJECT_ROOT,
    VideoJobStatus,
    create_channel,
    create_video_job,
    delete_channel,
    delete_video_job,
    get_channel,
    get_video_job,
    init_db,
    list_channels,
    list_video_jobs,
    update_channel,
    update_job_fields,
)
from core.llm_engine import LLMEngineError, condense_shorts_description, generate_video_topics
from core.scheduler import (
    assign_schedule_to_job,
    auto_schedule_pending_jobs,
    format_schedule_display,
    parse_manual_schedule_time,
    schedule_sort_key,
    peak_hours_summary,
    sync_all_channels_from_youtube,
    sync_channel_from_youtube,
)
from core.video_editor import VIDEO_EXTENSIONS, list_backgrounds
from core.youtube_uploader import (
    YouTubeUploaderError,
    fetch_channel_info,
    disconnect_youtube,
    get_authorization_url,
    is_connected,
    oauth_redirect_status,
    save_oauth_credentials,
)
from main import (
    get_runnable_jobs,
    get_scheduled_ready_jobs,
    process_job,
    recover_stale_production_jobs,
    recover_stuck_production_jobs,
    run_pending,
    run_uploads,
)

_pipeline_lock = threading.Lock()
_upload_lock = threading.Lock()


def flash_t(key: str, category: str = "message", **kwargs: object) -> None:
    flash(translate(key, get_locale(), **kwargs), category)


app = Flask(__name__)
# Local panel only — signs lang session + flash cookies (not configured via .env)
app.config["SECRET_KEY"] = "autotube-local-panel"
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB upload


@app.context_processor
def _dashboard_template_defaults():
    """Safe template defaults + i18n."""
    locale = get_locale()
    return {
        "active_channel_id": 0,
        "active_channel": None,
        "active_channel_name": "",
        "active_channel_thumbnail": "",
        "channel_picker": [],
        "channel_default_voice": "",
        "channel_voice_label": "—",
        "niche_default_voice": "",
        "locale": locale,
        "t": lambda k, **kw: translate(k, locale, **kw),
        "i18n_js": js_messages(locale),
    }

_QUEUE_STATUSES = frozenset(
    {
        VideoJobStatus.PENDING,
        VideoJobStatus.GENERATING_TEXT,
        VideoJobStatus.GENERATING_AUDIO,
        VideoJobStatus.RENDERING,
        VideoJobStatus.FAILED,
    }
)

STATUS_COLORS: dict[VideoJobStatus, str] = {
    VideoJobStatus.PENDING: "bg-slate-500/20 text-slate-300",
    VideoJobStatus.GENERATING_TEXT: "bg-blue-500/20 text-blue-300",
    VideoJobStatus.GENERATING_AUDIO: "bg-indigo-500/20 text-indigo-300",
    VideoJobStatus.RENDERING: "bg-amber-500/20 text-amber-300",
    VideoJobStatus.READY_TO_UPLOAD: "bg-purple-500/20 text-purple-300",
    VideoJobStatus.COMPLETED: "bg-emerald-500/20 text-emerald-300",
    VideoJobStatus.FAILED: "bg-red-500/20 text-red-300",
}


def _resolve_channel_id(explicit: int | None = None) -> int | None:
    """Active panel channel from URL ?channel= or form return_channel."""
    if explicit and get_channel(explicit):
        return explicit
    cid = request.args.get("channel", type=int)
    if cid and get_channel(cid):
        return cid
    form_cid = request.form.get("return_channel", type=int) or request.form.get(
        "channel_id", type=int
    )
    if form_cid and get_channel(form_cid):
        return form_cid
    return None


def _go_dashboard(channel_id: int | None = None):
    cid = _resolve_channel_id(channel_id)
    if cid:
        return redirect(url_for("dashboard", channel=cid))
    channels = list_channels()
    if channels:
        return redirect(url_for("dashboard", channel=channels[0].id))
    return redirect(url_for("dashboard"))


def _channel_picker(active_id: int | None) -> list[dict]:
    """All channels for the header dropdown (connected or not)."""
    tabs = []
    for ch in list_channels():
        jobs = [j for j in list_video_jobs() if j.channel_id == ch.id]
        connected = is_connected(ch) or ch.youtube_connected
        tabs.append(
            {
                "id": ch.id,
                "name": channel_display_name(ch),
                "niche": ch.niche,
                "active": active_id is not None and ch.id == active_id,
                "youtube_connected": connected,
                "thumbnail": ch.youtube_channel_thumbnail or "",
                "queue_count": sum(1 for j in jobs if j.status in _QUEUE_STATUSES),
                "ready_count": sum(
                    1 for j in jobs if j.status == VideoJobStatus.READY_TO_UPLOAD
                ),
                "youtube_count": sum(
                    1 for j in jobs if j.status == VideoJobStatus.COMPLETED
                ),
                "badge": sum(
                    1
                    for j in jobs
                    if j.status in _QUEUE_STATUSES
                    or j.status == VideoJobStatus.READY_TO_UPLOAD
                ),
            }
        )
    return tabs


def _channels_enriched() -> list[dict]:
    rows = []
    for ch in list_channels():
        connected = is_connected(ch) or ch.youtube_connected
        if connected and (
            not ch.youtube_channel_name or not ch.youtube_channel_thumbnail
        ):
            try:
                fetch_channel_info(ch)
                ch = get_channel(ch.id) or ch
            except YouTubeUploaderError:
                pass
        rows.append(
            {
                "channel": ch,
                "display_name": channel_display_name(ch),
                "youtube_connected": connected,
                "background_count": len(list_backgrounds(ch.niche)),
                "upload_ready_count": len(
                    get_scheduled_ready_jobs(channel_id=ch.id)
                ),
            }
        )
    return rows


def _parse_job_seo(job) -> dict[str, str]:
    """Split stored Shorts description into hook text and hashtags."""
    import re

    title = (job.title or job.raw_topic or "").strip()
    raw = (job.description or "").strip()
    if not raw:
        return {"title": title, "body": "", "hashtags": ""}

    tags = re.findall(r"#\w+", raw)
    body = raw
    for tag in tags:
        body = body.replace(tag, "")
    body = " ".join(body.split()).strip()

    hashtags_plain = " ".join(t.lstrip("#") for t in tags)
    return {
        "title": title,
        "body": body,
        "hashtags": " ".join(tags),
        "hashtags_plain": hashtags_plain,
        "char_count": str(len(raw)),
        "preview": raw,
    }


def _job_row(job, channels: dict) -> dict:
    channel = channels.get(job.channel_id)
    video_rel = None
    if job.video_output_path:
        path = Path(job.video_output_path)
        try:
            video_rel = str(path.relative_to(OUTPUTS_DIR))
        except ValueError:
            video_rel = path.name
    seo = _parse_job_seo(job)
    schedule = format_schedule_display(job.scheduled_time)
    watch_url = (
        f"https://www.youtube.com/watch?v={job.youtube_video_id}"
        if job.youtube_video_id
        else None
    )
    return {
        "job": job,
        "channel_name": channel_display_name(channel),
        "youtube_name": channel.youtube_channel_name if channel else None,
        "status_label": status_label(job.status.value, get_locale()),
        "status_color": STATUS_COLORS.get(job.status, "bg-slate-500/20"),
        "voice_label": voice_label(
            channel_voice_id(channel) if channel else job.elevenlabs_voice_id
        ),
        "video_rel": video_rel,
        "seo": seo,
        "schedule": schedule,
        "watch_url": watch_url,
        "is_planned": bool(job.scheduled_time),
        "is_on_youtube": job.status == VideoJobStatus.COMPLETED and bool(watch_url),
        "ready_badge": (
            translate("badge.scheduled_upload", get_locale())
            if job.status == VideoJobStatus.READY_TO_UPLOAD and job.scheduled_time
            else translate("badge.awaiting_schedule", get_locale())
            if job.status == VideoJobStatus.READY_TO_UPLOAD
            else ""
        ),
    }


def _queue_jobs(channel_id: int | None = None) -> list[dict]:
    """Production queue — jobs not yet ready to upload."""
    channels = {ch.id: ch for ch in list_channels()}
    rows = []
    for job in list_video_jobs():
        if channel_id is not None and job.channel_id != channel_id:
            continue
        if job.status not in _QUEUE_STATUSES:
            continue
        rows.append(_job_row(job, channels))
    rows.sort(key=lambda r: r["job"].id, reverse=True)
    return rows


def _ready_jobs(channel_id: int | None = None) -> list[dict]:
    """Rendered videos not yet uploaded to YouTube."""
    channels = {ch.id: ch for ch in list_channels()}
    rows = []
    for job in list_video_jobs():
        if channel_id is not None and job.channel_id != channel_id:
            continue
        if job.status != VideoJobStatus.READY_TO_UPLOAD:
            continue
        rows.append(_job_row(job, channels))
    rows.sort(
        key=lambda r: (
            0 if r["job"].scheduled_time else 1,
            schedule_sort_key(r["job"].scheduled_time),
        )
    )
    return rows


def _youtube_jobs(channel_id: int | None = None) -> list[dict]:
    """Live schedule list from YouTube API merged with the database."""
    from core.youtube_uploader import (
        YouTubeUploaderError,
        fetch_channel_videos,
        is_connected,
        sync_channel_schedule_from_youtube,
    )

    channels = {ch.id: ch for ch in list_channels()}
    jobs_by_yt: dict[str, object] = {}
    for job in list_video_jobs():
        if channel_id is not None and job.channel_id != channel_id:
            continue
        if job.youtube_video_id:
            jobs_by_yt[job.youtube_video_id] = job

    rows: list[dict] = []

    channel_list = list_channels()
    if channel_id is not None:
        channel_list = [ch for ch in channel_list if ch.id == channel_id]

    for ch in channel_list:
        if not is_connected(ch):
            continue
        try:
            sync_channel_schedule_from_youtube(ch)
            for info in fetch_channel_videos(ch):
                job = jobs_by_yt.get(info.video_id)
                iso = info.publish_at.isoformat()
                if job:
                    row = _job_row(job, channels)
                    row["schedule"] = format_schedule_display(iso)
                    row["display_title"] = job.title or job.raw_topic or info.title
                    row["youtube_only"] = False
                    row["_sort"] = iso
                else:
                    row = {
                        "job": None,
                        "job_id": None,
                        "display_title": info.title,
                        "channel_name": channel_display_name(ch),
                        "youtube_name": ch.youtube_channel_name,
                        "schedule": format_schedule_display(iso),
                        "watch_url": f"https://www.youtube.com/watch?v={info.video_id}",
                        "youtube_only": True,
                        "privacy": info.privacy_status,
                        "_sort": iso,
                    }
                rows.append(row)
        except YouTubeUploaderError:
            continue

    # Newest upload / publish date first
    rows.sort(key=lambda r: schedule_sort_key(r.get("_sort")), reverse=True)
    return rows


def _status_counts(channel_id: int | None = None) -> dict[str, int]:
    counts = {s.value: 0 for s in VideoJobStatus}
    for job in list_video_jobs():
        if channel_id is not None and job.channel_id != channel_id:
            continue
        counts[job.status.value] += 1
    return counts


_PROCESSING_STATUSES = frozenset(
    {
        VideoJobStatus.GENERATING_TEXT,
        VideoJobStatus.GENERATING_AUDIO,
        VideoJobStatus.RENDERING,
    }
)


def _processing_active(channel_id: int | None = None) -> bool:
    return _production_ui_state(channel_id)["processing_active"]


def _production_ui_state(channel_id: int | None = None) -> dict:
    """Shared production flags for dashboard HTML and /api/status."""
    jobs = list_video_jobs()
    if channel_id is not None:
        jobs = [j for j in jobs if j.channel_id == channel_id]

    active_job = next(
        (j for j in jobs if j.status in _PROCESSING_STATUSES),
        None,
    )
    locked = _pipeline_lock.locked()
    processing = locked or active_job is not None
    runnable = get_runnable_jobs(include_failed=False, channel_id=channel_id)
    pending_count = sum(1 for j in jobs if j.status == VideoJobStatus.PENDING)
    failed_count = sum(1 for j in jobs if j.status == VideoJobStatus.FAILED)

    return {
        "processing_active": processing,
        "pipeline_locked": locked,
        "production_count": len(runnable),
        "failed_count": failed_count,
        "pending_production_count": pending_count,
        "active_job_id": active_job.id if active_job else None,
    }


def _queue_status_snapshot(channel_id: int | None = None) -> list[dict]:
    """Lightweight queue rows for live UI updates."""
    rows = []
    for job in list_video_jobs():
        if channel_id is not None and job.channel_id != channel_id:
            continue
        if job.status not in _QUEUE_STATUSES and job.status not in _PROCESSING_STATUSES:
            continue
        rows.append({"id": job.id, "status": job.status.value})
    rows.sort(key=lambda r: r["id"], reverse=True)
    return rows


def _content_fingerprint(channel_id: int | None = None) -> str:
    parts: list[str] = []
    for job in list_video_jobs():
        if channel_id is not None and job.channel_id != channel_id:
            continue
        parts.append(f"{job.id}:{job.status.value}:{job.updated_at or ''}")
    digest = hashlib.md5("|".join(sorted(parts)).encode(), usedforsecurity=False)
    return digest.hexdigest()[:16]


def _dashboard_stats(channel_id: int | None = None) -> dict:
    counts = _status_counts(channel_id)
    prod = _production_ui_state(channel_id)
    upload_ready = len(get_scheduled_ready_jobs(channel_id=channel_id))
    return {
        **prod,
        "counts": counts,
        "stat_ready": counts["READY_TO_UPLOAD"],
        "stat_processing": (
            counts["GENERATING_TEXT"]
            + counts["GENERATING_AUDIO"]
            + counts["RENDERING"]
        ),
        "stat_youtube": counts["COMPLETED"],
        "queue_jobs": _queue_status_snapshot(channel_id),
        "upload_active": _upload_lock.locked(),
        "upload_ready_count": upload_ready,
        "content_fingerprint": _content_fingerprint(channel_id),
    }


def _backgrounds_by_niche() -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    if not BACKGROUNDS_DIR.exists():
        return result

    for niche_dir in sorted(BACKGROUNDS_DIR.iterdir()):
        if not niche_dir.is_dir():
            continue
        niche = niche_dir.name
        result[niche] = []
        for f in list_backgrounds(niche):
            rel = f.relative_to(BACKGROUNDS_DIR)
            result[niche].append(
                {
                    "name": f.name,
                    "rel_path": str(rel),
                    "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
                }
            )
    return result


@app.route("/api/status")
def api_dashboard_status():
    """Live dashboard stats without full page reload."""
    cid = _resolve_channel_id()
    return jsonify(_dashboard_stats(cid))


@app.route("/lang/<code>")
def set_language(code: str):
    """Switch UI language (EN / TR)."""
    if code in SUPPORTED_LOCALES:
        session["lang"] = code
    dest = request.referrer or url_for("dashboard")
    resp = make_response(redirect(dest))
    if code in SUPPORTED_LOCALES:
        resp.set_cookie("lang", code, max_age=60 * 60 * 24 * 365)
    return resp


@app.route("/jobs/reset-stuck", methods=["POST"])
def reset_stuck_jobs():
    """Reset stuck production jobs to PENDING immediately."""
    stuck = recover_stuck_production_jobs()
    stale = recover_stale_production_jobs(stale_minutes=5)
    total = stuck + stale
    if total:
        flash_t("flash.stuck_reset", "success", n=total)
    else:
        flash_t("flash.no_stuck", "success")
    return _go_dashboard(request.form.get("return_channel", type=int))


def _build_dashboard_context(active_id: int | None) -> dict:
    """Full context dict for dashboard.html."""
    channels = list_channels()
    active_channel = get_channel(active_id) if active_id else None

    if not _pipeline_lock.locked():
        recover_stale_production_jobs(stale_minutes=25)

    counts = _status_counts(active_id)
    enriched = _channels_enriched()

    return {
        "active_channel_id": active_id or 0,
        "active_channel": active_channel,
        "active_channel_name": channel_display_name(active_channel)
        if active_channel
        else translate("empty.no_channel", get_locale()),
        "channel_picker": _channel_picker(active_id),
        "active_channel_thumbnail": (
            active_channel.youtube_channel_thumbnail if active_channel else ""
        ),
        "queue_jobs": _queue_jobs(active_id),
        "ready_jobs": _ready_jobs(active_id),
        "youtube_jobs": _youtube_jobs(active_id),
        "channels_enriched": enriched,
        "channels": channels,
        "counts": counts,
        "backgrounds": _backgrounds_by_niche(),
        "api": api_status(),
        "ollama_model": OLLAMA_MODEL,
        "backgrounds_dir": str(BACKGROUNDS_DIR),
        "connected_count": sum(1 for row in enriched if row["youtube_connected"]),
        "total_channels": len(channels),
        "voices": load_voices(),
        "niches": list_niches(),
        "niche_profiles": list_niche_profiles(),
        "niche_default_voice": niche_default_voice_id(active_channel)
        if active_channel
        else "",
        "channel_voice_override": channel_voice_override(active_channel) or "",
        "niche_voice_label": voice_label(
            niche_default_voice_id(active_channel) if active_channel else None
        ),
        "channel_voice_label": voice_label(channel_voice_id(active_channel)),
        **_production_ui_state(active_id),
        "schedule_peak_summary": peak_hours_summary(),
        "schedule_us_peak": SCHEDULE_US_PEAK_HOURS,
        "schedule_timezone": SCHEDULE_TIMEZONE,
        "display_timezone": SCHEDULE_DISPLAY_TIMEZONE,
        "declare_synthetic_media": YOUTUBE_DECLARE_SYNTHETIC_MEDIA,
        "max_desc_chars": MAX_SHORTS_DESCRIPTION_CHARS,
        "stat_ready": counts["READY_TO_UPLOAD"],
        "stat_processing": (
            counts["GENERATING_TEXT"]
            + counts["GENERATING_AUDIO"]
            + counts["RENDERING"]
        ),
        "stat_youtube": counts["COMPLETED"],
        "upload_ready_count": len(get_scheduled_ready_jobs(channel_id=active_id)),
        "upload_active": _upload_lock.locked(),
        "content_fingerprint": _content_fingerprint(active_id),
        "oauth_status": oauth_redirect_status(),
        "panel_url": f"http://{HOST}:{PORT}",
    }


@app.route("/")
def dashboard():
    channels = list_channels()
    active_id = _resolve_channel_id()
    if not active_id and channels:
        return redirect(url_for("dashboard", channel=channels[0].id))

    return render_template("dashboard.html", **_build_dashboard_context(active_id))


def _niche_voice_for_channel(channel_id: int | None) -> str | None:
    ch = get_channel(channel_id) if channel_id else None
    return channel_voice_id(ch) if ch else None


@app.route("/jobs/new", methods=["POST"])
def create_job():
    channel_id = request.form.get("channel_id", type=int)
    raw_topic = (request.form.get("raw_topic") or "").strip()
    background_video = (request.form.get("background_video") or "").strip() or None
    voice_id = _niche_voice_for_channel(channel_id)

    if not channel_id or not raw_topic:
        flash_t("flash.channel_topic_required", "error")
        return _go_dashboard(channel_id)

    try:
        create_video_job(
            channel_id,
            raw_topic,
            background_video=background_video,
            elevenlabs_voice_id=voice_id,
        )
        flash_t("flash.added_queue", "success")
    except RuntimeError as exc:
        flash(str(exc), "error")

    return _go_dashboard(channel_id)


def _existing_topics_for_channel(channel_id: int) -> list[str]:
    """Topics already used on this channel — avoid duplicates in AI generation."""
    topics: list[str] = []
    for job in list_video_jobs():
        if job.channel_id != channel_id:
            continue
        for value in (job.raw_topic, job.title):
            if value and value.strip():
                topics.append(value.strip())
    return topics


@app.route("/jobs/generate-topics", methods=["POST"])
def generate_topics():
    """Generate weekly video topics via Ollama and add them to the queue."""
    channel_id = request.form.get("channel_id", type=int)
    count = request.form.get("count", type=int) or 7
    count = max(1, min(count, 14))
    voice_id = _niche_voice_for_channel(channel_id)
    run_after = request.form.get("run_production") == "on"

    channel = get_channel(channel_id) if channel_id else None
    if not channel:
        flash_t("flash.select_channel", "error")
        return _go_dashboard(channel_id)

    try:
        topics = generate_video_topics(
            channel,
            count,
            avoid_topics=_existing_topics_for_channel(channel_id),
        )
    except LLMEngineError as exc:
        flash_t("flash.topics_failed", "error", err=exc)
        return _go_dashboard(channel_id)

    created = 0
    for topic in topics:
        try:
            create_video_job(channel_id, topic, elevenlabs_voice_id=voice_id)
            created += 1
        except RuntimeError:
            pass

    label = channel_display_name(channel)
    hint_key = "flash.hint_starting" if run_after and created else "flash.hint_produce"
    flash_t(
        "flash.topics_added",
        "success",
        label=label,
        n=created,
        hint=translate(hint_key, get_locale()),
    )

    if run_after and created:
        def _run():
            with _pipeline_lock:
                try:
                    run_pending(channel_id=channel_id)
                except Exception as exc:
                    print(f"[PIPELINE ERROR] {exc}")

        threading.Thread(target=_run, daemon=True).start()

    return _go_dashboard(channel_id)


@app.route("/jobs/bulk", methods=["POST"])
def create_bulk_jobs():
    """Add multiple topics to a channel (one line = one video)."""
    channel_id = request.form.get("channel_id", type=int)
    topics_raw = (request.form.get("topics") or "").strip()
    voice_id = _niche_voice_for_channel(channel_id)

    if not channel_id or not topics_raw:
        flash_t("flash.channel_topic_required", "error")
        return _go_dashboard(channel_id)

    topics = [t.strip() for t in topics_raw.splitlines() if t.strip()]
    created = 0
    for topic in topics:
        try:
            create_video_job(channel_id, topic, elevenlabs_voice_id=voice_id)
            created += 1
        except RuntimeError:
            pass

    flash_t("flash.bulk_added", "success", n=created)
    return _go_dashboard(channel_id)


_ACTIVE_JOB_STATUSES = frozenset(
    {
        VideoJobStatus.GENERATING_TEXT,
        VideoJobStatus.GENERATING_AUDIO,
        VideoJobStatus.RENDERING,
    }
)


def _job_deletable(job, *, pipeline_locked: bool) -> bool:
    if pipeline_locked and job.status in _ACTIVE_JOB_STATUSES:
        return False
    return True


def _remove_job_record(job_id: int) -> bool:
    job = get_video_job(job_id)
    if not job:
        return False
    _delete_job_files(job)
    return delete_video_job(job_id)


def _delete_job_files(job) -> None:
    """Remove rendered output and temp files for a job."""
    candidates: list[Path] = [
        OUTPUTS_DIR / f"job_{job.id}_final.mp4",
        TEMP_DIR / f"job_{job.id}_audio.mp3",
        TEMP_DIR / f"job_{job.id}_timestamps.json",
    ]
    for attr in (job.video_output_path, job.audio_path, job.timestamps_path):
        if attr:
            candidates.append(Path(attr))

    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass


@app.route("/jobs/<int:job_id>/delete", methods=["POST"])
def delete_job(job_id: int):
    job = get_video_job(job_id)
    if not job:
        flash_t("flash.job_not_found", "error")
        return _go_dashboard()

    if not _job_deletable(job, pipeline_locked=_pipeline_lock.locked()):
        flash_t("flash.job_delete_active", "error", id=job_id)
        return _go_dashboard(job.channel_id)

    try:
        if _remove_job_record(job_id):
            flash_t("flash.job_deleted", "success", id=job_id)
        else:
            flash_t("flash.delete_failed", "error")
    except RuntimeError as exc:
        flash(str(exc), "error")

    return _go_dashboard(job.channel_id)


def _start_pipeline_jobs(
    job_ids: list[int],
    *,
    channel_id: int | None,
    flash_single_id: int | None = None,
) -> None:
    """Run one or more jobs sequentially in the pipeline thread."""
    if _pipeline_lock.locked():
        flash_t("flash.production_running", "error")
        return

    def _run() -> None:
        with _pipeline_lock:
            try:
                for job_id in job_ids:
                    process_job(job_id)
            except Exception as exc:
                print(f"[PIPELINE ERROR] {exc}")

    threading.Thread(target=_run, daemon=True).start()
    ch = get_channel(channel_id) if channel_id else None
    label = channel_display_name(ch) if ch else translate("flash.label_channel", get_locale())
    if flash_single_id:
        flash_t("flash.job_retry_started", "success", id=flash_single_id)
    elif len(job_ids) == 1:
        flash_t("flash.job_retry_started", "success", id=job_ids[0])
    else:
        flash_t("flash.jobs_retry_bulk", "success", label=label, n=len(job_ids))


@app.route("/jobs/bulk-delete", methods=["POST"])
def bulk_delete_jobs():
    """Delete multiple queue or ready jobs for the active channel."""
    channel_id = request.form.get("return_channel", type=int)
    raw_ids = request.form.getlist("job_ids")
    job_ids: list[int] = []
    for raw in raw_ids:
        try:
            job_ids.append(int(raw))
        except (TypeError, ValueError):
            continue

    if not job_ids:
        flash_t("flash.no_jobs_selected", "error")
        return _go_dashboard(channel_id)

    locked = _pipeline_lock.locked()
    deleted = 0
    skipped = 0
    for job_id in job_ids:
        job = get_video_job(job_id)
        if not job:
            continue
        if channel_id and job.channel_id != channel_id:
            continue
        if not _job_deletable(job, pipeline_locked=locked):
            skipped += 1
            continue
        try:
            if _remove_job_record(job_id):
                deleted += 1
        except RuntimeError:
            skipped += 1

    if deleted:
        flash_t("flash.jobs_deleted_bulk", "success", n=deleted)
    if skipped:
        flash_t("flash.jobs_delete_skipped", "warning", n=skipped)
    elif not deleted:
        flash_t("flash.delete_failed", "error")

    return _go_dashboard(channel_id)


def _collect_retry_job_ids(
    raw_ids: list[str],
    *,
    channel_id: int | None,
) -> list[int]:
    """PENDING / FAILED jobs only, scoped to channel when set."""
    allowed = {VideoJobStatus.PENDING, VideoJobStatus.FAILED}
    job_ids: list[int] = []
    for raw in raw_ids:
        try:
            job_id = int(raw)
        except (TypeError, ValueError):
            continue
        job = get_video_job(job_id)
        if not job or job.status not in allowed:
            continue
        if channel_id and job.channel_id != channel_id:
            continue
        job_ids.append(job_id)
    return job_ids


@app.route("/jobs/bulk-retry", methods=["POST"])
def bulk_retry_jobs():
    """Retry selected PENDING or FAILED jobs for the active channel."""
    channel_id = request.form.get("return_channel", type=int)
    job_ids = _collect_retry_job_ids(request.form.getlist("job_ids"), channel_id=channel_id)
    if not job_ids:
        flash_t("flash.no_jobs_selected", "error")
        return _go_dashboard(channel_id)
    _start_pipeline_jobs(job_ids, channel_id=channel_id)
    return _go_dashboard(channel_id)


@app.route("/jobs/retry-failed", methods=["POST"])
def retry_all_failed_jobs():
    """Retry every FAILED job on the active channel."""
    channel_id = request.form.get("return_channel", type=int)
    job_ids = [
        j.id
        for j in list_video_jobs()
        if j.status == VideoJobStatus.FAILED
        and (not channel_id or j.channel_id == channel_id)
    ]
    if not job_ids:
        flash_t("flash.no_failed_jobs", "info")
        return _go_dashboard(channel_id)
    _start_pipeline_jobs(job_ids, channel_id=channel_id)
    return _go_dashboard(channel_id)


@app.route("/schedule/sync", methods=["POST"])
def sync_youtube_schedule():
    """Read actual YouTube publish times and sync them to the database."""
    channel_id = _resolve_channel_id(request.form.get("return_channel", type=int))
    ch = get_channel(channel_id) if channel_id else None
    label = channel_display_name(ch) if ch else translate("flash.label_channel", get_locale())
    try:
        synced = (
            sync_channel_from_youtube(channel_id)
            if channel_id
            else sync_all_channels_from_youtube()
        )
        flash_t("flash.sync_ok", "success", label=label, n=synced)
    except Exception as exc:
        flash_t("flash.sync_error", "error", err=exc)
    return _go_dashboard(channel_id)


@app.route("/schedule/auto", methods=["POST"])
def auto_schedule():
    channel_id = _resolve_channel_id(request.form.get("return_channel", type=int))
    ch = get_channel(channel_id) if channel_id else None
    label = channel_display_name(ch) if ch else translate("flash.label_channel", get_locale())
    try:
        synced = (
            sync_channel_from_youtube(channel_id)
            if channel_id
            else sync_all_channels_from_youtube()
        )
    except Exception:
        synced = 0
    count = auto_schedule_pending_jobs(channel_id=channel_id)
    summary = peak_hours_summary()
    if count:
        if SCHEDULE_US_PEAK_HOURS:
            flash_t(
                "flash.schedule_ok_peak",
                "success",
                label=label,
                synced=synced,
                count=count,
                summary=summary,
            )
        else:
            flash_t(
                "flash.schedule_ok",
                "success",
                label=label,
                synced=synced,
                count=count,
                summary=summary,
            )
    else:
        flash_t("flash.no_ready_schedule", "success", label=label)
    return _go_dashboard(channel_id)


@app.route("/jobs/condense-all", methods=["POST"])
def condense_all_ready_seo():
    """Trim all ready video descriptions to the max character limit."""
    channel_id = _resolve_channel_id(request.form.get("return_channel", type=int))
    count = 0
    for job in list_video_jobs():
        if channel_id is not None and job.channel_id != channel_id:
            continue
        if job.status != VideoJobStatus.READY_TO_UPLOAD:
            continue
        new_desc = condense_shorts_description(
            job.description or "",
            title=job.title or job.raw_topic,
        )
        if new_desc != (job.description or ""):
            update_job_fields(job.id, description=new_desc)
            count += 1
    flash_t("flash.seo_trimmed", "success", n=count)
    return _go_dashboard(channel_id)


@app.route("/jobs/<int:job_id>/seo", methods=["POST"])
def update_job_seo(job_id: int):
    """Edit title, description, and hashtags on a local job before upload."""
    job = get_video_job(job_id)
    if not job:
        flash_t("flash.job_not_found", "error")
        return _go_dashboard()

    if job.status != VideoJobStatus.READY_TO_UPLOAD:
        flash_t("flash.only_ready_edit", "error")
        return _go_dashboard(job.channel_id)

    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()

    if not title:
        flash_t("flash.title_empty", "error")
        return _go_dashboard(job.channel_id)

    if not description:
        flash_t("flash.desc_empty", "error")
        return _go_dashboard(job.channel_id)

    if len(description) > MAX_SHORTS_DESCRIPTION_CHARS:
        flash_t(
            "flash.desc_long",
            "error",
            n=len(description),
            max=MAX_SHORTS_DESCRIPTION_CHARS,
        )
        return _go_dashboard(job.channel_id)

    update_job_fields(job_id, title=title[:100], description=description)
    flash_t(
        "flash.seo_updated",
        "success",
        id=job_id,
        n=len(description),
        max=MAX_SHORTS_DESCRIPTION_CHARS,
    )
    return _go_dashboard(job.channel_id)


@app.route("/jobs/<int:job_id>/schedule", methods=["POST"])
def schedule_job(job_id: int):
    job = next((j for j in list_video_jobs() if j.id == job_id), None)
    if not job:
        flash_t("flash.job_not_found", "error")
        return _go_dashboard()
    if job.status != VideoJobStatus.READY_TO_UPLOAD:
        flash_t("flash.only_ready_schedule", "error")
        return _go_dashboard(job.channel_id)

    manual = (request.form.get("scheduled_time") or "").strip()
    browser_tz = (request.form.get("scheduled_timezone") or "").strip() or None
    try:
        if manual:
            slot = parse_manual_schedule_time(manual, browser_tz)
            assign_schedule_to_job(job_id, slot)
        else:
            assign_schedule_to_job(job_id)
        if manual:
            flash_t("flash.manual_schedule", "success")
        else:
            flash_t("flash.auto_schedule", "success")
    except (ValueError, RuntimeError) as exc:
        flash_t("flash.schedule_error", "error", err=exc)

    return _go_dashboard(job.channel_id)


@app.route("/upload/scheduled", methods=["POST"])
@app.route("/upload/scheduled/<int:channel_id>", methods=["POST"])
def upload_scheduled(channel_id: int | None = None):
    """Upload scheduled ready videos for the selected channel."""
    if channel_id is None:
        channel_id = _resolve_channel_id(request.form.get("return_channel", type=int))

    if _upload_lock.locked():
        flash_t("flash.upload_running", "error")
        return _go_dashboard(channel_id)

    ready = get_scheduled_ready_jobs(channel_id=channel_id)
    if not ready:
        flash_t("flash.nothing_upload", "error")
        return _go_dashboard(channel_id)

    ch = get_channel(channel_id) if channel_id else None
    label = (
        channel_display_name(ch)
        if ch
        else translate("flash.label_all_channels", get_locale())
    )

    def _run():
        with _upload_lock:
            try:
                run_uploads(channel_id=channel_id)
            except Exception as exc:
                print(f"[UPLOAD ERROR] {exc}")

    threading.Thread(target=_run, daemon=True).start()
    flash_t("flash.upload_started", "success", n=len(ready), label=label)
    return _go_dashboard(channel_id)


@app.route("/pipeline/run", methods=["POST"])
def run_pipeline():
    job_id = request.form.get("job_id", type=int)
    channel_id = _resolve_channel_id(request.form.get("return_channel", type=int))
    if job_id:
        job = get_video_job(job_id)
        if not job:
            flash_t("flash.job_not_found", "error")
            return _go_dashboard(channel_id)
        channel_id = job.channel_id
        if job.status not in (
            VideoJobStatus.PENDING,
            VideoJobStatus.FAILED,
        ):
            flash_t("flash.job_not_retryable", "error", id=job_id)
            return _go_dashboard(channel_id)
        _start_pipeline_jobs([job_id], channel_id=channel_id, flash_single_id=job_id)
        return _go_dashboard(channel_id)

    if _pipeline_lock.locked():
        flash_t("flash.production_running", "error")
        return _go_dashboard(channel_id)

    def _run():
        with _pipeline_lock:
            try:
                run_pending(channel_id=channel_id)
            except Exception as exc:
                print(f"[PIPELINE ERROR] {exc}")

    threading.Thread(target=_run, daemon=True).start()
    ch = get_channel(channel_id) if channel_id else None
    label = channel_display_name(ch) if ch else translate("flash.label_channel", get_locale())
    n = len(get_runnable_jobs(channel_id=channel_id))
    flash_t("flash.production_started", "success", label=label, n=n)
    return _go_dashboard(channel_id)


@app.route("/channels/new", methods=["POST"])
def new_channel():
    name = (request.form.get("channel_name") or "").strip()
    niche = (request.form.get("niche") or "").strip().lower()

    if not name or not niche:
        flash_t("flash.channel_fields", "error")
        return redirect(url_for("dashboard"))

    profile = get_niche(niche)
    if not profile:
        flash_t("flash.unknown_niche", "error", niche=niche)
        return redirect(url_for("dashboard"))

    tone = niche_tone_rules(niche)
    connect_youtube = request.form.get("connect_youtube") == "on"

    try:
        channel_id = create_channel(
            channel_name=name,
            niche=niche,
            tone_rules=tone,
            youtube_credentials_path=f"config/creds/channel_pending.json",
            elevenlabs_voice_id=None,
        )
        (BACKGROUNDS_DIR / niche).mkdir(parents=True, exist_ok=True)
    except RuntimeError as exc:
        flash(str(exc), "error")
        return redirect(url_for("dashboard"))

    if connect_youtube:
        flash_t("flash.channel_created_connect", "success", name=name)
        return redirect(url_for("youtube_connect", channel_id=channel_id))

    flash_t("flash.channel_created", "success", name=name)
    return redirect(url_for("dashboard"))


@app.route("/channels/<int:channel_id>/delete", methods=["POST"])
def remove_channel(channel_id: int):
    """Remove a panel channel, its queue, OAuth token, and local job files."""
    channel = get_channel(channel_id)
    if not channel:
        flash_t("flash.channel_not_found", "error")
        return redirect(url_for("dashboard"))

    if _processing_active(channel_id):
        flash_t("flash.channel_delete_blocked", "error")
        return _go_dashboard(channel_id)

    label = channel_display_name(channel)
    creds_rel = (channel.youtube_credentials_path or "").strip()

    try:
        disconnect_youtube(channel)
        for job in list_video_jobs():
            if job.channel_id == channel_id:
                _delete_job_files(job)
        if not delete_channel(channel_id):
            flash_t("flash.delete_failed", "error")
            return _go_dashboard(channel_id)

        if creds_rel and "channel_pending" not in creds_rel:
            creds_file = PROJECT_ROOT / creds_rel
            if creds_file.is_file():
                try:
                    creds_file.unlink()
                except OSError:
                    pass
    except RuntimeError as exc:
        flash(str(exc), "error")
        return _go_dashboard(channel_id)

    flash_t("flash.channel_deleted", "success", name=label)
    remaining = list_channels()
    if remaining:
        return redirect(url_for("dashboard", channel=remaining[0].id))
    return redirect(url_for("dashboard"))


@app.route("/channels/<int:channel_id>/voice", methods=["POST"])
def update_channel_voice(channel_id: int):
    """Optional per-channel voice override (default = niche profile)."""
    channel = get_channel(channel_id)
    if not channel:
        flash_t("flash.channel_not_found", "error")
        return redirect(url_for("dashboard"))

    raw = (request.form.get("elevenlabs_voice_id") or "").strip()
    update_channel(channel_id, elevenlabs_voice_id=raw or "")
    flash_t(
        "flash.voice_updated",
        "success",
        name=channel_display_name(channel),
    )
    return _go_dashboard(channel_id)


@app.route("/oauth/youtube/<int:channel_id>/connect", methods=["GET", "POST"])
def youtube_connect(channel_id: int):
    """Start OAuth — Google account picker opens automatically."""
    channel = get_channel(channel_id)
    if not channel:
        flash_t("flash.channel_not_found", "error")
        return redirect(url_for("dashboard"))

    oauth = oauth_redirect_status()
    if not oauth["aligned"]:
        flash_t("flash.oauth_mismatch", "error", uri=oauth["redirect_uri"])
        return redirect(url_for("dashboard"))

    try:
        auth_url, _ = get_authorization_url(channel_id)
        return redirect(auth_url)
    except YouTubeUploaderError as exc:
        flash(str(exc), "error")
        return redirect(url_for("dashboard"))


@app.route("/oauth/youtube/<int:channel_id>")
def youtube_authorize(channel_id: int):
    """Legacy alias — redirects to connect."""
    return youtube_connect(channel_id)


@app.route("/oauth/youtube/<int:channel_id>/disconnect", methods=["POST"])
def youtube_disconnect(channel_id: int):
    """Clear stored token and reconnect with a different Google account."""
    channel = get_channel(channel_id)
    if not channel:
        flash_t("flash.channel_not_found", "error")
        return redirect(url_for("dashboard"))

    disconnect_youtube(channel)
    flash_t("flash.youtube_disconnected", "success")
    return redirect(url_for("youtube_connect", channel_id=channel_id))


@app.route("/oauth/youtube/callback")
def youtube_callback():
    """Google OAuth callback — save token and redirect to the panel."""
    state = request.args.get("state")
    code = request.args.get("code")
    oauth_error = request.args.get("error")

    loc = get_locale()
    if oauth_error:
        flash_t("flash.youtube_denied", "error", err=oauth_error)
        return redirect(url_for("dashboard"))

    if not state or not code:
        flash_t("flash.oauth_missing", "error")
        return redirect(url_for("dashboard"))

    message = ""
    success = False
    try:
        channel_id = int(state)
        save_oauth_credentials(channel_id, request.url)
        channel = get_channel(channel_id)
        if channel:
            try:
                profile = fetch_channel_info(channel)
                message = translate("flash.youtube_connected", loc, title=profile.title)
                flash(message, "success")
            except YouTubeUploaderError:
                message = translate("flash.youtube_token_saved", loc)
                flash(message, "success")
        success = True
    except (ValueError, YouTubeUploaderError) as exc:
        message = translate("flash.youtube_connect_error", loc, err=exc)
        flash(message, "error")

    panel = url_for("dashboard", _external=False)
    fallback = translate("oauth.complete" if success else "oauth.error", loc)
    return f"""<!DOCTYPE html>
<html lang="{loc}"><head>
  <meta charset="UTF-8" />
  <meta http-equiv="refresh" content="2;url={panel}" />
  <title>{translate("oauth.page_title", loc)}</title>
  <style>body{{font-family:system-ui;background:#09090b;color:#e4e4e7;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}}
  .box{{text-align:center;padding:2rem;border:1px solid #3f3f46;border-radius:12px;max-width:420px}}
  a{{color:#a78bfa}}</style>
</head><body><div class="box">
  <p>{'✓' if success else '✗'} {message or fallback}</p>
  <p style="font-size:14px;color:#a1a1aa;margin-top:1rem">{translate("oauth.redirecting", loc)}</p>
  <p style="font-size:12px;color:#71717a;margin-top:1rem"><a href="{panel}">{translate("oauth.click_here", loc)}</a></p>
</div></body></html>"""


@app.route("/backgrounds/upload", methods=["POST"])
def upload_background():
    niche = (request.form.get("niche") or "").strip()
    file = request.files.get("background_file")

    if not niche or not file or not file.filename:
        flash_t("flash.bg_required", "error")
        return redirect(url_for("dashboard"))

    ext = Path(file.filename).suffix.lower()
    if ext not in VIDEO_EXTENSIONS:
        flash_t(
            "flash.bg_format",
            "error",
            formats=", ".join(VIDEO_EXTENSIONS),
        )
        return redirect(url_for("dashboard"))

    niche_dir = BACKGROUNDS_DIR / niche
    niche_dir.mkdir(parents=True, exist_ok=True)
    filename = secure_filename(file.filename)
    dest = niche_dir / filename
    file.save(dest)
    flash_t("flash.bg_uploaded", "success", path=f"{niche}/{filename}")
    return redirect(url_for("dashboard"))


@app.route("/videos/<path:filename>")
def serve_video(filename: str):
    safe = Path(filename)
    if ".." in safe.parts:
        abort(404)
    return send_from_directory(OUTPUTS_DIR, filename)


@app.route("/backgrounds/<path:filename>")
def serve_background(filename: str):
    safe = Path(filename)
    if ".." in safe.parts:
        abort(404)
    return send_from_directory(BACKGROUNDS_DIR, filename)


def bootstrap() -> None:
    ensure_dirs()
    init_db()
    oauth = oauth_redirect_status()
    print(f"  → OAuth redirect: {oauth['redirect_uri']}")
    print(
        "  → Google Cloud Console → Credentials → Authorized redirect URIs "
        f"(add if you see redirect_uri_mismatch): {oauth['redirect_uri']}"
    )


if __name__ == "__main__":
    bootstrap()
    print(f"\n  AutoTube Shorts — Admin Panel")
    print(f"  → http://{HOST}:{PORT}")
    print(f"  → Videolar: {OUTPUTS_DIR}")
    print(f"  → Backgrounds: {BACKGROUNDS_DIR}\n")
    # Disable debug reloader — it can restart the server during OAuth callback
    app.run(host=HOST, port=PORT, debug=True, use_reloader=False)
