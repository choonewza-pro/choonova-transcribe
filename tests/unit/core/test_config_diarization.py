import unittest

from app.core.config import _resolve_diarization_enabled


class TestResolveDiarizationEnabled(unittest.TestCase):
    """Pure-function tests for the DIARIZATION_ENABLED resolution logic."""

    def test_explicit_true_wins_over_missing_token(self):
        self.assertTrue(_resolve_diarization_enabled(None, "true"))
        self.assertTrue(_resolve_diarization_enabled(None, "1"))
        self.assertTrue(_resolve_diarization_enabled(None, "yes"))
        self.assertTrue(_resolve_diarization_enabled(None, "True"))

    def test_explicit_false_wins_over_token(self):
        self.assertFalse(_resolve_diarization_enabled("hf_abc123", "false"))
        self.assertFalse(_resolve_diarization_enabled("hf_abc123", "0"))
        self.assertFalse(_resolve_diarization_enabled("hf_abc123", "no"))
        self.assertFalse(_resolve_diarization_enabled("hf_abc123", "False"))

    def test_unset_env_auto_off_without_token(self):
        self.assertFalse(_resolve_diarization_enabled(None, None))
        self.assertFalse(_resolve_diarization_enabled("", None))

    def test_unset_env_auto_on_with_token(self):
        self.assertTrue(_resolve_diarization_enabled("hf_abc123", None))

    def test_blank_env_value_treated_as_unset(self):
        self.assertTrue(_resolve_diarization_enabled("hf_abc123", ""))
        self.assertFalse(_resolve_diarization_enabled(None, ""))


if __name__ == "__main__":
    unittest.main()