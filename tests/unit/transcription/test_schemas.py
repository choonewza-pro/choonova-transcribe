import unittest
from app.schemas import TranscribeResponse, TranscriptionSegment


class TestTranscriptionSchemas(unittest.TestCase):

    def test_segment_with_word_only_backfills_text(self):
        # Legacy word-only items are normalized: `word` is dropped and its
        # content backfilled into `text` by the validator.
        item = TranscriptionSegment(word="สวัสดี", start=0.0, end=1.0)
        self.assertEqual(item.text, "สวัสดี")
        self.assertEqual(item.start, 0.0)
        self.assertEqual(item.end, 1.0)
        self.assertIsNone(item.speaker)

    def test_segment_with_text_only(self):
        # Diarization segments commonly use 'text' and 'speaker'
        item = TranscriptionSegment(text="สวัสดีครับ ท่านผู้ฟัง", start=0.031, end=16.703, speaker="SPEAKER_02")
        self.assertEqual(item.text, "สวัสดีครับ ท่านผู้ฟัง")
        self.assertEqual(item.start, 0.031)
        self.assertEqual(item.end, 16.703)
        self.assertEqual(item.speaker, "SPEAKER_02")

    def test_segment_without_word_or_text(self):
        # Edge case: raw timing turn with speaker only
        item = TranscriptionSegment(start=0.031, end=16.703, speaker="SPEAKER_02")
        self.assertIsNone(item.text)
        self.assertEqual(item.start, 0.031)
        self.assertEqual(item.end, 16.703)
        self.assertEqual(item.speaker, "SPEAKER_02")

    def test_segment_with_nested_words(self):
        item = TranscriptionSegment(
            text="สวัสดี",
            start=0.0,
            end=1.2,
            words=[{"word": "สวัสดี", "start": 0.0, "end": 1.2}],
        )
        self.assertEqual(len(item.words), 1)
        self.assertEqual(item.words[0]["word"], "สวัสดี")

    def test_segment_serialization_omits_null_words(self):
        # `words: null` is serialization noise — omitted from the payload.
        item = TranscriptionSegment(text="สวัสดี", start=0.0, end=1.2)
        dumped = item.model_dump()
        self.assertNotIn("words", dumped)
        self.assertNotIn("word", dumped)

        item_with_words = TranscriptionSegment(
            text="สวัสดี", start=0.0, end=1.2,
            words=[{"word": "สวัสดี", "start": 0.0, "end": 1.2}],
        )
        self.assertIn("words", item_with_words.model_dump())

    def test_transcribe_response_with_diarization_segments(self):
        raw_segments = [
            {"start": 0.031, "end": 16.703, "speaker": "SPEAKER_02", "text": "สวัสดีครับ"},
            {"start": 16.703, "end": 48.378, "speaker": "SPEAKER_03"},
        ]
        resp = TranscribeResponse(
            status="success",
            text="สวัสดีครับ",
            duration_seconds=48.378,
            elapsed_seconds=1.2,
            rtf=0.025,
            segments=raw_segments,
        )
        self.assertEqual(resp.status, "success")
        self.assertIsNotNone(resp.segments)
        self.assertEqual(len(resp.segments), 2)
        self.assertEqual(resp.segments[0].text, "สวัสดีครับ")
        self.assertEqual(resp.segments[0].speaker, "SPEAKER_02")
        self.assertEqual(resp.segments[1].speaker, "SPEAKER_03")
        self.assertIsNone(resp.segments[1].text)

    def test_transcription_segment_sync(self):
        seg_word = TranscriptionSegment(word="ทดสอบ", start=1.0, end=2.0)
        self.assertEqual(seg_word.text, "ทดสอบ")

        seg_text = TranscriptionSegment(text="ประโยคยาว", start=2.0, end=5.0, speaker="SPEAKER_01")
        self.assertEqual(seg_text.text, "ประโยคยาว")


if __name__ == "__main__":
    unittest.main()
