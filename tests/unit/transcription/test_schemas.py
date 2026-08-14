import unittest
from app.schemas import TranscribeResponse, TimestampItem, TranscriptionResult, TranscriptionSegment


class TestTranscriptionSchemas(unittest.TestCase):

    def test_timestamp_item_with_word_only(self):
        item = TimestampItem(word="สวัสดี", start=0.0, end=1.0)
        self.assertEqual(item.word, "สวัสดี")
        self.assertEqual(item.text, "สวัสดี")
        self.assertEqual(item.start, 0.0)
        self.assertEqual(item.end, 1.0)
        self.assertIsNone(item.speaker)

    def test_timestamp_item_with_text_only(self):
        # Diarization segments commonly use 'text' and 'speaker'
        item = TimestampItem(text="สวัสดีครับ ท่านผู้ฟัง", start=0.031, end=16.703, speaker="SPEAKER_02")
        self.assertEqual(item.word, "สวัสดีครับ ท่านผู้ฟัง")
        self.assertEqual(item.text, "สวัสดีครับ ท่านผู้ฟัง")
        self.assertEqual(item.start, 0.031)
        self.assertEqual(item.end, 16.703)
        self.assertEqual(item.speaker, "SPEAKER_02")

    def test_timestamp_item_without_word_or_text(self):
        # Edge case: raw timing turn with speaker only
        item = TimestampItem(start=0.031, end=16.703, speaker="SPEAKER_02")
        self.assertIsNone(item.word)
        self.assertIsNone(item.text)
        self.assertEqual(item.start, 0.031)
        self.assertEqual(item.end, 16.703)
        self.assertEqual(item.speaker, "SPEAKER_02")

    def test_transcribe_response_with_diarization_timestamps(self):
        raw_timestamps = [
            {"start": 0.031, "end": 16.703, "speaker": "SPEAKER_02", "text": "สวัสดีครับ"},
            {"start": 16.703, "end": 48.378, "speaker": "SPEAKER_03"},
        ]
        resp = TranscribeResponse(
            status="success",
            text="สวัสดีครับ",
            duration_seconds=48.378,
            elapsed_seconds=1.2,
            rtf=0.025,
            timestamps=raw_timestamps,
        )
        self.assertEqual(resp.status, "success")
        self.assertIsNotNone(resp.timestamps)
        self.assertEqual(len(resp.timestamps), 2)
        self.assertEqual(resp.timestamps[0].word, "สวัสดีครับ")
        self.assertEqual(resp.timestamps[0].speaker, "SPEAKER_02")
        self.assertEqual(resp.timestamps[1].speaker, "SPEAKER_03")
        self.assertIsNone(resp.timestamps[1].word)

    def test_transcription_segment_sync(self):
        seg_word = TranscriptionSegment(word="ทดสอบ", start=1.0, end=2.0)
        self.assertEqual(seg_word.text, "ทดสอบ")
        self.assertEqual(seg_word.word, "ทดสอบ")

        seg_text = TranscriptionSegment(text="ประโยคยาว", start=2.0, end=5.0, speaker="SPEAKER_01")
        self.assertEqual(seg_text.word, "ประโยคยาว")
        self.assertEqual(seg_text.text, "ประโยคยาว")


if __name__ == "__main__":
    unittest.main()
