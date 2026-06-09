"""
AutoTube-12 Central Orchestrator

Usage:
    python main.py run              # Process all PENDING jobs
    python main.py run --job-id 3   # Process a single job
    python main.py upload           # Upload READY_TO_UPLOAD jobs
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config.settings import BACKGROUNDS_DIR, DAEMON_INTERVAL_SECONDS, ensure_dirs
from core.database import (
    VideoJobStatus,
    db_session,
    get_channel,
    get_jobs_by_status,
    get_video_job,
    init_db,
    list_video_jobs,
    mark_job_completed,
    mark_job_failed,
    parse_visual_tags,
    save_audio_path,
    save_generated_text,
    save_rendered_video,
    update_job_fields,
    update_job_status,
)
from core.pexels_fetcher import resolve_background
from core.scheduler import auto_schedule_pending_jobs
from core.llm_engine import LLMEngineError, extract_youtube_tags, generate_script
from core.tts_engine import TTSEngineError, synthesize_speech
from core.video_editor import VideoEditorError, render_video
from core.youtube_uploader import (
    YouTubeUploaderError,
    fetch_channel_videos,
    is_connected,
    upload_and_schedule,
)
from core.youtube_uploader import _norm_title


def process_text(job_id: int) -> None:
    job = get_video_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    channel = get_channel(job.channel_id)
    if not channel:
        raise ValueError(f"Channel {job.channel_id} not found")

    update_job_status(job_id, VideoJobStatus.GENERATING_TEXT)
    result = generate_script(channel, job.raw_topic)
    save_generated_text(
        job_id,
        script=result.video_script,
        title=result.video_title,
        description=result.full_description,
        visual_tags=result.gorsel_etiketler,
    )


def process_audio(job_id: int) -> None:
    job = get_video_job(job_id)
    if not job or not job.script:
        raise ValueError(f"Job {job_id} has no script")

    channel = get_channel(job.channel_id)
    if not channel:
        raise ValueError(f"Channel {job.channel_id} not found")

    tts = synthesize_speech(
        channel, job.script, job_id, voice_id=job.elevenlabs_voice_id
    )
    save_audio_path(job_id, tts.audio_path, tts.timestamps_path)


def process_render(job_id: int) -> None:
    job = get_video_job(job_id)
    if not job or not job.audio_path or not job.timestamps_path:
        raise ValueError(f"Job {job_id} missing audio/timestamps")

    channel = get_channel(job.channel_id)
    if not channel:
        raise ValueError(f"Channel {job.channel_id} not found")

    visual_tags = parse_visual_tags(job)
    bg_path, bg_source = resolve_background(
        niche=channel.niche,
        job_id=job_id,
        visual_tags=visual_tags,
        preferred=job.background_video,
    )
    print(f"[BG] Job {job_id} background source: {bg_source}")

    rel_bg = None
    if bg_path:
        try:
            rel_bg = str(bg_path.relative_to(BACKGROUNDS_DIR))
        except ValueError:
            rel_bg = str(bg_path)
        update_job_fields(job_id, background_video=rel_bg)

    video_path = render_video(
        job_id=job_id,
        audio_path=Path(job.audio_path),
        timestamps_path=Path(job.timestamps_path),
        niche=channel.niche,
        background_video=rel_bg,
        channel_id=channel.id,
    )
    save_rendered_video(job_id, video_path)


def _upload_duplicate_reason(job) -> Optional[str]:
    """Block duplicate upload to the same channel — message or None."""
    if job.youtube_video_id:
        return f"Video already on YouTube ({job.youtube_video_id})"
    if job.status == VideoJobStatus.COMPLETED:
        return "Video already completed"

    norm = _norm_title(job.title or job.raw_topic or "")
    if not norm:
        return None

    for other in list_video_jobs():
        if other.id == job.id or other.channel_id != job.channel_id:
            continue
        if not other.youtube_video_id:
            continue
        if _norm_title(other.title or other.raw_topic or "") == norm:
            return (
                f"Same title already uploaded on this channel "
                f"(job #{other.id}, {other.youtube_video_id})"
            )

    channel = get_channel(job.channel_id)
    if channel and is_connected(channel):
        try:
            for info in fetch_channel_videos(channel):
                if _norm_title(info.title) == norm:
                    return (
                        f"Same title already exists on YouTube "
                        f"({info.video_id})"
                    )
        except YouTubeUploaderError:
            pass
    return None


def process_upload(job_id: int) -> None:
    job = get_video_job(job_id)
    if not job or not job.video_output_path:
        raise ValueError(f"Job {job_id} has no rendered video")

    channel = get_channel(job.channel_id)
    if not channel:
        raise ValueError(f"Channel {job.channel_id} not found")

    dup = _upload_duplicate_reason(job)
    if dup:
        raise ValueError(dup)

    if not is_connected(channel):
        from core.channels import channel_display_name

        raise YouTubeUploaderError(
            f"YouTube not connected: {channel_display_name(channel)}"
        )

    upload_desc = (job.description or job.raw_topic).strip()

    video_id = upload_and_schedule(
        channel,
        video_path=Path(job.video_output_path),
        title=job.title or job.raw_topic,
        description=upload_desc,
        scheduled_time=job.scheduled_time,
        tags=extract_youtube_tags(upload_desc),
    )

    mark_job_completed(
        job_id,
        scheduled_time=job.scheduled_time or datetime.utcnow().isoformat(),
    )
    update_job_fields(job_id, youtube_video_id=video_id)


_PRODUCTION_STATUSES = frozenset(
    {
        VideoJobStatus.PENDING,
        VideoJobStatus.FAILED,
        VideoJobStatus.GENERATING_TEXT,
        VideoJobStatus.GENERATING_AUDIO,
        VideoJobStatus.RENDERING,
    }
)


def get_production_jobs() -> list:
    """Queue view — pending, failed, and in-progress jobs."""
    jobs = [j for j in list_video_jobs() if j.status in _PRODUCTION_STATUSES]
    jobs.sort(key=lambda j: j.id)
    return jobs


def get_runnable_jobs(
    *,
    include_failed: bool = False,
    channel_id: int | None = None,
) -> list:
    """
    Run-all order — excludes FAILED by default.
    In-progress (render/audio/text) first, then PENDING.
    """
    jobs = [
        j
        for j in list_video_jobs()
        if j.status in _PRODUCTION_STATUSES
        and (include_failed or j.status != VideoJobStatus.FAILED)
        and (channel_id is None or j.channel_id == channel_id)
    ]

    def _priority(job) -> tuple[int, int]:
        if job.status == VideoJobStatus.RENDERING or (
            job.script and job.audio_path and not job.video_output_path
        ):
            return (0, job.id)
        if job.status in (
            VideoJobStatus.GENERATING_AUDIO,
            VideoJobStatus.GENERATING_TEXT,
        ):
            return (1, job.id)
        if job.status == VideoJobStatus.PENDING:
            return (2, job.id)
        return (3, job.id)

    jobs.sort(key=_priority)
    return jobs


def recover_ready_videos_marked_failed() -> int:
    """Recover ready videos marked FAILED after a YouTube upload error."""
    recovered = 0
    for job in list_video_jobs():
        if job.status != VideoJobStatus.FAILED or not job.video_output_path:
            continue
        update_job_fields(
            job.id,
            status=VideoJobStatus.READY_TO_UPLOAD,
            error_log="",
        )
        recovered += 1
    return recovered


def recover_stuck_production_jobs() -> int:
    """
    GENERATING_* durumunda takılı kalmış işleri PENDING'e al.
    Flask yeniden başlayınca veya Ollama timeout sonrası thread ölür; durum güncellenmez.
    """
    recovered = 0
    for job in list_video_jobs():
        if job.status == VideoJobStatus.GENERATING_TEXT and not job.script:
            update_job_fields(job.id, status=VideoJobStatus.PENDING, error_log="")
            recovered += 1
        elif job.status == VideoJobStatus.GENERATING_AUDIO and not job.audio_path:
            update_job_fields(job.id, status=VideoJobStatus.PENDING, error_log="")
            recovered += 1
        elif job.status == VideoJobStatus.RENDERING and not job.video_output_path:
            update_job_fields(job.id, status=VideoJobStatus.PENDING, error_log="")
            recovered += 1
    return recovered


def recover_stale_production_jobs(*, stale_minutes: int = 25) -> int:
    """
    Reset jobs stuck in GENERATING/RENDERING (dead thread / timeout).
    Stops the panel from refreshing forever after an Ollama timeout (~10 min).
    """
    cutoff = (datetime.utcnow() - timedelta(minutes=stale_minutes)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    active = (
        VideoJobStatus.GENERATING_TEXT.value,
        VideoJobStatus.GENERATING_AUDIO.value,
        VideoJobStatus.RENDERING.value,
    )
    try:
        with db_session() as conn:
            rows = conn.execute(
                """
                SELECT id FROM video_jobs
                WHERE status IN (?, ?, ?) AND updated_at < ?;
                """,
                (*active, cutoff),
            ).fetchall()
    except Exception:
        return 0

    recovered = 0
    for row in rows:
        update_job_fields(int(row["id"]), status=VideoJobStatus.PENDING, error_log="")
        recovered += 1
    return recovered


def process_job(job_id: int) -> None:
    """Production: text → audio → render. YouTube upload is separate (run_uploads)."""
    job = get_video_job(job_id)
    if not job:
        print(f"[SKIP] Job {job_id} not found")
        return

    if job.status == VideoJobStatus.COMPLETED:
        print(f"[SKIP] Job {job_id} already completed")
        return

    if job.status == VideoJobStatus.READY_TO_UPLOAD:
        print(f"[SKIP] Job {job_id} is ready — use Upload in the admin panel")
        return

    if job.status == VideoJobStatus.FAILED:
        update_job_fields(job_id, status=VideoJobStatus.PENDING, error_log="")
        job = get_video_job(job_id)
        print(f"[RETRY] Job {job_id} reset to PENDING")

    print(f"[START] Job {job_id}: {job.raw_topic if job else job_id}")

    try:
        job = get_video_job(job_id)
        if job and not job.script:
            process_text(job_id)
            job = get_video_job(job_id)

        if job and job.script and not job.audio_path:
            process_audio(job_id)
            job = get_video_job(job_id)

        if job and job.audio_path and not job.video_output_path:
            process_render(job_id)
            job = get_video_job(job_id)

        job = get_video_job(job_id)
        if (
            job
            and job.video_output_path
            and job.script
            and job.audio_path
            and job.status
            not in (VideoJobStatus.COMPLETED, VideoJobStatus.READY_TO_UPLOAD)
        ):
            update_job_fields(job_id, status=VideoJobStatus.READY_TO_UPLOAD)

        print(f"[DONE] Job {job_id}")
    except (LLMEngineError, TTSEngineError, VideoEditorError, YouTubeUploaderError, ValueError) as exc:
        mark_job_failed(job_id, str(exc))
        print(f"[FAILED] Job {job_id}: {exc}")
    except Exception as exc:
        mark_job_failed(job_id, f"{exc}\n{traceback.format_exc()}")
        print(f"[FAILED] Job {job_id}: {exc}")


def run_pending(
    *,
    job_id: int | None = None,
    channel_id: int | None = None,
) -> None:
    ensure_dirs()
    init_db()

    if job_id:
        process_job(job_id)
        return

    recovered = recover_stuck_production_jobs()
    if recovered:
        print(f"[RECOVER] {recovered} stuck job(s) reset to PENDING.")
    ready_fix = recover_ready_videos_marked_failed()
    if ready_fix:
        print(f"[RECOVER] {ready_fix} ready video(s) restored from FAILED.")

    jobs = get_runnable_jobs(include_failed=False, channel_id=channel_id)
    if not jobs:
        print("No runnable production jobs found.")
        return

    print(f"Processing {len(jobs)} job(s) (production only, FAILED skipped)...")
    for job in jobs:
        process_job(job.id)


def run_schedule() -> None:
    """Auto-assign publish times to ready videos without a schedule."""
    ensure_dirs()
    init_db()
    count = auto_schedule_pending_jobs()
    print(f"Scheduled {count} job(s).")


def run_daemon() -> None:
    """Continuous production loop — does not upload (use upload command separately)."""
    import time

    ensure_dirs()
    init_db()
    print(f"Daemon started (interval={DAEMON_INTERVAL_SECONDS}s). Ctrl+C to stop.")

    while True:
        try:
            scheduled = auto_schedule_pending_jobs()
            if scheduled:
                print(f"[SCHEDULE] {scheduled} job(s) auto-scheduled.")

            jobs = get_runnable_jobs(include_failed=False)
            if jobs:
                print(f"[DAEMON] Processing {len(jobs)} job(s)...")
                for job in jobs:
                    process_job(job.id)
        except KeyboardInterrupt:
            print("\nDaemon stopped.")
            break
        except Exception as exc:
            print(f"[DAEMON ERROR] {exc}")

        time.sleep(DAEMON_INTERVAL_SECONDS)


def get_scheduled_ready_jobs(*, channel_id: Optional[int] = None) -> list:
    """Ready jobs with a schedule that are not yet on YouTube."""
    jobs = [
        j
        for j in get_jobs_by_status(VideoJobStatus.READY_TO_UPLOAD)
        if j.scheduled_time
        and j.video_output_path
        and not j.youtube_video_id
    ]
    if channel_id is not None:
        jobs = [j for j in jobs if j.channel_id == channel_id]
    return jobs


def run_uploads(*, channel_id: Optional[int] = None) -> int:
    """Upload scheduled ready videos to each channel's YouTube account."""
    ensure_dirs()
    init_db()

    jobs = get_scheduled_ready_jobs(channel_id=channel_id)
    if not jobs:
        print("No scheduled READY_TO_UPLOAD jobs found.")
        return 0

    uploaded = 0
    for job in jobs:
        try:
            process_upload(job.id)
            uploaded += 1
            print(f"[UPLOADED] Job {job.id}")
        except (YouTubeUploaderError, ValueError) as exc:
            update_job_fields(job.id, error_log=str(exc))
            print(f"[UPLOAD FAILED] Job {job.id}: {exc}")
        except Exception as exc:
            update_job_fields(job.id, error_log=str(exc))
            print(f"[UPLOAD FAILED] Job {job.id}: {exc}")
    return uploaded


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoTube-12 Pipeline Orchestrator")
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run", help="Process pending video jobs")
    run_parser.add_argument("--job-id", type=int, help="Process a single job")
    sub.add_parser("upload", help="Upload scheduled ready videos to YouTube")
    sub.add_parser("schedule", help="Auto-assign publish times to unscheduled jobs")

    sub.add_parser("daemon", help="Continuous production loop (does not upload)")

    args = parser.parse_args()

    if args.command == "run":
        run_pending(job_id=args.job_id)
    elif args.command == "upload":
        run_uploads()
    elif args.command == "schedule":
        run_schedule()
    elif args.command == "daemon":
        run_daemon()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
