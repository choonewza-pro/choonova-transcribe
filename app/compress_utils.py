import os
import re
import json
import logging
import subprocess
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("typhoon-asr-compress-utils")

# Map common libx264 presets to the NVENC p1..p7 scale. NVENC uses different
# preset names (p1 = slowest/highest quality ... p7 = fastest/smallest).
NVENC_PRESET_MAP = {
    "veryslow": "p1",
    "slower": "p2",
    "slow": "p2",
    "medium": "p4",
    "fast": "p5",
    "faster": "p5",
    "veryfast": "p6",
    "ultrafast": "p7",
    "superfast": "p6",
}
NVENC_PRESET_VALID = [f"p{i}" for i in range(1, 8)]
X264_PRESET_VALID = (
    "ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow",
    "slower", "veryslow",
)

# Substrings in ffmpeg stderr that indicate NVENC is unusable at runtime even
# though the binary may list h264_nvenc (e.g. the driver lib libnvidia-encode.so.1
# is not loadable in the container, or the driver is too old). These are used by
# both the availability probe and the worker's runtime fallback.
NVENC_FAILURE_MARKERS: Tuple[str, ...] = (
    "cannot load libnvidia-encode",
    "minimum required nvidia driver",
    "operation not permitted",
)


def is_nvenc_available() -> bool:
    """
    Check that h264_nvenc is not just compiled in, but actually usable at
    runtime. Listing the encoder via '-encoders' is not enough: a container may
    ship an ffmpeg build with NVENC enabled while the driver library
    (libnvidia-encode.so.1) is never mounted, which only fails at encode time.
    A real tiny encode against a null output catches that case.
    """
    try:
        res = subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner",
                "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=1",
                "-frames:v", "2", "-c:v", "h264_nvenc", "-f", "null", "-",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=30,
        )
        if res.returncode != 0:
            logger.warning(
                f"NVENC availability probe failed: {res.stderr.strip()[-500:]}"
            )
            return False
        return True
    except Exception as e:
        logger.warning(f"Failed to check NVENC availability: {e}")
        return False


def is_nvenc_failure(stderr: str) -> bool:
    """Return True if ffmpeg stderr indicates NVENC is unusable at runtime."""
    if not stderr:
        return False
    lower = stderr.lower()
    return any(marker in lower for marker in NVENC_FAILURE_MARKERS)


def normalize_encoder(encoder: str) -> str:
    """Normalize requested encoder to 'libx264' or 'nvenc', falling back safely."""
    enc = (encoder or "libx264").strip().lower()
    if enc in ("nvenc", "h264_nvenc", "gpu", "nv"):
        return "nvenc" if is_nvenc_available() else "libx264"
    return "libx264"


def normalize_preset(preset: str, encoder: str) -> str:
    """Normalize a preset name for the target encoder."""
    preset = (preset or "medium").strip().lower()
    if encoder == "nvenc":
        if preset in NVENC_PRESET_VALID:
            return preset
        return NVENC_PRESET_MAP.get(preset, "p4")
    if preset not in X264_PRESET_VALID:
        return "medium"
    return preset


def probe_video(input_path: str) -> Dict[str, Any]:
    """
    Probe a media file with ffprobe and return:
    {width, height, duration_seconds, has_audio, codec_name}
    Returns zero defaults (never raises) so the worker can degrade gracefully.
    """
    result = {
        "width": 0,
        "height": 0,
        "duration_seconds": 0.0,
        "has_audio": False,
        "video_codec": "",
    }
    cmd = [
        "ffprobe", "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        input_path,
    ]
    try:
        res = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60
        )
        if res.returncode != 0:
            logger.warning(f"ffprobe failed for {input_path}: {res.stderr[:300]}")
            return result
        data = json.loads(res.stdout or "{}")
    except Exception as e:
        logger.warning(f"ffprobe error for {input_path}: {e}")
        return result

    fmt = data.get("format", {})
    try:
        result["duration_seconds"] = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        result["duration_seconds"] = 0.0

    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and result["width"] == 0:
            try:
                result["width"] = int(stream.get("width") or 0)
                result["height"] = int(stream.get("height") or 0)
            except (TypeError, ValueError):
                pass
            result["video_codec"] = stream.get("codec_name", "")
            # Stream-level duration is more reliable than format for some files.
            try:
                sdur = float(stream.get("duration") or 0.0)
                if sdur > result["duration_seconds"]:
                    result["duration_seconds"] = sdur
            except (TypeError, ValueError):
                pass
        elif stream.get("codec_type") == "audio":
            result["has_audio"] = True

    return result


def _target_width(original_width: int, requested: int) -> Optional[int]:
    """Clamp requested width to the original so we never upscale."""
    if not requested or requested <= 0:
        return None
    if original_width and original_width > 0 and requested > original_width:
        return original_width
    return requested


def parse_trim_time(value: str) -> float:
    """
    Parse a user-supplied trim time into seconds (float).

    Accepts 'SS', 'SS.xxx', 'MM:SS', 'MM:SS.xxx', 'HH:MM:SS' or
    'HH:MM:SS.xxx'. An empty/whitespace-only value returns 0.0 (= no trim).
    Raises ValueError for any malformed input.
    """
    s = (value or "").strip()
    if not s:
        return 0.0
    parts = s.split(":")
    if len(parts) > 3:
        raise ValueError(
            f"invalid trim time '{value}' (use SS, MM:SS or HH:MM:SS)"
        )
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        raise ValueError(
            f"invalid trim time '{value}' (use SS, MM:SS or HH:MM:SS)"
        )
    if any(n < 0 for n in nums):
        raise ValueError(f"invalid trim time '{value}' (must be >= 0)")
    total = 0.0
    for n in nums:
        total = total * 60.0 + n
    return total


