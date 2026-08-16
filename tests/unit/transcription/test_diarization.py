"""
Unit tests for pure Diarization helper functions:
- merge_speaker_overlap
- assign_speakers_to_segments
- group_speaker_segments
- relabel_speakers_chronological
- build_srt_subtitles
"""

import unittest
from app.pyannote_engine import (
    merge_speaker_overlap,
    assign_speakers_to_segments,
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

    def test_assign_speakers_to_segments_exact_match(self):
        segments = [
            {"text": "สวัสดีครับ", "start": 0.0, "end": 1.8},
            {"text": "ยินดีที่ได้รู้จัก", "start": 2.2, "end": 3.8},
        ]
        turns = [
            {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
            {"start": 2.2, "end": 4.0, "speaker": "SPEAKER_01"},
        ]

        result = assign_speakers_to_segments(segments, turns)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["speaker"], "SPEAKER_00")
        self.assertEqual(result[1]["speaker"], "SPEAKER_01")
        # Output shape matches the Gemini reference: word/text/start/end/speaker
        self.assertEqual(result[0]["text"], "สวัสดีครับ")
        self.assertEqual(result[0]["word"], "สวัสดีครับ")
        self.assertEqual(result[0]["start"], 0.0)
        self.assertEqual(result[0]["end"], 1.8)

    def test_assign_speakers_to_segments_nearest_fallback(self):
        # Segment lands in a silence gap; nearest turn within tolerance wins.
        segments = [
            {"text": "เอ่อ", "start": 2.05, "end": 2.15},
        ]
        turns = [
            {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
            {"start": 2.5, "end": 4.0, "speaker": "SPEAKER_01"},
        ]

        result = assign_speakers_to_segments(segments, turns, gap_tolerance_sec=0.5)
        self.assertEqual(result[0]["speaker"], "SPEAKER_00")

    def test_assign_speakers_to_segments_no_turns_unknown(self):
        segments = [
            {"text": "สวัสดี", "start": 0.0, "end": 1.0},
        ]
        result = assign_speakers_to_segments(segments, [])
        self.assertEqual(result[0]["speaker"], "UNKNOWN")
        self.assertEqual(result[0]["text"], "สวัสดี")

    def test_assign_speakers_to_segments_empty_segments(self):
        self.assertEqual(assign_speakers_to_segments([], []), [])

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
        self.assertEqual(grouped[0]["text"], "สวัสดีครับ")
        self.assertEqual(grouped[0]["start"], 0.0)
        self.assertEqual(grouped[0]["end"], 1.8)

        self.assertEqual(grouped[1]["speaker"], "SPEAKER_01")
        self.assertEqual(grouped[1]["text"], "ยินดีที่ได้รู้จัก")
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

    def test_collapse_repeated_tokens(self):
        from app.text_utils import collapse_repeated_tokens

        # RNNT decode loop hallucination: long identical runs collapse to 3.
        tokens = ["สาย", "นาง", "นาง", "นาง", "นาง", "นาง", "นาง", "ไง"]
        result = collapse_repeated_tokens(tokens)
        self.assertEqual(result.count("นาง"), 3)

    def test_collapse_repeated_tokens_keeps_short_emphasis(self):
        from app.text_utils import collapse_repeated_tokens

        # Legitimate short repetition must be preserved.
        result = collapse_repeated_tokens(["เร็ว", "เร็ว"])
        self.assertEqual(result, ["เร็ว", "เร็ว"])

    def test_clean_text_collapses_hallucination(self):
        from app.text_utils import clean_text

        # Full-text cleanup drops pathological loops (works without pythainlp
        # installed because the fallback splits on whitespace here).
        text = "go " + "go " * 20 + "go"
        cleaned = clean_text(text)
        self.assertEqual(cleaned.count("go"), 3)

    def test_group_speaker_segments_joins_thai_without_spaces(self):
        # Thai turns should read as continuous text, matching raw ASR output.
        segments = [
            {"text": "สวัสดี", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
            {"text": "ครับ", "start": 1.1, "end": 1.8, "speaker": "SPEAKER_00"},
            {"text": "hello", "start": 2.2, "end": 2.8, "speaker": "SPEAKER_01"},
            {"text": "there", "start": 2.9, "end": 3.8, "speaker": "SPEAKER_01"},
        ]

        grouped = group_speaker_segments(segments)
        self.assertEqual(grouped[0]["text"], "สวัสดีครับ")
        self.assertEqual(grouped[1]["text"], "hello there")

    def test_consolidate_resolves_cross_speaker_overlap(self):
        from app.pyannote_engine import consolidate_diarization_turns

        # Two speakers claim overlapping time; the longer turn dominates.
        turns = [
            {"start": 0.0, "end": 4.0, "speaker": "SPEAKER_01"},
            {"start": 1.0, "end": 3.0, "speaker": "SPEAKER_00"},
        ]
        result = consolidate_diarization_turns(turns)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["speaker"], "SPEAKER_01")
        self.assertEqual(result[0]["start"], 0.0)
        self.assertEqual(result[0]["end"], 4.0)

    def test_consolidate_truncates_later_turn(self):
        from app.pyannote_engine import consolidate_diarization_turns

        # Overlapping turns: the later one is cut out of the overlap region.
        turns = [
            {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
            {"start": 1.0, "end": 5.0, "speaker": "SPEAKER_01"},
        ]
        result = consolidate_diarization_turns(turns)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["speaker"], "SPEAKER_00")
        self.assertEqual(result[0]["end"], 2.0)
        self.assertEqual(result[1]["speaker"], "SPEAKER_01")
        self.assertEqual(result[1]["start"], 2.0)
        self.assertEqual(result[1]["end"], 5.0)

    def test_consolidate_merges_same_speaker_gap(self):
        from app.pyannote_engine import consolidate_diarization_turns

        turns = [
            {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
            {"start": 2.4, "end": 4.0, "speaker": "SPEAKER_00"},   # gap 0.4 <= 0.6
            {"start": 6.0, "end": 7.0, "speaker": "SPEAKER_01"},
        ]
        result = consolidate_diarization_turns(turns)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["speaker"], "SPEAKER_00")
        self.assertEqual(result[0]["end"], 4.0)

    def test_consolidate_drops_tiny_turns(self):
        from app.pyannote_engine import consolidate_diarization_turns

        turns = [
            {"start": 0.0, "end": 4.0, "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 5.3, "speaker": "SPEAKER_01"},   # 0.3s < 0.5s min
        ]
        result = consolidate_diarization_turns(turns)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["speaker"], "SPEAKER_00")

    def test_group_words_by_turns_buckets_by_overlap(self):
        from app.pyannote_engine import group_words_by_turns

        words = [
            {"word": "สวัสดี", "start": 0.1, "end": 0.9},
            {"word": "ครับ", "start": 1.0, "end": 1.8},
            {"word": "ยินดี", "start": 2.2, "end": 2.9},
            {"word": "ที่รู้จัก", "start": 3.0, "end": 3.9},
        ]
        turns = [
            {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
            {"start": 2.1, "end": 4.0, "speaker": "SPEAKER_01"},
        ]
        result = group_words_by_turns(words, turns)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["speaker"], "SPEAKER_00")
        self.assertEqual(result[0]["text"], "สวัสดีครับ")
        self.assertEqual(result[0]["start"], 0.0)
        self.assertEqual(result[1]["speaker"], "SPEAKER_01")
        self.assertEqual(result[1]["text"], "ยินดีที่รู้จัก")
        self.assertEqual(
            [w["word"] for w in result[0]["words"]],
            ["สวัสดี", "ครับ"],
        )
        self.assertEqual(
            [w["word"] for w in result[1]["words"]],
            ["ยินดี", "ที่รู้จัก"],
        )
        self.assertEqual(result[0]["words"][0]["start"], 0.1)
        self.assertEqual(result[0]["words"][1]["end"], 1.8)

    def test_group_words_by_turns_empty(self):
        from app.pyannote_engine import group_words_by_turns

        self.assertEqual(group_words_by_turns([], []), [])
        self.assertEqual(
            group_words_by_turns(
                [{"word": "ครับ", "start": 0.0, "end": 0.5}], []
            ),
            [],
        )

    def test_reconstruct_thai_words_rebuilds_whole_words(self):
        from app.pyannote_engine import reconstruct_thai_words

        # faster-whisper returns character-level tokens for Thai; reconstruct
        # must re-tokenize the full text into whole words with real times.
        segments = [
            {
                "text": "คุณชมนี เป็นอะไร",
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
        ]
        result = reconstruct_thai_words(segments)
        self.assertTrue(result)
        joined = "".join(w["word"] for w in result).replace(" ", "")
        self.assertEqual(joined, "คุณชมนีเป็นอะไร")
        self.assertGreaterEqual(result[0]["start"], 0.0)
        self.assertLessEqual(result[-1]["end"], 1.8)

    def test_reconstruct_thai_words_empty_and_without_pythainlp(self):
        from app.pyannote_engine import reconstruct_thai_words

        self.assertEqual(reconstruct_thai_words([]), [])
        # segments without words fall back to char tokens
        result = reconstruct_thai_words([{"text": "สวัสดี", "words": []}])
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
