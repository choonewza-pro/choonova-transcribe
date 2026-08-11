import os
import sqlite3
import json
import time
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from app.config import (
    DATA_DIR,
    JOBS_DB_PATH,
    CLEANUP_RETENTION_HOURS,
    TARGET_CHUNK_DURATION_SEC,
    MAX_CHUNK_DURATION_SEC,
    MODEL_LOAD_MODE_DEFAULT,
    MODEL_IDLE_TIMEOUT_SEC_DEFAULT,
    COMPRESS_RETENTION_HOURS,
    COMPRESS_ENCODER,
    COMPRESS_PRESET,
    COMPRESS_CRF,
)

logger = logging.getLogger("typhoon-asr-db")


def get_db_connection() -> sqlite3.Connection:
    """
    Get SQLite database connection with Row factory for dict-like access.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(JOBS_DB_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """
    Initialize SQLite database tables if they do not exist.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                file_size_bytes INTEGER DEFAULT 0,
                language TEXT DEFAULT 'th',
                status TEXT NOT NULL,
                progress_pct REAL DEFAULT 0.0,
                current_stage TEXT DEFAULT '',
                total_chunks INTEGER DEFAULT 0,
                completed_chunks INTEGER DEFAULT 0,
                duration_seconds REAL DEFAULT 0.0,
                elapsed_seconds REAL DEFAULT 0.0,
                result_text TEXT,
                timestamps_json TEXT,
                srt_text TEXT,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Migrations for existing databases created before newer columns existed.
        columns = [r["name"] for r in cursor.execute("PRAGMA table_info(jobs)").fetchall()]
        if "language" not in columns:
            cursor.execute(
                "ALTER TABLE jobs ADD COLUMN language TEXT DEFAULT 'th'"
            )
        if "target_chunk_sec" not in columns:
            cursor.execute(
                f"ALTER TABLE jobs ADD COLUMN target_chunk_sec REAL DEFAULT {TARGET_CHUNK_DURATION_SEC}"
            )
        if "max_chunk_sec" not in columns:
            cursor.execute(
                f"ALTER TABLE jobs ADD COLUMN max_chunk_sec REAL DEFAULT {MAX_CHUNK_DURATION_SEC}"
            )
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
        """)
        # Runtime settings key-value store (e.g. MODEL_LOAD_MODE). Seeded from
        # env defaults on first boot only; afterwards the DB is the source of
        # truth and can be changed at runtime via the dashboard / API.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            ("MODEL_LOAD_MODE", MODEL_LOAD_MODE_DEFAULT),
        )
        cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            ("MODEL_IDLE_TIMEOUT_SEC", str(MODEL_IDLE_TIMEOUT_SEC_DEFAULT)),
        )
        # Video compressor jobs (FFmpeg queue). Kept separate from the
        # transcription `jobs` table because the columns differ.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS compress_jobs (
                job_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                input_path TEXT,
                file_size_bytes INTEGER DEFAULT 0,
                status TEXT NOT NULL,
                progress_pct REAL DEFAULT 0.0,
                current_stage TEXT DEFAULT '',
                target_width INTEGER DEFAULT 0,
                bitrate_kbps INTEGER DEFAULT 0,
                crf INTEGER DEFAULT 28,
                preset TEXT DEFAULT 'medium',
                encoder TEXT DEFAULT 'libx264',
                trim_start REAL DEFAULT 0.0,
                trim_end REAL DEFAULT 0.0,
                input_width INTEGER DEFAULT 0,
                input_height INTEGER DEFAULT 0,
                duration_seconds REAL DEFAULT 0.0,
                output_path TEXT,
                output_size_bytes INTEGER DEFAULT 0,
                output_width INTEGER DEFAULT 0,
                output_height INTEGER DEFAULT 0,
                elapsed_seconds REAL DEFAULT 0.0,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_compress_jobs_created_at ON compress_jobs(created_at);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_compress_jobs_status ON compress_jobs(status);
        """)
        compress_columns = [
            r["name"] for r in cursor.execute("PRAGMA table_info(compress_jobs)").fetchall()
        ]
        if "input_path" not in compress_columns:
            cursor.execute("ALTER TABLE compress_jobs ADD COLUMN input_path TEXT")
        if "trim_start" not in compress_columns:
            cursor.execute("ALTER TABLE compress_jobs ADD COLUMN trim_start REAL DEFAULT 0.0")
        if "trim_end" not in compress_columns:
            cursor.execute("ALTER TABLE compress_jobs ADD COLUMN trim_end REAL DEFAULT 0.0")
        if "audio_extract_format" not in compress_columns:
            cursor.execute("ALTER TABLE compress_jobs ADD COLUMN audio_extract_format TEXT DEFAULT ''")
        if "audio_extract_path" not in compress_columns:
            cursor.execute("ALTER TABLE compress_jobs ADD COLUMN audio_extract_path TEXT")
        if "audio_extract_size_bytes" not in compress_columns:
            cursor.execute("ALTER TABLE compress_jobs ADD COLUMN audio_extract_size_bytes INTEGER DEFAULT 0")
        conn.commit()
    logger.info(f"SQLite DB initialized at {JOBS_DB_PATH}")