def build_compress_cmd(
    input_path: str,
    output_path: str,
    target_width: int = 0,
    bitrate_kbps: int = 0,
    crf: int = 28,
    preset: str = "medium",
    encoder: str = "libx264",
    probe: Optional[Dict[str, Any]] = None,
    trim_start: float = 0.0,
    trim_end: float = 0.0,
) -> List[str]:
    """
    Build an ffmpeg command that compresses a video.

    - target_width > 0 -> scale to that width preserving aspect ratio (clamped
      to the original width to prevent upscaling). '-2' keeps the height even
      (required by H.264) while maintaining the ratio.
    - bitrate_kbps > 0 -> constrained video bitrate (overrides CRF quality).
    - crf -> quality control for the encoder (CRF for x264, CQ for NVENC).
    - encoder -> 'libx264' or 'nvenc'; picks the correct flag set/preset map.
    - probe -> optional result of probe_video(); used to detect missing audio
      (-> '-an') and to clamp the target width.
    - trim_start / trim_end -> seconds (float). trim_start > 0 adds a fast,
      frame-accurate '-ss' seek before the input; trim_end > 0 adds '-to' as an
      input option too so it is measured on the input timeline (yielding the
      [trim_start, trim_end] segment exactly). Both default to 0 = no trimming.
    """
    probe = probe or {}
    original_width = int(probe.get("width") or 0)
    has_audio = bool(probe.get("has_audio"))

    cmd = ["ffmpeg", "-y", "-hide_banner"]
    cmd += ["-protocol_whitelist", "file,pipe,crypto"]
    if trim_start > 0:
        cmd += ["-ss", str(trim_start)]
    if trim_end > 0:
        cmd += ["-to", str(trim_end)]
    cmd += ["-i", input_path]
    cmd += ["-progress", "pipe:1", "-nostats"]

    width = _target_width(original_width, int(target_width or 0))
    if width is not None:
        cmd += ["-vf", f"scale={width}:-2"]

    # Encoder-specific option sets.
    if encoder == "nvenc":
        nv_preset = normalize_preset(preset, "nvenc")
        cmd += ["-c:v", "h264_nvenc", "-preset", nv_preset]
        if bitrate_kbps and bitrate_kbps > 0:
            br = f"{bitrate_kbps}k"
            cmd += ["-b:v", br, "-maxrate", br, "-bufsize", f"{bitrate_kbps * 2}k"]
        else:
            cmd += ["-cq", str(int(crf or 28))]
        # NVENC is greedy with parallelism; a single worker keeps encode stable.
        cmd += ["-rc", "vbr" if bitrate_kbps and bitrate_kbps > 0 else "constqp"]
    else:
        cmd += ["-c:v", "libx264", "-preset", normalize_preset(preset, "libx264")]
        if bitrate_kbps and bitrate_kbps > 0:
            br = f"{bitrate_kbps}k"
            cmd += ["-b:v", br, "-maxrate", br, "-bufsize", f"{bitrate_kbps * 2}k"]
        else:
            cmd += ["-crf", str(int(crf or 28))]

    # Audio: re-encode to AAC 128k; if the source has no audio stream, drop it.
    if has_audio:
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-an"]

    cmd += ["-movflags", "+faststart", output_path]
    return cmd


def parse_progress_line(line: str) -> Tuple[Optional[float], bool]:
    """
    Parse a single '-progress pipe:1' key=value line.
    Returns (out_time_seconds, is_end). out_time may be None.
    """
    line = line.strip()
    if not line:
        return None, False
    if line == "progress=end":
        return None, True
    if line.startswith("out_time_us="):
        try:
            return int(line.split("=", 1)[1]) / 1_000_000.0, False
        except (ValueError, IndexError):
            return None, False
    if line.startswith("out_time_ms="):
        try:
            return int(line.split("=", 1)[1]) / 1_000_000.0, False
        except (ValueError, IndexError):
            return None, False
    if line.startswith("out_time="):
        # fallback: HH:MM:SS.microseconds
        m = re.search(r"out_time=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
        if m:
            try:
                h, mn, s = m.groups()
                return int(h) * 3600 + int(mn) * 60 + float(s), False
            except ValueError:
                return None, False
    return None, False


def format_bytes(num: float) -> str:
    """Human-readable byte size for logs/UI stats."""
    try:
        num = float(num or 0)
    except (TypeError, ValueError):
        num = 0.0
    if num <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.2f} {unit}"
        num /= 1024
    return f"{num:.2f} TB"


def build_audio_extract_cmd(
    input_path: str,
    output_path: str,
    format: str = "wav",
) -> List[str]:
    """
    Build an ffmpeg command that extracts audio from a video file.
    format: 'wav' (16kHz mono PCM) or 'mp3' (192kbps stereo).
    """
    cmd = ["ffmpeg", "-y", "-hide_banner", "-protocol_whitelist", "file,pipe,crypto", "-i", input_path, "-vn"]
    if format == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", "192k"]
    else:
        cmd += ["-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1"]
    cmd += [output_path]
    return cmd
