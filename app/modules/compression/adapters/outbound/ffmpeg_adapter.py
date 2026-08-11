"""
FFmpeg Video Compression Outbound Adapter implementing MediaCompressorPort.
"""

from typing import Optional
from app.modules.compression.domain.ports import MediaCompressorPort
from app.compress_utils import (
    compress_video as _raw_compress_video,
    is_nvenc_available as _is_nvenc_available,
    probe_media_metadata as _probe_media_metadata,
)


class FFmpegCompressAdapter(MediaCompressorPort):
    """FFmpeg media compression outbound adapter."""

    def is_nvenc_usable(self) -> bool:
        return _is_nvenc_available()

    def get_metadata(self, file_path: str) -> dict:
        return _probe_media_metadata(file_path)

    def compress_video(
        self,
        input_path: str,
        output_path: str,
        target_resolution: Optional[str] = None,
        encoder: str = "libx264",
        preset: str = "medium",
        crf: int = 28,
        progress_callback=None,
    ) -> dict:
        return _raw_compress_video(
            input_path=input_path,
            output_path=output_path,
            target_resolution=target_resolution,
            encoder=encoder,
            preset=preset,
            crf=crf,
            progress_callback=progress_callback,
        )
