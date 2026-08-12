"""
FFmpeg Audio Processing Adapter implementing MediaProcessorPort.
Wraps legacy app.audio_utils functions under domain port interface.
"""

from typing import List
from app.modules.transcription.domain.entities import JobChunk
from app.modules.transcription.domain.ports import MediaProcessorPort
from app.audio_utils import (
    extract_audio_ffmpeg,
    split_audio_silence,
    get_audio_duration_ffmpeg,
    check_disk_space as _check_disk_space,
    safe_delete_dir as _safe_delete_dir,
)
from app.core.media_validator import ALLOWED_EXTENSIONS


class FFmpegAudioAdapter(MediaProcessorPort):
    """FFmpeg audio extraction and chunking outbound adapter."""

    def extract_and_chunk_audio(self, media_path: str, target_chunk_sec: float = 30.0) -> List[JobChunk]:
        import os, tempfile
        # Extract audio to a temp WAV
        tmp_dir = tempfile.mkdtemp()
        wav_path = os.path.join(tmp_dir, "audio.wav")
        extract_audio_ffmpeg(media_path, wav_path)
        # Split into silence-based chunks
        chunks_info = split_audio_silence(wav_path, tmp_dir, target_chunk_sec=target_chunk_sec)
        domain_chunks = []
        for idx, chunk_info in enumerate(chunks_info):
            chunk_path = chunk_info.get("path") or chunk_info.get("audio_path") or chunk_info
            duration = chunk_info.get("duration", 0.0) if isinstance(chunk_info, dict) else 0.0
            domain_chunks.append(JobChunk(
                chunk_index=idx,
                audio_path=chunk_path if isinstance(chunk_path, str) else str(chunk_path),
                duration_seconds=duration,
                status="pending",
            ))
        return domain_chunks

    def get_duration(self, media_path: str) -> float:
        return get_audio_duration_ffmpeg(media_path)

    def check_disk_space(self, path: str, required_gb: float = 5.0) -> bool:
        return _check_disk_space(path, required_gb)

    def safe_delete_dir(self, dir_path: str) -> bool:
        return _safe_delete_dir(dir_path)

    @staticmethod
    def is_allowed_file(filename: str) -> bool:
        if not filename or "." not in filename:
            return False
        ext = filename.rsplit(".", 1)[-1].lower()
        return ext in ALLOWED_EXTENSIONS
