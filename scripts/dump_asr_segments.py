"""
Diagnostic: dump raw faster-whisper ASR segments + words + diarization turns
for a Thai audio file, so the segment-anchor thresholds in
``group_words_by_turns`` can be calibrated against real VAD boundaries.

Run on the GPU host (the app environment):
    python scripts/dump_asr_segments.py assets/test_2_speaker.mp3 assets/test_3_talk.mp3
    python scripts/dump_asr_segments.py some.mp3 --outdir diagnostics

Writes one JSON per input to <outdir>/<basename>.diagnostic.json and prints a
summary of segment gaps (where VAD did / didn't split) and stretched words.
"""

import argparse
import json
import os
import sys


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _analyze_file(audio_path: str, outdir: str) -> None:
    from app.engine_router import transcribe_file
    from app.pyannote_engine import (
        diarize_audio,
        reconstruct_thai_words,
        group_words_by_turns,
    )
    from app.audio_utils import extract_audio_ffmpeg, get_audio_duration_ffmpeg

    basename = os.path.splitext(os.path.basename(audio_path))[0]
    os.makedirs(outdir, exist_ok=True)
    temp_wav = os.path.join(outdir, f"{basename}.diag_diarization_input.wav")
    extract_audio_ffmpeg(audio_path, temp_wav)

    res = transcribe_file(audio_path=audio_path, language="th", with_timestamps=True)
    raw_segments = res.get("segments", [])
    turns = diarize_audio(temp_wav)

    words = reconstruct_thai_words(raw_segments)
    grouped = group_words_by_turns(words, turns)

    gaps = []
    for i in range(1, len(raw_segments)):
        prev_end = _safe_float(raw_segments[i - 1].get("end"))
        cur_start = _safe_float(raw_segments[i].get("start"))
        gaps.append(round(cur_start - prev_end, 3))

    stretched = [
        {
            "word": str(w.get("word", "")),
            "start": w.get("start"),
            "end": w.get("end"),
            "dur": round(_safe_float(w.get("end")) - _safe_float(w.get("start")), 3),
        }
        for seg in raw_segments
        for w in (seg.get("words") or [])
        if _safe_float(w.get("end")) - _safe_float(w.get("start")) > 1.2
    ]
    stretched.sort(key=lambda x: -x["dur"])

    payload = {
        "file": audio_path,
        "duration_seconds": get_audio_duration_ffmpeg(audio_path),
        "segment_count": len(raw_segments),
        "word_count": len(words),
        "segment_gaps": gaps,
        "segments": [
            {
                "id": seg.get("id"),
                "start": seg.get("start"),
                "end": seg.get("end"),
                "text": seg.get("text", ""),
                "words": [
                    {"word": w.get("word", ""), "start": w.get("start"), "end": w.get("end")}
                    for w in (seg.get("words") or [])
                ],
            }
            for seg in raw_segments
        ],
        "turns": turns,
        "grouped_segments": grouped,
        "stretched_words_gt_1_2s": stretched,
    }

    out_path = os.path.join(outdir, f"{basename}.diagnostic.json")
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)

    gaps_ge_half = [g for g in gaps if g >= 0.5]
    print(f"\n=== {audio_path} ===")
    print(f"  segments: {len(raw_segments)}  words: {len(words)}  turns: {len(turns)}")
    print(f"  segment gaps: {gaps}")
    print(f"  gaps >= 0.5s (candidate speaker boundaries VAD merged): {len(gaps_ge_half)} {gaps_ge_half}")
    print(f"  stretched words >1.2s: {len(stretched)} (top 5: "
          f"{[f'{s['word']}({s['dur']}s)' for s in stretched[:5]]})")
    print(f"  grouped segments from group_words_by_turns: {len(grouped)}")
    for g in grouped[:6]:
        print(f"    {g['speaker']} {g['start']:.3f}-{g['end']:.3f} | {g['text'][:60]}")
    print(f"  wrote {out_path}")

    try:
        os.remove(temp_wav)
    except OSError:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("audio_paths", nargs="+", help="Thai audio files to analyze")
    ap.add_argument("--outdir", default="diagnostics", help="output dir for JSON dumps")
    args = ap.parse_args()

    for path in args.audio_paths:
        if not os.path.exists(path):
            print(f"skip: {path} not found", file=sys.stderr)
            continue
        _analyze_file(path, args.outdir)


if __name__ == "__main__":
    main()