"""
Unit tests for pure Diarization helper functions:
- merge_speaker_overlap
- group_speaker_segments
- relabel_speakers_chronological
- build_srt_subtitles
"""

import unittest
from app.pyannote_engine import (
    merge_speaker_overlap,
    group_speaker_segments,
    smooth_speaker_labels,
    relabel_speakers_chronological,
    build_srt_subtitles,
)


class TestDiarizationHelpers(unittest.TestCase):

    def test_merge_speaker_overlap_exact_match(self):
        segments = [
            {"word": "สวัสดี", "start": 0.0, "end": 1.0},
            {"word": "ครับ", "start": 1.1, "end": 1.8},
            {"word": "สบายดีไหม", "start": 2.5, "end": 3.8},
        ]
        diarization_turns = [
            {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
            {"start": 2.2, "end": 4.0, "speaker": "SPEAKER_01"},
        ]

        result = merge_speaker_overlap(segments, diarization_turns)
        self.assertEqual(result[0]["speaker"], "SPEAKER_00")
        self.assertEqual(result[1]["speaker"], "SPEAKER_00")
        self.assertEqual(result[2]["speaker"], "SPEAKER_01")

    def test_merge_speaker_overlap_fallback_tolerance(self):
        # Word falls in silence gap between turns
        segments = [
            {"word": "เอ่อ", "start": 2.05, "end": 2.15},
        ]
        diarization_turns = [
            {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
            {"start": 2.5, "end": 4.0, "speaker": "SPEAKER_01"},
        ]

        result = merge_speaker_overlap(segments, diarization_turns, gap_tolerance_sec=0.5)
        # 2.05 is closest to turn 0.0-2.0 (dist=0.05s) -> should be SPEAKER_00
        self.assertEqual(result[0]["speaker"], "SPEAKER_00")

    def test_group_speaker_segments(self):
        segments = [
            {"text": "สวัสดี", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
            {"text": "ครับ", "start": 1.1, "end": 1.8, "speaker": "SPEAKER_00"},
            {"text": "ยินดี", "start": 2.2, "end": 2.8, "speaker": "SPEAKER_01"},
            {"text": "ที่ได้รู้จัก", "start": 2.9, "end": 3.8, "speaker": "SPEAKER_01"},
        ]

        grouped = group_speaker_segments(segments)
        self.assertEqual(len(grouped), 2)
        self.assertEqual(grouped[0]["speaker"], "SPEAKER_00")
        self.assertEqual(grouped[0]["text"], "สวัสดี ครับ")
        self.assertEqual(grouped[0]["start"], 0.0)
        self.assertEqual(grouped[0]["end"], 1.8)

        self.assertEqual(grouped[1]["speaker"], "SPEAKER_01")
        self.assertEqual(grouped[1]["text"], "ยินดี ที่ได้รู้จัก")
        self.assertEqual(grouped[1]["start"], 2.2)
        self.assertEqual(grouped[1]["end"], 3.8)

    def test_smooth_speaker_labels(self):
        # Short SPEAKER_01 blip sandwiched between SPEAKER_00 turns gets snapped.
        segments = [
            {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
            {"start": 1.0, "end": 1.2, "speaker": "SPEAKER_01"},   # 0.2s blip
            {"start": 1.2, "end": 2.0, "speaker": "SPEAKER_00"},
        ]
        result = smooth_speaker_labels([dict(s) for s in segments])
        self.assertEqual(result[1]["speaker"], "SPEAKER_00")

    def test_smooth_speaker_labels_absorbs_unknown(self):
        segments = [
            {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
            {"start": 1.0, "end": 2.0, "speaker": "UNKNOWN"},
            {"start": 2.0, "end": 3.0, "speaker": "SPEAKER_01"},
        ]
        result = smooth_speaker_labels([dict(s) for s in segments])
        # UNKNOWN absorbed into its nearest known neighbor (SPEAKER_00)
        self.assertEqual(result[1]["speaker"], "SPEAKER_00")

    def test_smooth_speaker_labels_keeps_alternation(self):
        # A-B-A-B alternation must NOT be flattened away.
        segments = [
            {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
            {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_01"},
            {"start": 4.0, "end": 6.0, "speaker": "SPEAKER_00"},
        ]
        result = smooth_speaker_labels([dict(s) for s in segments])
        self.assertEqual([s["speaker"] for s in result],
                         ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"])

    def test_relabel_speakers_chronological(self):
        # PyAnnote cluster IDs are arbitrary; SPEAKER_00 must become the
        # first speaker that actually appears in time.
        turns = [
            {"start": 30.0, "end": 35.0, "speaker": "SPEAKER_02"},
            {"start": 5.0, "end": 10.0, "speaker": "SPEAKER_01"},
            {"start": 0.0, "end": 4.0, "speaker": "SPEAKER_00"},
            {"start": 40.0, "end": 45.0, "speaker": "SPEAKER_02"},
        ]

        result = relabel_speakers_chronological(turns)
        by_start = {t["start"]: t["speaker"] for t in result}
        # first speaker (0.0) -> SPEAKER_00, second (5.0) -> SPEAKER_01, third (30.0) -> SPEAKER_02
        self.assertEqual(by_start[0.0], "SPEAKER_00")
        self.assertEqual(by_start[5.0], "SPEAKER_01")
        self.assertEqual(by_start[30.0], "SPEAKER_02")
        self.assertEqual(by_start[40.0], "SPEAKER_02")  # same cluster keeps its new label

    def test_build_srt_subtitles_with_speakers(self):
        timestamps = [
            {"text": "สวัสดีครับ", "start": 0.0, "end": 1.5, "speaker": "SPEAKER_00"},
            {"text": "ยินดีต้อนรับครับ", "start": 2.0, "end": 3.5, "speaker": "SPEAKER_01"},
        ]

        srt_output = build_srt_subtitles(timestamps)
        self.assertIn("1\n00:00:00,000 --> 00:00:01,500\n[SPEAKER_00]: สวัสดีครับ", srt_output)
        self.assertIn("2\n00:00:02,000 --> 00:00:03,500\n[SPEAKER_01]: ยินดีต้อนรับครับ", srt_output)


if __name__ == "__main__":
    unittest.main()
