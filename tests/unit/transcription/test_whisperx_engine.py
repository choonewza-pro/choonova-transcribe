import sys
import unittest

from app.core.config import WHISPER_THAI_COMPUTE_TYPE, WHISPERX_MODEL, WHISPER_COMPUTE_TYPE
from app.whisper_thai_engine import resolve_thai_model_name
from app.whisperx_engine import WhisperXDiarizer, _select_asr_model


class TestSelectAsrModel(unittest.TestCase):
    """Pure model-selection helper for the WhisperX ASR model."""

    def test_whisperx_thai_selects_thai_tuned_ct2(self):
        name, ct = _select_asr_model("whisperx-thai", "th")
        self.assertEqual(name, resolve_thai_model_name())
        self.assertEqual(ct, WHISPER_THAI_COMPUTE_TYPE)

    def test_whisperx_thai_is_case_and_space_insensitive(self):
        name, ct = _select_asr_model("  WhisperX-Thai ", "th")
        self.assertEqual(name, resolve_thai_model_name())
        self.assertEqual(ct, WHISPER_THAI_COMPUTE_TYPE)

    def test_whisperx_keeps_default_asr(self):
        for model in ("whisperx", "whisper", None, ""):
            name, ct = _select_asr_model(model, "th")
            self.assertEqual((name, ct), (WHISPERX_MODEL, WHISPER_COMPUTE_TYPE))


class _FakeWhisperX:
    def __init__(self):
        self.loaded = []

    def load_model(self, name, device=None, compute_type=None):
        self.loaded.append((name, compute_type))
        return f"model:{name}"


class TestWhisperXDiarizerLoadSwitching(unittest.TestCase):
    """The WhisperX singleton reloads its ASR model when the selection changes."""

    def setUp(self):
        self._fake = _FakeWhisperX()
        self._orig = sys.modules.get("whisperx")
        sys.modules["whisperx"] = self._fake
        self.d = WhisperXDiarizer(model_name="turbo", device="cpu", compute_type="int8")

    def tearDown(self):
        if self._orig is not None:
            sys.modules["whisperx"] = self._orig
        else:
            sys.modules.pop("whisperx", None)

    def test_reuses_already_loaded_matching_model(self):
        self.d.load_asr_model("A", "ct1")
        self.assertEqual(len(self._fake.loaded), 1)
        self.d.load_asr_model("A", "ct1")
        self.assertEqual(len(self._fake.loaded), 1)
        self.assertEqual(self.d._asr_model_name, "A")

    def test_reloads_when_selection_changes(self):
        self.d.load_asr_model("turbo", "int8")
        self.d.load_asr_model("thai", "int8_float16")
        self.assertEqual(len(self._fake.loaded), 2)
        self.assertEqual(self._fake.loaded[-1], ("thai", "int8_float16"))
        self.assertEqual(self.d._asr_model, "model:thai")
        self.assertEqual(self.d._asr_model_name, "thai")
        self.assertEqual(self.d._asr_compute_type, "int8_float16")


if __name__ == "__main__":
    unittest.main()