def create_job(
    job_id: str,
    filename: str,
    file_size_bytes: int = 0,
    language: str = "th",
    target_chunk_sec: float = TARGET_CHUNK_DURATION_SEC,
    max_chunk_sec: float = MAX_CHUNK_DURATION_SEC,
) -> Dict[str, Any]:
    """
    Insert a new job record in SQLite with status='queued'.
    """
    now = datetime.utcnow().isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO jobs (
                job_id, filename, file_size_bytes, language, status, progress_pct,
                current_stage, target_chunk_sec, max_chunk_sec, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'queued', 0.0, 'File Uploaded', ?, ?, ?, ?)
        """,
            (job_id, filename, file_size_bytes, language, target_chunk_sec, max_chunk_sec, now, now),
        )
        conn.commit()
    return get_job(job_id)


def update_job_status(
    job_id: str,
    status: Optional[str] = None,
    progress_pct: Optional[float] = None,
    current_stage: Optional[str] = None,
    completed_chunks: Optional[int] = None,
    total_chunks: Optional[int] = None,
    duration_seconds: Optional[float] = None,
    elapsed_seconds: Optional[float] = None,
    result_text: Optional[str] = None,
    timestamps_json: Optional[str] = None,
    srt_text: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """
    Dynamically update job fields in SQLite.
    """
    fields = []
    values = []

    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if progress_pct is not None:
        fields.append("progress_pct = ?")
        values.append(round(progress_pct, 2))
    if current_stage is not None:
        fields.append("current_stage = ?")
        values.append(current_stage)
    if completed_chunks is not None:
        fields.append("completed_chunks = ?")
        values.append(completed_chunks)
    if total_chunks is not None:
        fields.append("total_chunks = ?")
        values.append(total_chunks)
    if duration_seconds is not None:
        fields.append("duration_seconds = ?")
        values.append(round(duration_seconds, 2))
    if elapsed_seconds is not None:
        fields.append("elapsed_seconds = ?")
        values.append(round(elapsed_seconds, 3))
    if result_text is not None:
        fields.append("result_text = ?")
        values.append(result_text)
    if timestamps_json is not None:
        fields.append("timestamps_json = ?")
        values.append(timestamps_json)
    if srt_text is not None:
        fields.append("srt_text = ?")
        values.append(srt_text)
    if error_message is not None:
        fields.append("error_message = ?")
        values.append(error_message)

    if not fields:
        return

    fields.append("updated_at = ?")
    values.append(datetime.utcnow().isoformat())
    values.append(job_id)

    query = f"UPDATE jobs SET {', '.join(fields)} WHERE job_id = ?"
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, values)
        conn.commit()


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a job record by job_id.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            return None
        res = dict(row)
        if res.get("timestamps_json"):
            try:
                res["timestamps"] = json.loads(res["timestamps_json"])
            except Exception:
                res["timestamps"] = None
        return res


def list_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    """
    List recent jobs ordered by created_at DESC.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def delete_job(job_id: str) -> bool:
    """
    Delete a job record from SQLite.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
        conn.commit()
        return cursor.rowcount > 0


def cleanup_expired_jobs(hours: int = CLEANUP_RETENTION_HOURS) -> List[str]:
    """
    Clean up jobs older than specified hours.

    - Completed jobs: KEEP the DB record (transcription history must be viewable later),
      but return their job_id so leftover files/directories can be removed.
    - Non-completed jobs (failed / stuck processing): DELETE the record and return the job_id.

    Returns list of job_ids whose on-disk job directories should be cleaned up.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT job_id, status FROM jobs
            WHERE created_at < datetime('now', '-' || ? || ' hours')
        """,
            (hours,),
        )
        rows = cursor.fetchall()

        expired_ids = [r["job_id"] for r in rows]
        non_completed_ids = [r["job_id"] for r in rows if r["status"] != "completed"]

        if non_completed_ids:
            placeholders = ",".join("?" * len(non_completed_ids))
            cursor.execute(
                f"DELETE FROM jobs WHERE job_id IN ({placeholders})", non_completed_ids
            )
            conn.commit()
            logger.info(
                f"Cleaned up {len(non_completed_ids)} non-completed expired jobs "
                f"(older than {hours}h); kept {len(expired_ids) - len(non_completed_ids)} completed record(s)"
            )

        return expired_ids


def recover_zombie_jobs() -> int:
    """
    On app startup, scan for jobs interrupted mid-processing and mark them as failed.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE jobs 
            SET status = 'failed',
                error_message = 'Server restarted or crash occurred during processing',
                updated_at = CURRENT_TIMESTAMP
            WHERE status IN ('queued', 'extracting', 'chunking', 'transcribing');
        """)
        recovered_count = cursor.rowcount
        conn.commit()
        if recovered_count > 0:
            logger.warning(
                f"Recovered {recovered_count} zombie jobs stuck in processing state"
            )
        return recovered_count


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    Read a runtime setting from the `settings` table. Falls back to the
    provided default (typically the env-derived default) if the key is absent.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row:
            return row["value"]
    return default


def set_setting(key: str, value: str) -> None:
    """
    Upsert a runtime setting into the `settings` table.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """,
            (key, value),
        )
        conn.commit()


def get_all_settings() -> Dict[str, str]:
    """
    Return all runtime settings as a dict.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in cursor.fetchall()}

