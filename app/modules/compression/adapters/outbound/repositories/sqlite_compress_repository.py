"""
SQLite implementation of CompressionRepositoryPort.
Maps between CompressionJob domain entities and the compress_jobs table.
"""

from typing import Optional, List, Dict, Any
from app.core.db import get_db_connection
from app.modules.compression.domain.entities import CompressionJob
from app.modules.compression.domain.ports import CompressionRepositoryPort


def _row_to_job(r) -> CompressionJob:
    """Convert a SQLite Row (dict-like) into a CompressionJob domain entity."""
    d = dict(r)
    return CompressionJob(
        job_id=d["job_id"],
        filename=d["filename"],
        input_path=d.get("input_path") or "",
        file_size_bytes=d.get("file_size_bytes") or 0,
        status=d["status"],
        target_width=d.get("target_width") or 0,
        bitrate_kbps=d.get("bitrate_kbps") or 0,
        crf=d.get("crf") or 28,
        preset=d.get("preset") or "medium",
        encoder=d.get("encoder") or "libx264",
        trim_start=d.get("trim_start") or 0.0,
        trim_end=d.get("trim_end") or 0.0,
        audio_extract_format=d.get("audio_extract_format") or "",
        progress_pct=d.get("progress_pct") or 0.0,
        current_stage=d.get("current_stage") or "queued",
        duration_seconds=d.get("duration_seconds") or 0.0,
        elapsed_seconds=d.get("elapsed_seconds") or 0.0,
        input_width=d.get("input_width"),
        input_height=d.get("input_height"),
        output_path=d.get("output_path"),
        output_size_bytes=d.get("output_size_bytes"),
        output_width=d.get("output_width"),
        output_height=d.get("output_height"),
        compression_ratio=d.get("compression_ratio"),
        encoder_used=d.get("encoder_used"),
        audio_extract_path=d.get("audio_extract_path"),
        audio_extract_size_bytes=d.get("audio_extract_size_bytes"),
        error_message=d.get("error_message"),
        created_at=str(d["created_at"]) if d.get("created_at") else None,
        updated_at=str(d["updated_at"]) if d.get("updated_at") else None,
        started_at=str(d["started_at"]) if d.get("started_at") else None,
        completed_at=str(d["completed_at"]) if d.get("completed_at") else None,
        failed_at=str(d["failed_at"]) if d.get("failed_at") else None,
        cancelled_at=str(d["cancelled_at"]) if d.get("cancelled_at") else None,
    )


