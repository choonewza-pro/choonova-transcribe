"""
Unit tests for the engine_router Thai timestamp post-processing.

faster-whisper emits character-level word tokens for Thai; the router must
rebuild them into whole words so inline / job-worker / OpenAI paths all get
word-level timestamps without diarization.
"""

import unittest

try:
    from app import engine_router
except ImportError as e:
    # engine_router pulls in app.asr_engine -> librosa (GPU-only dep),
    # absent in CPU/CI environments. Skip rather than hard-fail.
    engine_router = None
    _IMPORT_ERROR = e


def _engine_router():
    if engine_router is None:
        raise unittest.SkipTest(f"engine_router unavailable (missing GPU dep): {_IMPORT_ERROR}")
    return engine_router


class FakeWhisperThaiEngine:
    """Stand-in for whisper_thai_engine that returns char-level tokens."""

    def transcribe_file(self, audio_path, language="th", with_timestamps=False):
        return {
            "text": "คุณชมนี เป็นอะไร",
            "elapsed": 0.0,
            "duration": 2.0,
            "language": "th",
            "timestamps": [
                {"word": "ค", "start": 0.0, "end": 0.1},
                {"word": "ุ", "start": 0.1, "end": 0.2},
                {"word": "ณ", "start": 0.2, "end": 0.3},
                {"word": "ช", "start": 0.3, "end": 0.4},
                {"word": "ม", "start": 0.4, "end": 0.5},
                {"word": "นี", "start": 0.5, "end": 0.7},
                {"word": "เป็น", "start": 0.8, "end": 1.2},
                {"word": "อะไร", "start": 1.3, "end": 1.8},
            ],
            "segments": [
                {
                    "text": "คุณชมนี เป็นอะไร",
                    "start": 0.0,
                    "end": 1.8,
                    "words": [
                        {"word": "ค", "start": 0.0, "end": 0.1},
                        {"word": "ุ", "start": 0.1, "end": 0.2},
                        {"word": "ณ", "start": 0.2, "end": 0.3},
                        {"word": "ช", "start": 0.3, "end": 0.4},
                        {"word": "ม", "start": 0.4, "end": 0.5},
                        {"word": "นี", "start": 0.5, "end": 0.7},
                        {"word": "เป็น", "start": 0.8, "end": 1.2},
                        {"word": "อะไร", "start": 1.3, "end": 1.8},
                    ],
                }
            ],
        }

    def transcribe_bytes(self, audio_bytes, filename_hint="audio.wav", language="th", with_timestamps=False):
        return self.transcribe_file(filename_hint, language, with_timestamps)


class TestEngineRouterThaiTimestamps(unittest.TestCase):

    def test_transcribe_file_rebuilds_word_level_timestamps(self):
        router = _engine_router()
        fake = FakeWhisperThaiEngine()
        original = router.whisper_thai_engine
        router.whisper_thai_engine = fake
        try:
            res = router.transcribe_file(
                audio_path="fake.wav",
                language="th",
                with_timestamps=True,
            )
        finally:
            router.whisper_thai_engine = original

        self.assertEqual(res["model"], "thai-whisper")
        words = [t["word"] for t in res["timestamps"]]
        self.assertNotIn("ค", words)
        self.assertNotIn("ุ", words)
        joined = "".join(words).replace(" ", "")
        self.assertEqual(joined, "คุณชมนีเป็นอะไร")
        self.assertGreaterEqual(res["timestamps"][0]["start"], 0.0)
        self.assertLessEqual(res["timestamps"][-1]["end"], 1.8)

    def test_transcribe_bytes_rebuilds_word_level_timestamps(self):
        router = _engine_router()
        fake = FakeWhisperThaiEngine()
        original = router.whisper_thai_engine
        router.whisper_thai_engine = fake
        try:
            res = router.transcribe_bytes(
                audio_bytes=b"fake",
                filename_hint="fake.wav",
                language="th",
                with_timestamps=True,
            )
        finally:
            router.whisper_thai_engine = original

        self.assertEqual(res["model"], "thai-whisper")
        words = [t["word"] for t in res["timestamps"]]
        self.assertNotIn("ุ", words)
        self.assertEqual("".join(words).replace(" ", ""), "คุณชมนีเป็นอะไร")

    def test_transcribe_file_without_timestamps_leaves_empty(self):
        router = _engine_router()
        fake = FakeWhisperThaiEngine()
        original = router.whisper_thai_engine
        router.whisper_thai_engine = fake
        try:
            res = router.transcribe_file(
                audio_path="fake.wav",
                language="th",
                with_timestamps=False,
            )
        finally:
            router.whisper_thai_engine = original

        self.assertEqual(res["timestamps"], [])


if __name__ == "__main__":
    unittest.main()