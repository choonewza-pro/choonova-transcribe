"""
FFmpeg Audio Processing Adapter implementing MediaProcessorPort.
"""

from typing import List
from app.modules.transcription.domain.entities import JobChunk
from app.modules.transcription.domain.ports import MediaProcessorPort
from app.audio_utils import extract_audio_from_media, split_audio_into_chunks, get_media_duration


class FFmpegAudioAdapter(MediaProcessorPort):
    """FFmpeg audio extraction and chunking outbound adapter."""

    def extract_and_chunk_audio(self, media_path: str, target_chunk_sec: float = 30.0) -> List[JobChunk]:
        temp_wav = extract_audio_from_media(media_path)
        chunks_info = split_audio_into_chunks(temp_wav, chunk_duration_sec=target_chunk_sec)
        
        domain_chunks = []
        for idx, (chunk_path, duration) in enumerate(chunks_info):
            domain_chunks.append(JobChunk(
                chunk_index=idx,
                audio_path=chunk_path,
                duration_seconds=duration,
                status="pending",
            ))
        return domain_chunks

    def get_duration(self, media_path: str) -> float:
        return get_media_duration(media_path)
