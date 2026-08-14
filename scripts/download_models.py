"""
Model pre-download script for ChooNova Transcribe.
Used during Docker build and available for local offline preparation.
"""

import argparse
import os
import sys


def download_typhoon(model_dir: str = "/app/models", token: str | None = None) -> None:
    from huggingface_hub import hf_hub_download

    token = token or os.getenv("HF_TOKEN", "").strip() or None
    os.makedirs(model_dir, exist_ok=True)
    target_file = os.path.join(model_dir, "typhoon-asr-realtime.nemo")
    if os.path.exists(target_file) and os.path.getsize(target_file) > 100 * 1024 * 1024:
        print(f"  ℹ️ Typhoon ASR model already exists at {target_file}")
        return

    p = hf_hub_download(
        repo_id="typhoon-ai/typhoon-asr-realtime",
        filename="typhoon-asr-realtime.nemo",
        local_dir=model_dir,
        token=token,
    )
    size = os.path.getsize(p) / (1024**3)
    print()
    print("=" * 70)
    print("  ✅ MODEL DOWNLOAD COMPLETE — Typhoon ASR Realtime")
    print(f"  📁 {p}")
    print(f"  💾 {size:.2f} GB")
    print("=" * 70)
    print()


def download_whisper(model_name: str = "large-v3-turbo", token: str | None = None) -> None:
    from huggingface_hub import snapshot_download

    token = token or os.getenv("HF_TOKEN", "").strip() or None
    m = model_name or os.getenv("WHISPER_MODEL", "large-v3-turbo")
    repo_id = (
        "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
        if m in ("turbo", "large-v3-turbo")
        else f"Systran/faster-whisper-{m}"
    )
    p = snapshot_download(repo_id=repo_id, token=token)
    print()
    print("=" * 70)
    print("  ✅ WHISPER MODEL DOWNLOAD COMPLETE — " + repo_id)
    print(f"  📁 {p}")
    print("=" * 70)
    print()


def download_pyannote(model_dir: str = "/app/models", token: str | None = None) -> None:
    from huggingface_hub import snapshot_download

    # Check if local models already exist
    seg_file = os.path.join(model_dir, "pyannote", "segmentation-3.0", "pytorch_model.bin")
    emb_file = os.path.join(model_dir, "speechbrain", "spkrec-ecapa-voxceleb", "embedding_model.ckpt")
    if os.path.exists(seg_file) and os.path.exists(emb_file):
        print("  ℹ️ Local PyAnnote & SpeechBrain models already exist in", model_dir)
        return

    token = token or os.getenv("HF_TOKEN", "").strip() or None
    if token:
        try:
            p1 = snapshot_download(repo_id="pyannote/speaker-diarization-3.1", token=token)
            p2 = snapshot_download(repo_id="pyannote/segmentation-3.0", token=token)
            p3 = snapshot_download(repo_id="speechbrain/spkrec-ecapa-voxceleb", token=token)
            print()
            print("=" * 70)
            print("  ✅ PYANNOTE DIARIZATION MODELS DOWNLOAD COMPLETE")
            print(f"  📁 {p1}")
            print(f"  📁 {p2}")
            print(f"  📁 {p3}")
            print("=" * 70)
            print()
        except Exception as e:
            err_msg = str(e)
            print()
            print("=" * 70)
            print(f"  ⚠️ Could not pre-download PyAnnote models during build: {err_msg[:120]}...")
            if "403" in err_msg or "401" in err_msg or "gated" in err_msg.lower():
                print("  💡 HINT: PyAnnote models require accepting user agreements on Hugging Face:")
                print("     1. https://huggingface.co/pyannote/speaker-diarization-3.1")
                print("     2. https://huggingface.co/pyannote/segmentation-3.0")
                print("     (After accepting on Hugging Face, rebuild with docker compose up -d --build)")
            print("=" * 70)
            print()
    else:
        print(
            "  ℹ️ HF_TOKEN not provided at build time; PyAnnote models will load at runtime when HF_TOKEN is configured in .env."
        )


def download_whisperx_align(lang: str = "en") -> None:
    try:
        import whisperx

        whisperx.load_align_model(language_code=lang, device="cpu")
        print()
        print("=" * 70)
        print(f"  ✅ WHISPERX ALIGNMENT MODEL ({lang}) DOWNLOAD COMPLETE")
        print("=" * 70)
        print()
    except Exception as e:
        print(f"  ⚠️ Could not pre-download WhisperX alignment model: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="ChooNova Transcribe model downloader")
    parser.add_argument("--all", action="store_true", help="Download all models")
    parser.add_argument("--typhoon", action="store_true", help="Download Typhoon ASR model")
    parser.add_argument("--whisper", action="store_true", help="Download Whisper model")
    parser.add_argument("--pyannote", action="store_true", help="Download PyAnnote models")
    parser.add_argument(
        "--whisperx-align", action="store_true", help="Download WhisperX alignment model"
    )
    parser.add_argument("--model-dir", default="/app/models", help="Target dir for Typhoon model")
    parser.add_argument(
        "--whisper-model", default="large-v3-turbo", help="Whisper model name/variant"
    )
    parser.add_argument("--hf-token", default="", help="Hugging Face token")
    args = parser.parse_args()

    # If no specific flags given, default to all
    if not any([args.typhoon, args.whisper, args.pyannote, args.whisperx_align, args.all]):
        args.all = True

    token = args.hf_token or os.getenv("HF_TOKEN", "").strip() or None

    if args.typhoon or args.all:
        download_typhoon(model_dir=args.model_dir, token=token)

    if args.whisper or args.all:
        download_whisper(model_name=args.whisper_model, token=token)

    if args.pyannote or args.all:
        download_pyannote(model_dir=args.model_dir, token=token)

    if args.whisperx_align or args.all:
        download_whisperx_align(lang="en")


if __name__ == "__main__":
    main()
