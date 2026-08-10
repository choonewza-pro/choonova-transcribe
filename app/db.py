import os
import sqlite3
import json
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
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            ("MODEL_LOAD_MODE", MODEL_LOAD_MODE_DEFAULT),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            ("MODEL_IDLE_TIMEOUT_SEC", str(MODEL_IDLE_TIMEOUT_SEC_DEFAULT)),
        )
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