class SQLiteCompressRepository(CompressionRepositoryPort):
    """SQLite-backed repository for compression jobs, using the shared WAL DB."""

    def create_job(self, job: CompressionJob) -> CompressionJob:
        from datetime import datetime
        now = datetime.utcnow().isoformat()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO compress_jobs (
                    job_id, filename, input_path, file_size_bytes, status, progress_pct,
                    current_stage, target_width, bitrate_kbps, crf, preset, encoder,
                    trim_start, trim_end, audio_extract_format, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id, job.filename, job.input_path, job.file_size_bytes,
                    job.status, job.progress_pct, job.current_stage,
                    job.target_width, job.bitrate_kbps, job.crf, job.preset, job.encoder,
                    job.trim_start, job.trim_end, job.audio_extract_format, now, now,
                ),
            )
            conn.commit()
        return self.get_job(job.job_id)

    def get_job(self, job_id: str) -> Optional[CompressionJob]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM compress_jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                return _row_to_job(row)
        return None

    def update_progress(
        self,
        job_id: str,
        progress_pct: float,
        current_stage: str,
        elapsed_seconds: float,
    ) -> None:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE compress_jobs
                SET progress_pct = ?, current_stage = ?, elapsed_seconds = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                (progress_pct, current_stage, elapsed_seconds, job_id),
            )
            conn.commit()

    def complete_job(
        self,
        job_id: str,
        output_path: str,
        output_size_bytes: int,
        compression_ratio: float,
        encoder_used: str,
        elapsed_seconds: float,
    ) -> None:
        from datetime import datetime
        now = datetime.utcnow().isoformat()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE compress_jobs
                SET status = 'completed', progress_pct = 100.0, current_stage = 'done',
                    output_path = ?, output_size_bytes = ?, compression_ratio = ?,
                    encoder_used = ?, elapsed_seconds = ?,
                    completed_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                (output_path, output_size_bytes, compression_ratio,
                 encoder_used, elapsed_seconds, now, job_id),
            )
            conn.commit()

    def fail_job(self, job_id: str, error_message: str) -> None:
        from datetime import datetime
        now = datetime.utcnow().isoformat()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE compress_jobs
                SET status = 'failed', current_stage = 'failed',
                    error_message = ?, failed_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                (error_message, now, job_id),
            )
            conn.commit()

    def update_job(self, job_id: str, **kwargs) -> None:
        """General-purpose field update. Pass column names as kwargs."""
        if not kwargs:
            return
        from datetime import datetime
        fields = []
        values = []
        allowed = {
            "status", "progress_pct", "current_stage", "input_width", "input_height",
            "duration_seconds", "output_path", "output_size_bytes", "output_width",
            "output_height", "elapsed_seconds", "error_message", "encoder",
            "encoder_used", "audio_extract_path", "audio_extract_size_bytes",
            "started_at", "completed_at", "failed_at", "cancelled_at",
        }
        for k, v in kwargs.items():
            if k in allowed:
                fields.append(f"{k} = ?")
                values.append(v)
        if not fields:
            return
        fields.append("updated_at = ?")
        values.append(datetime.utcnow().isoformat())
        values.append(job_id)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE compress_jobs SET {', '.join(fields)} WHERE job_id = ?",
                values,
            )
            conn.commit()

    def get_queued_jobs(self, limit: int = 10) -> List[CompressionJob]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM compress_jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT ?",
                (limit,),
            )
            return [_row_to_job(r) for r in cursor.fetchall()]

    def list_jobs(self, limit: int = 50, status_filter: Optional[str] = None) -> List[CompressionJob]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if status_filter:
                cursor.execute(
                    "SELECT * FROM compress_jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status_filter, limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM compress_jobs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            return [_row_to_job(r) for r in cursor.fetchall()]

    def delete_job(self, job_id: str) -> bool:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM compress_jobs WHERE job_id = ?", (job_id,))
            conn.commit()
            return cursor.rowcount > 0

    def job_queue_info(self, job_id: str) -> Dict[str, int]:
        """Return queue_position (1-based) and queue_length for a job."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) AS c FROM compress_jobs
                WHERE status = 'queued' AND created_at < (
                    SELECT created_at FROM compress_jobs WHERE job_id = ?
                )
                """,
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

    def count_queued(self) -> int:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) AS c FROM compress_jobs WHERE status = 'queued'"
            )
            row = cursor.fetchone()
            return int(row["c"]) if row else 0

    def get_retention_summary(self) -> Dict[str, Any]:
        from app.core.db import get_db_connection as _conn
        from app.core.config import COMPRESS_RETENTION_HOURS
        # Read last cleanup metadata from settings table
        last_at = None
        last_count = 0
        try:
            with _conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM settings WHERE key = 'COMPRESS_LAST_CLEANUP_AT'")
                row = cursor.fetchone()
                if row:
                    last_at = row["value"]
                cursor.execute("SELECT value FROM settings WHERE key = 'COMPRESS_LAST_CLEANUP_COUNT'")
                row = cursor.fetchone()
                if row:
                    last_count = int(row["value"] or 0)
        except Exception:
            pass
        return {
            "retention_hours": COMPRESS_RETENTION_HOURS,
            "last_cleanup_at": last_at,
            "last_cleanup_count": last_count,
        }
