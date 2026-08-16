import unittest
from app.modules.transcription.adapters.inbound.workers.run_inline_transcribe import (
    _strip_word_level,
)


class TestStripWordLevel(unittest.TestCase):
    """Arrange-Act-Assert tests for _strip_word_level: drops per-word fields
    from diarization segments when with_timestamps=false, keeping the
    speaker turn shape."""

    def _make_segment(self, **overrides):
        seg = {
            "speaker": "SPEAKER_00",
            "start": 0.065,
            "end": 3.49,
            "text": "หลายคนบอกว่าปัจจุบันAIที่โง่ที่สุดและแพ้ที่สุดคือ",
            "word": "หลายคนบอกว่าปัจจุบันAIที่โง่ที่สุดและแพ้ที่สุดคือ",
            "words": [
                {"word": "หลายคน", "start": 0.065, "end": 0.85},
                {"word": "บอกว่า", "start": 0.86, "end": 1.75},
            ],
        }
        seg.update(overrides)
        return seg

    def test_removes_word_and_words_keeps_turn_fields(self):
        segments = [self._make_segment()]

        stripped = _strip_word_level(segments)

        self.assertEqual(len(stripped), 1)
        self.assertNotIn("word", stripped[0])
        self.assertNotIn("words", stripped[0])
        self.assertEqual(
            stripped[0],
            {
                "speaker": "SPEAKER_00",
                "start": 0.065,
                "end": 3.49,
                "text": "หลายคนบอกว่าปัจจุบันAIที่โง่ที่สุดและแพ้ที่สุดคือ",
            },
        )

    def test_does_not_mutate_input_segments(self):
        segments = [self._make_segment()]

        _strip_word_level(segments)

        self.assertIn("word", segments[0])
        self.assertIn("words", segments[0])

    def test_mixed_whisperx_shape(self):
        segments = [
            self._make_segment(speaker="SPEAKER_01", start=4.0, end=5.5)
        ]

        stripped = _strip_word_level(segments)

        self.assertEqual(stripped[0]["speaker"], "SPEAKER_01")
        self.assertEqual(stripped[0]["start"], 4.0)
        self.assertNotIn("word", stripped[0])

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(_strip_word_level([]), [])

    def test_segment_without_word_keys_passes_through(self):
        segment = {
            "speaker": "SPEAKER_00",
            "start": 0.0,
            "end": 1.0,
            "text": "hello",
        }

        stripped = _strip_word_level([segment])

        self.assertEqual(stripped, [segment])


if __name__ == "__main__":
    unittest.main()