# =========================================================================
# Video Compressor jobs (FFmpeg queue)
# =========================================================================


def create_compress_job(
    job_id: str,
    filename: str,
    input_path: str,
    file_size_bytes: int = 0,
    target_width: int = 0,
    bitrate_kbps: int = 0,
    crf: int = COMPRESS_CRF,
    preset: str = COMPRESS_PRESET,
    encoder: str = COMPRESS_ENCODER,
    trim_start: float = 0.0,
    trim_end: float = 0.0,
    audio_extract_format: str = "",
) -> Dict[str, Any]:
    """
    Insert a new video compressor job with status='queued'.
    trim_start / trim_end are seconds; 0.0 = no trimming.
    audio_extract_format: '' = none, 'wav', 'mp3'.
    """
    now = datetime.utcnow().isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO compress_jobs (
                job_id, filename, input_path, file_size_bytes, status, progress_pct,
                current_stage, target_width, bitrate_kbps, crf, preset, encoder,
                trim_start, trim_end, audio_extract_format, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'queued', 0.0, 'Waiting in queue', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                job_id, filename, input_path, file_size_bytes, target_width, bitrate_kbps,
                crf, preset, encoder, trim_start, trim_end, audio_extract_format, now, now,
            ),
        )
        conn.commit()
    return get_compress_job(job_id)


def update_compress_job(
    job_id: str,
    status: Optional[str] = None,
    progress_pct: Optional[float] = None,
    current_stage: Optional[str] = None,
    input_width: Optional[int] = None,
    input_height: Optional[int] = None,
    duration_seconds: Optional[float] = None,
    output_path: Optional[str] = None,
    output_size_bytes: Optional[int] = None,
    output_width: Optional[int] = None,
    output_height: Optional[int] = None,
    elapsed_seconds: Optional[float] = None,
    error_message: Optional[str] = None,
    encoder: Optional[str] = None,
    audio_extract_path: Optional[str] = None,
    audio_extract_size_bytes: Optional[int] = None,
) -> None:
    """
    Dynamically update video compressor job fields in SQLite.
    """
    fields = []
    values = []

    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if progress_pct is not None:
        fields.append("progress_pct = ?")
        values.append(round(progress_pct, 2))
    if current_stage is not None:
        fields.append("current_stage = ?")
        values.append(current_stage)
    if input_width is not None:
        fields.append("input_width = ?")
        values.append(input_width)
    if input_height is not None:
        fields.append("input_height = ?")
        values.append(input_height)
    if duration_seconds is not None:
        fields.append("duration_seconds = ?")
        values.append(round(duration_seconds, 2))
    if output_path is not None:
        fields.append("output_path = ?")
        values.append(output_path)
    if output_size_bytes is not None:
        fields.append("output_size_bytes = ?")
        values.append(output_size_bytes)
    if output_width is not None:
        fields.append("output_width = ?")
        values.append(output_width)
    if output_height is not None:
        fields.append("output_height = ?")
        values.append(output_height)
    if elapsed_seconds is not None:
        fields.append("elapsed_seconds = ?")
        values.append(round(elapsed_seconds, 3))
    if error_message is not None:
        fields.append("error_message = ?")
        values.append(error_message)
    if encoder is not None:
        fields.append("encoder = ?")
        values.append(encoder)
    if audio_extract_path is not None:
        fields.append("audio_extract_path = ?")
        values.append(audio_extract_path)
    if audio_extract_size_bytes is not None:
        fields.append("audio_extract_size_bytes = ?")
        values.append(audio_extract_size_bytes)

    if not fields:
        return

    fields.append("updated_at = ?")
    values.append(datetime.utcnow().isoformat())
    values.append(job_id)

    query = f"UPDATE compress_jobs SET {', '.join(fields)} WHERE job_id = ?"
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, values)
        conn.commit()


