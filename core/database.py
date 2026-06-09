"""
SQLite database layer for AutoTube Shorts.

Handles connection management, schema migrations, and video_jobs state transitions.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Generator, Optional

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "pipeline.db"

SCHEMA_VERSION = 5


class VideoJobStatus(str, Enum):
    """Allowed workflow states for video_jobs."""

    PENDING = "PENDING"
    GENERATING_TEXT = "GENERATING_TEXT"
    GENERATING_AUDIO = "GENERATING_AUDIO"
    RENDERING = "RENDERING"
    READY_TO_UPLOAD = "READY_TO_UPLOAD"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# Ordered pipeline transitions (excluding FAILED, which is a terminal error state).
PIPELINE_STATUSES: tuple[VideoJobStatus, ...] = (
    VideoJobStatus.PENDING,
    VideoJobStatus.GENERATING_TEXT,
    VideoJobStatus.GENERATING_AUDIO,
    VideoJobStatus.RENDERING,
    VideoJobStatus.READY_TO_UPLOAD,
    VideoJobStatus.COMPLETED,
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Channel:
    id: int
    channel_name: str
    niche: str
    tone_rules: str
    youtube_credentials_path: str
    elevenlabs_voice_id: Optional[str] = None
    youtube_connected: bool = False
    youtube_channel_name: Optional[str] = None
    youtube_channel_thumbnail: Optional[str] = None


@dataclass
class VideoJob:
    id: int
    channel_id: int
    raw_topic: str
    status: VideoJobStatus
    script: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    audio_path: Optional[str] = None
    video_output_path: Optional[str] = None
    scheduled_time: Optional[str] = None
    error_log: Optional[str] = None
    background_video: Optional[str] = None
    timestamps_path: Optional[str] = None
    youtube_video_id: Optional[str] = None
    visual_tags: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = None
    updated_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def _ensure_data_dir(db_path: Path) -> None:
    """Create the parent directory for the SQLite file if it does not exist."""
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Failed to create database directory: {db_path.parent}"
        ) from exc


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """
    Return a SQLite connection with row-factory and foreign-key enforcement.

    Caller is responsible for closing the connection.
    """
    try:
        _ensure_data_dir(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to connect to database at {db_path}") from exc


@contextmanager
def db_session(db_path: Path = DEFAULT_DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    """Context manager that commits on success and rolls back on failure."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

