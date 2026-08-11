import os
import re
import shutil
import logging
import subprocess
from typing import List, Tuple, Dict, Any

logger = logging.getLogger("typhoon-asr-audio-utils")

def check_disk_space(target_path: str, required_gb: float = 5.0) -> bool:
    """
    Check if the disk containing target_path has at least required_gb free space.
    """
    try:
        os.makedirs(target_path, exist_ok=True)
        usage = shutil.disk_usage(target_path)
        free_gb = usage.free / (1024 ** 3)
        if free_gb < required_gb:
            logger.warning(f"Low disk space: {free_gb:.2f} GB free, required: {required_gb} GB")
            return False
        return True
    except Exception as e:
        logger.error(f"Error checking disk space: {e}")
        return True

def safe_delete_file(file_path: str) -> bool:
    """
    Safely delete a single file if it exists.
    """
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.debug(f"Deleted file: {file_path}")
            return True
    except Exception as e:
        logger.warning(f"Failed to delete file {file_path}: {e}")
    return False

def safe_delete_dir(dir_path: str) -> bool:
    """
    Safely delete a directory and all its contents if it exists.
    """
    try:
        if dir_path and os.path.exists(dir_path):
            shutil.rmtree(dir_path, ignore_errors=True)
            logger.info(f"Cleaned up directory: {dir_path}")
            return True
    except Exception as e:
        logger.warning(f"Failed to delete directory {dir_path}: {e}")
    return False

def extract_audio_ffmpeg(input_file: str, output_wav: str) -> str:
    """
    Extract audio from video file (MP4, MKV, MOV, etc.) and convert to 16kHz Mono 16-bit PCM WAV.
    """
    os.makedirs(os.path.dirname(output_wav), exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-protocol_whitelist", "file,pipe,crypto",
        "-i", input_file,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_wav
    ]
    logger.info(f"Extracting audio using FFmpeg: {' '.join(cmd)}")
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        logger.error(f"FFmpeg audio extraction failed: {res.stderr}")
        raise RuntimeError(f"FFmpeg audio extraction failed: {res.stderr[:500]}")
    
    if not os.path.exists(output_wav) or os.path.getsize(output_wav) == 0:
        raise RuntimeError("Extracted audio file is empty or missing")
        
    return output_wav

def get_audio_duration_ffmpeg(audio_path: str) -> float:
    """
    Get audio duration in seconds using ffprobe or ffmpeg.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-protocol_whitelist", "file,pipe,crypto",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip())
    except Exception:
        pass

    # Fallback to ffmpeg -i if ffprobe is missing
    cmd_fallback = ["ffmpeg", "-protocol_whitelist", "file,pipe,crypto", "-i", audio_path]
    res_fb = subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", res_fb.stderr)
    if match:
        hours, minutes, seconds = match.groups()
        return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
    
    return 0.0

def detect_silences_ffmpeg(audio_path: str, noise_db: str = "-30dB", min_duration_sec: float = 0.5) -> List[float]:
    """
    Run FFmpeg silencedetect to find mid-points of silences in the audio.
    Returns list of silence midpoint timestamps (in seconds).
    """
    cmd = [
        "ffmpeg", "-protocol_whitelist", "file,pipe,crypto", "-i", audio_path,
        "-af", f"silencedetect=noise={noise_db}:d={min_duration_sec}",
        "-f", "null", "-"
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    silence_starts = []
    silence_ends = []

    for line in res.stderr.splitlines():
        if "silence_start:" in line:
            match = re.search(r"silence_start:\s*([\d\.]+)", line)
            if match:
                silence_starts.append(float(match.group(1)))
        elif "silence_end:" in line:
            match = re.search(r"silence_end:\s*([\d\.]+)", line)
            if match:
                silence_ends.append(float(match.group(1)))

    silence_midpoints = []
    for s_start, s_end in zip(silence_starts, silence_ends):
        silence_midpoints.append((s_start + s_end) / 2.0)

    return silence_midpoints

def split_audio_silence(
    input_wav: str,
    output_dir: str,
    target_chunk_sec: float = 30.0,
    max_chunk_sec: float = 60.0
) -> List[Dict[str, Any]]:
    """
    Split audio into chunks targeting ~30-60 seconds, splitting strictly at silence points.
    If no silence is detected within max_chunk_sec, fallback to hard split with 0.5s overlap.
    
    Returns list of dicts: [{'path': ..., 'start_sec': ..., 'end_sec': ..., 'duration_sec': ...}]
    """
    os.makedirs(output_dir, exist_ok=True)
    total_duration = get_audio_duration_ffmpeg(input_wav)
    if total_duration <= 0.0:
        raise ValueError("Invalid audio duration or unable to read file duration")

    # Single chunk if duration is already less than max_chunk_sec
    if total_duration <= max_chunk_sec:
        chunk_path = os.path.join(output_dir, "chunk_000.wav")
        shutil.copyfile(input_wav, chunk_path)
        return [{
            "path": chunk_path,
            "start_sec": 0.0,
            "end_sec": total_duration,
            "duration_sec": total_duration
        }]

    silences = detect_silences_ffmpeg(input_wav)
    
    cut_points = [0.0]
    current_pos = 0.0
    min_chunk_gap = max(5.0, target_chunk_sec * 0.33)

    while current_pos < total_duration:
        target_pos = current_pos + target_chunk_sec
        max_pos = current_pos + max_chunk_sec

        if max_pos >= total_duration:
            break

        # Find best silence point between current_pos + min_chunk_gap and max_pos
        valid_silences = [s for s in silences if (current_pos + min_chunk_gap) <= s <= max_pos]
        
        if valid_silences:
            # Pick silence closest to target_pos
            best_silence = min(valid_silences, key=lambda s: abs(s - target_pos))
            cut_points.append(best_silence)
            current_pos = best_silence
        else:
            # Fallback: Hard cut at max_pos
            cut_points.append(max_pos)
            current_pos = max_pos

    if cut_points[-1] < total_duration:
        cut_points.append(total_duration)

    chunks = []
    for i in range(len(cut_points) - 1):
        start_sec = cut_points[i]
        end_sec = cut_points[i+1]
        
        # Add 0.5s overlap for hard cuts if start > 0
        actual_start = max(0.0, start_sec - 0.25) if i > 0 else start_sec
        actual_end = end_sec
        dur = actual_end - actual_start

        chunk_path = os.path.join(output_dir, f"chunk_{i:03d}.wav")
        cmd = [
            "ffmpeg", "-y",
            "-protocol_whitelist", "file,pipe,crypto",
            "-ss", f"{actual_start:.3f}",
            "-to", f"{actual_end:.3f}",
            "-i", input_wav,
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            chunk_path
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        chunks.append({
            "index": i,
            "path": chunk_path,
            "start_sec": round(actual_start, 3),
            "end_sec": round(actual_end, 3),
            "duration_sec": round(dur, 3)
        })

    logger.info(f"Split {input_wav} ({total_duration:.2f}s) into {len(chunks)} chunks")
    return chunks