def get_compress_job(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a video compressor job record by job_id.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM compress_jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def list_compress_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    """
    List recent video compressor jobs ordered by created_at DESC.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM compress_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in cursor.fetchall()]


def delete_compress_job(job_id: str) -> bool:
    """
    Delete a video compressor job record from SQLite.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM compress_jobs WHERE job_id = ?", (job_id,))
        conn.commit()
        return cursor.rowcount > 0


def get_next_queued_compress_job() -> Optional[Dict[str, Any]]:
    """
    FIFO pick: the oldest job still waiting in the queue. The queue dispatcher
    uses this to guarantee only COMPRESS_MAX_CONCURRENT jobs run at once.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM compress_jobs WHERE status = 'queued' "
            "ORDER BY created_at ASC, rowid ASC LIMIT 1"
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def count_queued_compress_jobs() -> int:
    """
    Number of jobs currently waiting in the queue (status='queued').
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS c FROM compress_jobs WHERE status = 'queued'"
        )
        row = cursor.fetchone()
        return int(row["c"]) if row else 0


def compress_job_queue_info(job_id: str) -> Dict[str, int]:
    """
    Return queue position (1-based) and total queue length for a job.
    A job that is already processing has position 0 (not waiting).
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS c FROM compress_jobs "
            "WHERE status = 'queued' AND created_at < "
            "(SELECT created_at FROM compress_jobs WHERE job_id = ?)",
            (job_id,),
        )
        row = cursor.fetchone()
        position = int(row["c"]) + 1 if row else 1
        cursor.execute(
            "SELECT COUNT(*) AS c FROM compress_jobs WHERE status = 'queued'"
        )
        total = cursor.fetchone()
        queue_length = int(total["c"]) if total else 0
    return {"queue_position": position, "queue_length": queue_length}


def recover_zombie_compress_jobs() -> List[str]:
    """
    On app startup, scan for video compressor jobs interrupted mid-processing
    (crashed worker, server restart) and mark them as failed. Returns the list
    of recovered job_ids whose leftover on-disk job directories (which may still
    contain a large input file) should be deleted by the caller.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT job_id FROM compress_jobs WHERE status IN ('queued', 'processing')"
        )
        recovered_ids = [r["job_id"] for r in cursor.fetchall()]
        if recovered_ids:
            placeholders = ",".join("?" * len(recovered_ids))
            cursor.execute(
                f"""
                UPDATE compress_jobs
                SET status = 'failed',
                    error_message = 'Server restarted or crash occurred during compression',
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id IN ({placeholders})
                """,
                recovered_ids,
            )
            conn.commit()
            logger.warning(
                f"Recovered {len(recovered_ids)} zombie video compressor jobs "
                "stuck in queued/processing state"
            )
        return recovered_ids


def cleanup_expired_compress_jobs(hours: float = COMPRESS_RETENTION_HOURS) -> List[str]:
    """
    Clean up video compressor jobs older than the retention window.

    - Completed jobs: KEEP the DB record (history), but return their job_id so
      the caller can delete the on-disk compressed output file (the record's
      output_path becomes stale and downloads 404).
    - Non-completed jobs (failed / stuck): DELETE the record and return the id.

    Returns list of job_ids whose on-disk job directories should be removed.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT job_id, status FROM compress_jobs
            WHERE created_at < datetime('now', '-' || ? || ' hours')
        """,
            (float(hours),),
        )
        rows = cursor.fetchall()

        expired_ids = [r["job_id"] for r in rows]
        non_completed_ids = [r["job_id"] for r in rows if r["status"] != "completed"]

        if non_completed_ids:
            placeholders = ",".join("?" * len(non_completed_ids))
            cursor.execute(
                f"DELETE FROM compress_jobs WHERE job_id IN ({placeholders})",
                non_completed_ids,
            )
            conn.commit()
            logger.info(
                f"Cleaned up {len(non_completed_ids)} non-completed expired "
                f"video compressor jobs (older than {hours}h); kept "
                f"{len(expired_ids) - len(non_completed_ids)} completed record(s)"
            )

    # Record whenever the retention policy actually cleared files, so the
    # dashboard can show when the last automatic cleanup ran and how many
    # on-disk job directories (input/output) were removed. The timestamp is
    # stored as a JS-friendly UTC string (ISO 8601 with 'Z' suffix).
    if expired_ids:
        now_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        set_setting("COMPRESS_LAST_CLEANUP_AT", now_utc)
        set_setting("COMPRESS_LAST_CLEANUP_COUNT", str(len(expired_ids)))

    return expired_ids
