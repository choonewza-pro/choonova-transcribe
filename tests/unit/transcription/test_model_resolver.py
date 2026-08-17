import unittest

from app.model_selection import resolve_transcription_model


class TestResolveTranscriptionModel(unittest.TestCase):
    """Matrix tests for the model selection resolver (th/en/auto x diarization)."""

    # ------------------------------------------------------------- valid matrix

    def test_th_without_diarization_allows_three_models(self):
        for model in ("thai-whisper", "typhoon", "whisper"):
            self.assertEqual(
                resolve_transcription_model("th", False, model), model
            )

    def test_th_with_diarization_allows_three_models(self):
        for model in ("thai-whisper", "whisperx", "whisperx-thai"):
            self.assertEqual(
                resolve_transcription_model("th", True, model), model
            )

    def test_en_without_diarization_allows_only_whisper(self):
        self.assertEqual(
            resolve_transcription_model("en", False, "whisper"), "whisper"
        )

    def test_auto_without_diarization_allows_only_whisper(self):
        self.assertEqual(
            resolve_transcription_model("auto", False, "whisper"), "whisper"
        )

    def test_en_and_auto_with_diarization_allow_only_whisperx(self):
        for lang in ("en", "auto"):
            self.assertEqual(
                resolve_transcription_model(lang, True, "whisperx"), "whisperx"
            )

    # --------------------------------------------------------- invalid combos

    def test_th_diarization_rejects_non_diar_models(self):
        for model in ("typhoon", "whisper"):
            with self.assertRaises(ValueError):
                resolve_transcription_model("th", True, model)

    def test_en_rejects_thai_models(self):
        for model in ("thai-whisper", "typhoon", "whisperx"):
            with self.assertRaises(ValueError):
                resolve_transcription_model("en", False, model)

    def test_auto_without_diarization_rejects_whisperx(self):
        with self.assertRaises(ValueError):
            resolve_transcription_model("auto", False, "whisperx")

    def test_unknown_model_rejected(self):
        with self.assertRaises(ValueError):
            resolve_transcription_model("th", False, "gpt-5")

    # --------------------------------------------- num_speakers forcing diarization

    def test_model_invalid_when_speaker_params_force_diarization(self):
        # Router forces enable_diarization=True when num_speakers/min/max are sent;
        # after forcing, model='whisper' must be rejected for th.
        with self.assertRaises(ValueError):
            resolve_transcription_model("th", True, "whisper")

    # ------------------------------------------------------------ normalization

    def test_model_is_normalized_case_and_whitespace_insensitive(self):
        self.assertEqual(
            resolve_transcription_model("th", False, "  THAI-WHISPER "),
            "thai-whisper",
        )

    def test_missing_model_raises_with_allowed_list(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_transcription_model("th", True, None)
        self.assertIn("thai-whisper", str(ctx.exception))
        self.assertIn("whisperx", str(ctx.exception))
        self.assertIn("whisperx-thai", str(ctx.exception))

    def test_invalid_combo_error_mentions_allowed_models(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_transcription_model("th", True, "typhoon")
        msg = str(ctx.exception)
        self.assertIn("thai-whisper", msg)
        self.assertIn("whisperx", msg)
        self.assertIn("whisperx-thai", msg)


if __name__ == "__main__":
    unittest.main()
