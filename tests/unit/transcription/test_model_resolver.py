import unittest

from app.model_selection import resolve_transcription_model


class TestResolveTranscriptionModel(unittest.TestCase):
    """Matrix tests for the model selection resolver (th/en/auto x diarization x translate)."""

    # ------------------------------------------------------------- valid matrix

    def test_th_without_diarization_allows_three_models(self):
        for model in ("thai-whisper", "typhoon", "whisper"):
            self.assertEqual(
                resolve_transcription_model("th", False, "transcribe", model), model
            )

    def test_th_with_diarization_allows_thai_whisper_and_whisperx(self):
        for model in ("thai-whisper", "whisperx"):
            self.assertEqual(
                resolve_transcription_model("th", True, "transcribe", model), model
            )

    def test_en_without_diarization_allows_only_whisper(self):
        self.assertEqual(
            resolve_transcription_model("en", False, "transcribe", "whisper"), "whisper"
        )

    def test_auto_without_diarization_allows_only_whisper(self):
        self.assertEqual(
            resolve_transcription_model("auto", False, "transcribe", "whisper"), "whisper"
        )

    def test_en_and_auto_with_diarization_allow_only_whisperx(self):
        for lang in ("en", "auto"):
            self.assertEqual(
                resolve_transcription_model(lang, True, "transcribe", "whisperx"), "whisperx"
            )

    def test_translate_allows_only_whisper(self):
        for lang in ("th", "en", "auto"):
            self.assertEqual(
                resolve_transcription_model(lang, False, "translate", "whisper"), "whisper"
            )
            self.assertEqual(
                resolve_transcription_model(lang, True, "translate", "whisper"), "whisper"
            )

    # --------------------------------------------------------- invalid combos

    def test_th_diarization_rejects_non_diar_models(self):
        for model in ("typhoon", "whisper"):
            with self.assertRaises(ValueError):
                resolve_transcription_model("th", True, "transcribe", model)

    def test_en_rejects_thai_models(self):
        for model in ("thai-whisper", "typhoon", "whisperx"):
            with self.assertRaises(ValueError):
                resolve_transcription_model("en", False, "transcribe", model)

    def test_auto_without_diarization_rejects_whisperx(self):
        with self.assertRaises(ValueError):
            resolve_transcription_model("auto", False, "transcribe", "whisperx")

    def test_translate_rejects_non_whisper_models(self):
        for model in ("thai-whisper", "typhoon", "whisperx"):
            with self.assertRaises(ValueError):
                resolve_transcription_model("th", False, "translate", model)

    def test_unknown_model_rejected(self):
        with self.assertRaises(ValueError):
            resolve_transcription_model("th", False, "transcribe", "gpt-5")

    # --------------------------------------------- num_speakers forcing diarization

    def test_model_invalid_when_speaker_params_force_diarization(self):
        # Router forces enable_diarization=True when num_speakers/min/max are sent;
        # after forcing, model='whisper' must be rejected for th.
        with self.assertRaises(ValueError):
            resolve_transcription_model("th", True, "transcribe", "whisper")

    # ------------------------------------------------------------ normalization

    def test_model_is_normalized_case_and_whitespace_insensitive(self):
        self.assertEqual(
            resolve_transcription_model("th", False, "transcribe", "  THAI-WHISPER "),
            "thai-whisper",
        )

    def test_missing_model_raises_with_allowed_list(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_transcription_model("th", True, "transcribe", None)
        self.assertIn("thai-whisper", str(ctx.exception))
        self.assertIn("whisperx", str(ctx.exception))

    def test_invalid_combo_error_mentions_allowed_models(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_transcription_model("th", True, "transcribe", "typhoon")
        msg = str(ctx.exception)
        self.assertIn("thai-whisper", msg)
        self.assertIn("whisperx", msg)


if __name__ == "__main__":
    unittest.main()