_MIGRATIONS: dict[int, list[str]] = {
    1: [
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     INTEGER PRIMARY KEY,
            applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS channels (
            id                        INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_name              TEXT NOT NULL,
            niche                     TEXT NOT NULL,
            tone_rules                TEXT NOT NULL,
            youtube_credentials_path  TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS video_jobs (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id        INTEGER NOT NULL,
            raw_topic         TEXT NOT NULL,
            status            TEXT NOT NULL DEFAULT 'PENDING'
                              CHECK (status IN (
                                  'PENDING',
                                  'GENERATING_TEXT',
                                  'GENERATING_AUDIO',
                                  'RENDERING',
                                  'READY_TO_UPLOAD',
                                  'COMPLETED',
                                  'FAILED'
                              )),
            script            TEXT,
            title             TEXT,
            description       TEXT,
            audio_path        TEXT,
            video_output_path TEXT,
            scheduled_time    TEXT,
            error_log         TEXT,
            created_at        TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (channel_id) REFERENCES channels (id)
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_video_jobs_status
            ON video_jobs (status);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_video_jobs_channel_id
            ON video_jobs (channel_id);
        """,
    ],
    2: [
        "ALTER TABLE channels ADD COLUMN elevenlabs_voice_id TEXT;",
        "ALTER TABLE channels ADD COLUMN youtube_connected INTEGER NOT NULL DEFAULT 0;",
        "ALTER TABLE channels ADD COLUMN youtube_channel_name TEXT;",
        "ALTER TABLE video_jobs ADD COLUMN background_video TEXT;",
        "ALTER TABLE video_jobs ADD COLUMN timestamps_path TEXT;",
        "ALTER TABLE video_jobs ADD COLUMN youtube_video_id TEXT;",
    ],
    3: [
        "ALTER TABLE video_jobs ADD COLUMN visual_tags TEXT;",
    ],
    4: [
        "ALTER TABLE video_jobs ADD COLUMN elevenlabs_voice_id TEXT;",
    ],
    5: [
        "ALTER TABLE channels ADD COLUMN youtube_channel_thumbnail TEXT;",
    ],
}


def _get_applied_version(conn: sqlite3.Connection) -> int:
    """Return the highest applied migration version, or 0 if none."""
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     INTEGER PRIMARY KEY,
                applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations;"
        ).fetchone()
        return int(row["version"]) if row else 0
    except sqlite3.Error as exc:
        raise RuntimeError("Failed to read schema migration version") from exc


def run_migrations(db_path: Path = DEFAULT_DB_PATH) -> int:
    """
    Apply pending schema migrations idempotently.

    Returns the schema version after migration.
    """
    try:
        with db_session(db_path) as conn:
            current_version = _get_applied_version(conn)

            for version in range(current_version + 1, SCHEMA_VERSION + 1):
                statements = _MIGRATIONS.get(version)
                if not statements:
                    raise RuntimeError(f"No migration defined for version {version}")

                for statement in statements:
                    try:
                        conn.execute(statement)
                    except sqlite3.OperationalError as exc:
                        if "duplicate column name" not in str(exc).lower():
                            raise

                conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES (?);",
                    (version,),
                )

            return SCHEMA_VERSION
    except sqlite3.Error as exc:
        raise RuntimeError("Database migration failed") from exc


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Initialize the database by running all pending migrations."""
    run_migrations(db_path)


# ---------------------------------------------------------------------------
# Row mappers
# ---------------------------------------------------------------------------


def _row_get(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def _row_to_channel(row: sqlite3.Row) -> Channel:
    return Channel(
        id=row["id"],
        channel_name=row["channel_name"],
        niche=row["niche"],
        tone_rules=row["tone_rules"],
        youtube_credentials_path=row["youtube_credentials_path"],
        elevenlabs_voice_id=_row_get(row, "elevenlabs_voice_id"),
        youtube_connected=bool(_row_get(row, "youtube_connected", 0)),
        youtube_channel_name=_row_get(row, "youtube_channel_name"),
        youtube_channel_thumbnail=_row_get(row, "youtube_channel_thumbnail"),
    )


def _row_to_video_job(row: sqlite3.Row) -> VideoJob:
    return VideoJob(
        id=row["id"],
        channel_id=row["channel_id"],
        raw_topic=row["raw_topic"],
        status=VideoJobStatus(row["status"]),
        script=row["script"],
        title=row["title"],
        description=row["description"],
        audio_path=row["audio_path"],
        video_output_path=row["video_output_path"],
        scheduled_time=row["scheduled_time"],
        error_log=row["error_log"],
        background_video=_row_get(row, "background_video"),
        timestamps_path=_row_get(row, "timestamps_path"),
        youtube_video_id=_row_get(row, "youtube_video_id"),
        visual_tags=_row_get(row, "visual_tags"),
        elevenlabs_voice_id=_row_get(row, "elevenlabs_voice_id"),
        updated_at=_row_get(row, "updated_at"),
    )


# ---------------------------------------------------------------------------
# Channel operations
# ---------------------------------------------------------------------------


def create_channel(
    channel_name: str,
    niche: str,
    tone_rules: str,
    youtube_credentials_path: str,
    elevenlabs_voice_id: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    """Insert a new channel and return its id."""
    try:
        with db_session(db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO channels (
                    channel_name, niche, tone_rules,
                    youtube_credentials_path, elevenlabs_voice_id
                ) VALUES (?, ?, ?, ?, ?);
                """,
                (
                    channel_name,
                    niche,
                    tone_rules,
                    youtube_credentials_path,
                    elevenlabs_voice_id,
                ),
            )
            return int(cursor.lastrowid)
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to create channel '{channel_name}'") from exc


def update_channel(
    channel_id: int,
    *,
    channel_name: Optional[str] = None,
    niche: Optional[str] = None,
    tone_rules: Optional[str] = None,
    elevenlabs_voice_id: Optional[str] = None,
    youtube_connected: Optional[bool] = None,
    youtube_channel_name: Optional[str] = None,
    youtube_channel_thumbnail: Optional[str] = None,
    youtube_credentials_path: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    """Partially update a channel record."""
    field_map: dict[str, Any] = {}
    if channel_name is not None:
        field_map["channel_name"] = channel_name
    if niche is not None:
        field_map["niche"] = niche
    if tone_rules is not None:
        field_map["tone_rules"] = tone_rules
    if elevenlabs_voice_id is not None:
        field_map["elevenlabs_voice_id"] = elevenlabs_voice_id
    if youtube_connected is not None:
        field_map["youtube_connected"] = int(youtube_connected)
    if youtube_channel_name is not None:
        field_map["youtube_channel_name"] = youtube_channel_name
    if youtube_channel_thumbnail is not None:
        field_map["youtube_channel_thumbnail"] = youtube_channel_thumbnail
    if youtube_credentials_path is not None:
        field_map["youtube_credentials_path"] = youtube_credentials_path

    if not field_map:
        return get_channel(channel_id, db_path) is not None

    set_clause = ", ".join(f"{col} = ?" for col in field_map)
    values = list(field_map.values()) + [channel_id]

    try:
        with db_session(db_path) as conn:
            cursor = conn.execute(
                f"UPDATE channels SET {set_clause} WHERE id = ?;",
                values,
            )
            return cursor.rowcount > 0
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to update channel id={channel_id}") from exc


def get_channel(channel_id: int, db_path: Path = DEFAULT_DB_PATH) -> Optional[Channel]:
    """Fetch a single channel by id."""
    try:
        with db_session(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM channels WHERE id = ?;",
                (channel_id,),
            ).fetchone()
            return _row_to_channel(row) if row else None
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to fetch channel id={channel_id}") from exc


def list_channels(db_path: Path = DEFAULT_DB_PATH) -> list[Channel]:
    """Return all configured channels."""
    try:
        with db_session(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM channels ORDER BY id ASC;"
            ).fetchall()
            return [_row_to_channel(row) for row in rows]
    except sqlite3.Error as exc:
        raise RuntimeError("Failed to list channels") from exc


def delete_channel(channel_id: int, db_path: Path = DEFAULT_DB_PATH) -> bool:
    """Delete a channel and all of its video jobs."""
    try:
        with db_session(db_path) as conn:
            conn.execute(
                "DELETE FROM video_jobs WHERE channel_id = ?;",
                (channel_id,),
            )
            cursor = conn.execute(
                "DELETE FROM channels WHERE id = ?;",
                (channel_id,),
            )
            return cursor.rowcount > 0
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to delete channel id={channel_id}") from exc


# ---------------------------------------------------------------------------
# Video job operations
# ---------------------------------------------------------------------------


def create_video_job(
    channel_id: int,
    raw_topic: str,
    *,
    scheduled_time: Optional[datetime | str] = None,
    background_video: Optional[str] = None,
    elevenlabs_voice_id: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    """Insert a new PENDING video job and return its id."""
    sched = None
    if scheduled_time is not None:
        sched = (
            scheduled_time.isoformat()
            if isinstance(scheduled_time, datetime)
            else scheduled_time
        )

    try:
        with db_session(db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO video_jobs (
                    channel_id, raw_topic, status, scheduled_time,
                    background_video, elevenlabs_voice_id
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    channel_id,
                    raw_topic,
                    VideoJobStatus.PENDING.value,
                    sched,
                    background_video,
                    elevenlabs_voice_id,
                ),
            )
            return int(cursor.lastrowid)
    except sqlite3.Error as exc:
        raise RuntimeError(
            f"Failed to create video job for channel_id={channel_id}"
        ) from exc


def get_video_job(job_id: int, db_path: Path = DEFAULT_DB_PATH) -> Optional[VideoJob]:
    """Fetch a single video job by id."""
    try:
        with db_session(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM video_jobs WHERE id = ?;",
                (job_id,),
            ).fetchone()
            return _row_to_video_job(row) if row else None
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to fetch video job id={job_id}") from exc


def get_jobs_by_status(
    status: VideoJobStatus,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[VideoJob]:
    """Return all video jobs matching the given status."""
    try:
        with db_session(db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM video_jobs
                WHERE status = ?
                ORDER BY created_at ASC, id ASC;
                """,
                (status.value,),
            ).fetchall()
            return [_row_to_video_job(row) for row in rows]
    except sqlite3.Error as exc:
        raise RuntimeError(
            f"Failed to fetch jobs with status={status.value}"
        ) from exc


def get_pending_jobs(db_path: Path = DEFAULT_DB_PATH) -> list[VideoJob]:
    """Convenience wrapper used by the orchestrator to fetch PENDING jobs."""
    return get_jobs_by_status(VideoJobStatus.PENDING, db_path)


def list_video_jobs(db_path: Path = DEFAULT_DB_PATH) -> list[VideoJob]:
    """Return all video jobs, newest first."""
    try:
        with db_session(db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM video_jobs
                ORDER BY created_at DESC, id DESC;
                """
            ).fetchall()
            return [_row_to_video_job(row) for row in rows]
    except sqlite3.Error as exc:
        raise RuntimeError("Failed to list video jobs") from exc


def delete_video_job(job_id: int, db_path: Path = DEFAULT_DB_PATH) -> bool:
    """Delete a video job record from the database."""
    try:
        with db_session(db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM video_jobs WHERE id = ?;",
                (job_id,),
            )
            return cursor.rowcount > 0
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to delete video job id={job_id}") from exc


def _touch_job_updated_at(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute(
        """
        UPDATE video_jobs
        SET updated_at = datetime('now')
        WHERE id = ?;
        """,
        (job_id,),
    )


def update_job_status(
    job_id: int,
    status: VideoJobStatus,
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    """
    Set the workflow status of a video job.

    Returns True if a row was updated, False if the job does not exist.
    """
    try:
        with db_session(db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE video_jobs
                SET status = ?, updated_at = datetime('now')
                WHERE id = ?;
                """,
                (status.value, job_id),
            )
            return cursor.rowcount > 0
    except sqlite3.Error as exc:
        raise RuntimeError(
            f"Failed to update status for job id={job_id} to {status.value}"
        ) from exc


def advance_job_status(
    job_id: int,
    db_path: Path = DEFAULT_DB_PATH,
) -> VideoJobStatus:
    """
    Move a job to the next pipeline status.

    Raises ValueError if the job is already COMPLETED, FAILED, or at the last step.
    """
    job = get_video_job(job_id, db_path)
    if job is None:
        raise ValueError(f"Video job id={job_id} not found")

    if job.status in (VideoJobStatus.COMPLETED, VideoJobStatus.FAILED):
        raise ValueError(
            f"Cannot advance job id={job_id} from terminal status {job.status.value}"
        )

    try:
        current_index = PIPELINE_STATUSES.index(job.status)
    except ValueError as exc:
        raise ValueError(f"Unknown pipeline status: {job.status.value}") from exc

    if current_index >= len(PIPELINE_STATUSES) - 1:
        raise ValueError(
            f"Job id={job_id} is already at the final pipeline status "
            f"({job.status.value})"
        )

    next_status = PIPELINE_STATUSES[current_index + 1]
    update_job_status(job_id, next_status, db_path)
    return next_status


def mark_job_failed(
    job_id: int,
    error_message: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    """
    Set a job to FAILED and persist the error message.

    Returns True if a row was updated, False if the job does not exist.
    """
    try:
        with db_session(db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE video_jobs
                SET status = ?,
                    error_log = ?,
                    updated_at = datetime('now')
                WHERE id = ?;
                """,
                (VideoJobStatus.FAILED.value, error_message, job_id),
            )
            return cursor.rowcount > 0
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to mark job id={job_id} as FAILED") from exc


def update_job_fields(
    job_id: int,
    *,
    status: Optional[VideoJobStatus] = None,
    script: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    audio_path: Optional[str] = None,
    video_output_path: Optional[str] = None,
    scheduled_time: Optional[datetime | str] = None,
    clear_scheduled_time: bool = False,
    error_log: Optional[str] = None,
    background_video: Optional[str] = None,
    timestamps_path: Optional[str] = None,
    youtube_video_id: Optional[str] = None,
    clear_youtube_video_id: bool = False,
    visual_tags: Optional[str] = None,
    elevenlabs_voice_id: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    """
    Partially update nullable video_jobs columns.

    Only keyword arguments that are not None are written.
    Use clear_youtube_video_id=True to set youtube_video_id to NULL.
    Use clear_scheduled_time=True to set scheduled_time to NULL.
    Returns True if a row was updated, False if the job does not exist.
    """
    field_map: dict[str, Any] = {}

    if status is not None:
        field_map["status"] = status.value
    if script is not None:
        field_map["script"] = script
    if title is not None:
        field_map["title"] = title
    if description is not None:
        field_map["description"] = description
    if audio_path is not None:
        field_map["audio_path"] = str(audio_path)
    if video_output_path is not None:
        field_map["video_output_path"] = str(video_output_path)
    if clear_scheduled_time:
        field_map["scheduled_time"] = None
    elif scheduled_time is not None:
        if isinstance(scheduled_time, datetime):
            field_map["scheduled_time"] = scheduled_time.isoformat()
        else:
            field_map["scheduled_time"] = scheduled_time
    if error_log is not None:
        field_map["error_log"] = error_log
    if background_video is not None:
        field_map["background_video"] = background_video
    if timestamps_path is not None:
        field_map["timestamps_path"] = str(timestamps_path)
    if clear_youtube_video_id:
        field_map["youtube_video_id"] = None
    elif youtube_video_id is not None:
        field_map["youtube_video_id"] = youtube_video_id
    if visual_tags is not None:
        field_map["visual_tags"] = visual_tags
    if elevenlabs_voice_id is not None:
        field_map["elevenlabs_voice_id"] = elevenlabs_voice_id

    if not field_map:
        return get_video_job(job_id, db_path) is not None

    set_clause = ", ".join(f"{column} = ?" for column in field_map)
    values = list(field_map.values()) + [job_id]

    try:
        with db_session(db_path) as conn:
            cursor = conn.execute(
                f"""
                UPDATE video_jobs
                SET {set_clause}, updated_at = datetime('now')
                WHERE id = ?;
                """,
                values,
            )
            return cursor.rowcount > 0
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to update fields for job id={job_id}") from exc


def save_generated_text(
    job_id: int,
    script: str,
    title: str,
    description: str,
    visual_tags: Optional[list[str]] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    """Persist LLM output and move the job to GENERATING_AUDIO."""
    import json

    tags_json = json.dumps(visual_tags, ensure_ascii=False) if visual_tags else None
    return update_job_fields(
        job_id,
        status=VideoJobStatus.GENERATING_AUDIO,
        script=script,
        title=title,
        description=description,
        visual_tags=tags_json,
        db_path=db_path,
    )


def parse_visual_tags(job: VideoJob) -> list[str]:
    """Parse visual_tags JSON column into a list of strings."""
    import json

    if not job.visual_tags:
        return []
    try:
        data = json.loads(job.visual_tags)
        return [str(t).strip() for t in data if str(t).strip()]
    except (json.JSONDecodeError, TypeError):
        return []


def save_audio_path(
    job_id: int,
    audio_path: Path | str,
    timestamps_path: Optional[Path | str] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    """Persist the TTS audio file path and move the job to RENDERING."""
    return update_job_fields(
        job_id,
        status=VideoJobStatus.RENDERING,
        audio_path=audio_path,
        timestamps_path=timestamps_path,
        db_path=db_path,
    )


def save_rendered_video(
    job_id: int,
    video_output_path: Path | str,
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    """Persist the rendered video path and move the job to READY_TO_UPLOAD."""
    return update_job_fields(
        job_id,
        status=VideoJobStatus.READY_TO_UPLOAD,
        video_output_path=video_output_path,
        db_path=db_path,
    )


def mark_job_completed(
    job_id: int,
    scheduled_time: Optional[datetime | str] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    """Mark a job as COMPLETED after a successful YouTube upload/schedule."""
    return update_job_fields(
        job_id,
        status=VideoJobStatus.COMPLETED,
        scheduled_time=scheduled_time,
        db_path=db_path,
    )
