import os
import subprocess
import logging
import filetype
from fastapi import HTTPException
from app.core.config import MAX_MEDIA_DURATION_SEC

logger = logging.getLogger(__name__)

# List of allowed mime types (audio and video)
ALLOWED_MIME_PREFIXES = ("audio/", "video/")
ALLOWED_EXTENSIONS = {
    "wav", "mp3", "m4a", "ogg", "flac", "mp4", "mkv", "mov", "webm", "aac"
}

def _is_isobmff_container(header_bytes: bytes) -> bool:
    """
    Detect an ISO-BMFF (MP4/M4A family) container by scanning for a `ftyp` box.

    `filetype` only recognizes a few `ftyp` brands (M4A / isom / mp42), so
    real-world m4a files from phone recorders / audio tools that use other
    brands (M4B, M4P, M4V, 3gp4, qt, ...) or carry a leading `free`/`wide` box
    before the `ftyp` box would otherwise be rejected at the magic-byte layer
    even though ffprobe (the deep validation layer that runs next) accepts them.
    """
    scan_limit = min(len(header_bytes), 64)
    for offset in range(0, scan_limit - 4, 4):
        if header_bytes[offset:offset + 4] == b"ftyp":
            return True
    return False


def validate_magic_bytes(header_bytes: bytes) -> str:
    """
    Check the magic bytes of the file to ensure it's an audio or video file.
    Returns the mime type if valid, raises HTTPException otherwise.
    """
    kind = filetype.guess(header_bytes)
    if kind is None:
        # Fallback for ISO-BMFF (MP4/M4A) containers that filetype's brand list misses.
        if _is_isobmff_container(header_bytes):
            return "audio/mp4"

        # Fallback for raw MP3 (MPEG Audio Layer I/II/III) or ADTS AAC frame sync headers
        # Frame sync is 11 or 12 set bits: 0xFF followed by top 3 bits set (0xE0)
        if len(header_bytes) >= 2 and header_bytes[0] == 0xFF and (header_bytes[1] & 0xE0) == 0xE0:
            return "audio/mpeg"
            
        raise HTTPException(status_code=422, detail="Cannot determine file type from magic bytes. File may be corrupted or not a valid media file.")
    
    mime = kind.mime
    if not any(mime.startswith(prefix) for prefix in ALLOWED_MIME_PREFIXES):
        raise HTTPException(status_code=422, detail=f"Invalid file type: {mime}. Only audio and video files are allowed.")
    
    return mime

def validate_extension(filename: str):
    """
    Check if the file extension is in the allowed list.
    """
    if not filename:
        raise HTTPException(status_code=400, detail="Filename is missing.")
    
    ext = filename.split(".")[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"Extension '{ext}' is not allowed.")

def validate_with_ffprobe(filepath: str, max_duration_sec: float | None = None):
    """
    Use ffprobe to deeply inspect the media file container.
    This protects against Polyglot files and deeply hidden malicious streams.

    max_duration_sec: optional duration limit override. Defaults to
    MAX_MEDIA_DURATION_SEC (long-form media). Short audio endpoints pass their
    own MAX_AUDIO_DURATION_SEC since they process the file in a single pass.
    """
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found for validation.")

    # -protocol_whitelist file,crypto : Prevent SSRF via HLS playlists
    cmd = [
        "ffprobe",
        "-v", "error",
        "-protocol_whitelist", "file,crypto",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        filepath
    ]
    
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        
        if res.returncode != 0:
            logger.error(f"FFprobe validation failed for {filepath}: {res.stderr}")
            raise HTTPException(status_code=422, detail="File is corrupted or not a valid media container (ffprobe failed).")
            
        duration_str = res.stdout.strip()
        if not duration_str or duration_str == "N/A":
            logger.error(f"FFprobe could not determine duration for {filepath}")
            raise HTTPException(status_code=422, detail="Could not determine media duration. File might be invalid.")
            
        try:
            duration = float(duration_str)
            if duration <= 0:
                raise ValueError()
            max_duration = max_duration_sec if max_duration_sec is not None else MAX_MEDIA_DURATION_SEC
            if max_duration > 0 and duration > max_duration:
                raise HTTPException(
                    status_code=413,
                    detail=f"Media duration ({duration:.1f}s) exceeds maximum allowed ({max_duration:.0f}s)."
                )
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid media duration parsed.")
            
    except subprocess.TimeoutExpired:
        logger.error(f"FFprobe timed out validating {filepath}")
        raise HTTPException(status_code=408, detail="Media validation timed out.")
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        logger.error(f"Error during ffprobe validation: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during file validation.")

def secure_filename(filename: str) -> str:
    """
    Ensure the filename doesn't contain path traversal characters.
    """
    safe_name = os.path.basename(filename)
    if not safe_name or safe_name in (".", ".."):
        return "uploaded_file.tmp"
    return safe_name
