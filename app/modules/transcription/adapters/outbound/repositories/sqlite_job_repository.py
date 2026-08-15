"""
SQLite implementation of JobRepositoryPort for Transcription jobs.
Maps between TranscriptionJob domain entities and the jobs table in SQLite.
"""

import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from app.core.db import get_db_connection
from app.modules.transcription.domain.entities import TranscriptionJob
from app.modules.transcription.domain.ports import JobRepositoryPort


def _row_to_job(r) -> TranscriptionJob:
    """Convert a SQLite Row (dict-like) into a TranscriptionJob domain entity."""
    d = dict(r)
    result = None
    if d.get("result_json"):
        try:
            result = json.loads(d["result_json"])
        except Exception:
            result = {"text": d["result_json"]}

    error = None
    if d.get("error_json"):
        try:
            error = json.loads(d["error_json"])
        except Exception:
            error = {"message": d["error_json"]}

    now_iso = datetime.utcnow().isoformat()
    return TranscriptionJob(
        id=d["id"],
        type=d.get("type") or "transcription",
        filename=d["filename"],
        file_size_bytes=d.get("file_size_bytes") or 0,
        language=d.get("language") or "th",
        model=d.get("model"),
        status=d["status"],
        progress=d.get("progress") or 0.0,
        stage=d.get("stage") or "queued",
        total_chunks=d.get("total_chunks") or 0,
        completed_chunks=d.get("completed_chunks") or 0,
        duration=d.get("duration") or 0.0,
        processing_time=d.get("processing_time") or 0.0,
        target_chunk_sec=d.get("target_chunk_sec") if d.get("target_chunk_sec") is not None else 30.0,
        max_chunk_sec=d.get("max_chunk_sec") if d.get("max_chunk_sec") is not None else 60.0,
        enable_diarization=bool(d.get("enable_diarization")),
        num_speakers=d.get("num_speakers"),
        min_speakers=d.get("min_speakers"),
        max_speakers=d.get("max_speakers"),
        task=d.get("task") or "transcribe",
        result=result,
        error=error,
        created_at=str(d["created_at"]) if d.get("created_at") else now_iso,
        updated_at=str(d["updated_at"]) if d.get("updated_at") else now_iso,
        started_at=str(d["started_at"]) if d.get("started_at") else None,
        completed_at=str(d["completed_at"]) if d.get("completed_at") else None,
    )


class SQLiteJobRepository(JobRepositoryPort):
    """SQLite-backed repository for transcription jobs, using the shared WAL DB."""

    def create_job(self, job: TranscriptionJob) -> TranscriptionJob:
        now = datetime.utcnow().isoformat()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO jobs (
                    id, type, filename, file_size_bytes, language, model, status,
                    progress, stage, total_chunks, completed_chunks,
                    duration, processing_time, target_chunk_sec, max_chunk_sec,
                    enable_diarization, num_speakers, min_speakers, max_speakers,
                    task, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id, job.type, job.filename, job.file_size_bytes, job.language,
                    job.model, job.status, job.progress, job.stage,
                    job.total_chunks, job.completed_chunks,
                    job.duration, job.processing_time,
                    job.target_chunk_sec, job.max_chunk_sec,
                    1 if job.enable_diarization else 0,
                    job.num_speakers,
                    job.min_speakers,
                    job.max_speakers,
                    job.task,
                    now, now,
                ),
            )
            conn.commit()
        return self.get_job(job.id)

    def get_job(self, job_id: str) -> Optional[TranscriptionJob]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                return _row_to_job(row)
        return None

    def update_progress(
        self,
        job_id: str,
        progress_pct: float,
        current_stage: str,
        completed_chunks: int,
        elapsed_seconds: float,
    ) -> None:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET progress = ?, stage = ?, completed_chunks = ?,
                    processing_time = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (progress_pct, current_stage, completed_chunks, elapsed_seconds, job_id),
            )
            conn.commit()

    def complete_job(
        self,
        job_id: str,
        result_text: str,
        timestamps_json: str,
        srt_text: str,
        elapsed_seconds: float,
    ) -> None:
        result_payload = json.dumps({
            "text": result_text,
            "segments": json.loads(timestamps_json) if timestamps_json else [],
            "srt": srt_text,
        })
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'completed', progress = 100.0, stage = 'done',
                    result_json = ?, processing_time = ?, completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (result_payload, elapsed_seconds, job_id),
            )
            conn.commit()

    def fail_job(self, job_id: str, error_message: str) -> None:
        error_payload = json.dumps({"message": error_message})
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'failed', stage = 'failed',
                    error_json = ?, failed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (error_payload, job_id),
            )
            conn.commit()

    def update_status(
        self,
        job_id: str,
        status: str,
        progress: Optional[float] = None,
        stage: Optional[str] = None,
        completed_chunks: Optional[int] = None,
        total_chunks: Optional[int] = None,
        duration: Optional[float] = None,
        processing_time: Optional[float] = None,
        result_json: Optional[str] = None,
        error_json: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        """General-purpose status update matching legacy update_job_status signature."""
        sets = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        params: list = [status]
        if progress is not None:
            sets.append("progress = ?"); params.append(progress)
        if stage is not None:
            sets.append("stage = ?"); params.append(stage)
        if completed_chunks is not None:
            sets.append("completed_chunks = ?"); params.append(completed_chunks)
        if total_chunks is not None:
            sets.append("total_chunks = ?"); params.append(total_chunks)
        if duration is not None:
            sets.append("duration = ?"); params.append(duration)
        if processing_time is not None:
            sets.append("processing_time = ?"); params.append(processing_time)
        if result_json is not None:
            sets.append("result_json = ?"); params.append(result_json)
        if error_json is not None:
            sets.append("error_json = ?"); params.append(error_json)
        if model is not None:
            sets.append("model = ?"); params.append(model)
        params.append(job_id)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", params
            )
            conn.commit()

    def list_jobs(
        self,
        limit: int = 50,
        offset: int = 0,
        status_filter: Optional[str] = None,
    ) -> List[TranscriptionJob]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if status_filter:
                cursor.execute(
                    "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (status_filter, limit, offset),
                )
            else:
                cursor.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            return [_row_to_job(r) for r in cursor.fetchall()]

    def delete_job(self, job_id: str) -> bool:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.commit()
            return cursor.rowcount > 0

    def job_queue_info(self, job_id: str) -> Dict[str, int]:
        """Return queue_position and queue_length for a given job."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = 'queued'",
            )
            queue_length = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT COUNT(*) FROM jobs
                WHERE status = 'queued' AND created_at <= (
                    SELECT created_at FROM jobs WHERE id = ?
                )
                """,
                (job_id,),
            )
            queue_position = cursor.fetchone()[0]
        return {"queue_position": queue_position, "queue_length": queue_length}

    def count_queued(self) -> int:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'queued'")
            return cursor.fetchone()[0]

    def get_retention_summary(self) -> Dict[str, Any]:
        """Return retention configuration for the transcription dashboard."""
        from app.core.config import TRANSCRIBE_RETENTION_HOURS
        return {"retention_hours": TRANSCRIBE_RETENTION_HOURS}
