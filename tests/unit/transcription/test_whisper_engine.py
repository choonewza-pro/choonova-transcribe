"""
Unit tests for whisper_engine.resolve_whisper_model_name().

The resolver must find a locally-baked CT2 copy under models/ before falling
back to HuggingFace, regardless of the folder naming convention (legacy
unprefixed ``faster-whisper-large-v3-turbo`` vs the canonical ``-ct2`` name
used by scripts/download_models.py). A name mismatch here caused the first
``model=whisper`` request to download ~1.6GB from HF inside the self-test's
request timeout.
"""

import os
import shutil
import tempfile
import unittest

import app.whisper_engine as whisper_engine


class TestResolveWhisperModelName(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig_service_dir = whisper_engine.SERVICE_DIR
        self._orig_whisper_model = whisper_engine.WHISPER_MODEL
        whisper_engine.SERVICE_DIR = self._tmp

    def tearDown(self):
        whisper_engine.SERVICE_DIR = self._orig_service_dir
        whisper_engine.WHISPER_MODEL = self._orig_whisper_model
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _bake(self, folder_name: str) -> str:
        path = os.path.join(self._tmp, "models", folder_name)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "model.bin"), "wb") as f:
            f.write(b"\x00")
        return path

    def test_legacy_bare_folder_found_for_turbo(self):
        whisper_engine.WHISPER_MODEL = "large-v3-turbo"
        baked = self._bake("faster-whisper-large-v3-turbo")
        self.assertEqual(whisper_engine.resolve_whisper_model_name(), baked)

    def test_canonical_ct2_folder_found_for_turbo(self):
        whisper_engine.WHISPER_MODEL = "large-v3-turbo"
        baked = self._bake("faster-whisper-large-v3-turbo-ct2")
        self.assertEqual(whisper_engine.resolve_whisper_model_name(), baked)

    def test_turbo_falls_back_to_hf_mirror_when_missing(self):
        whisper_engine.WHISPER_MODEL = "large-v3-turbo"
        self.assertEqual(
            whisper_engine.resolve_whisper_model_name(),
            "deepdml/faster-whisper-large-v3-turbo-ct2",
        )

    def test_full_repo_id_with_local_copy(self):
        whisper_engine.WHISPER_MODEL = "deepdml/faster-whisper-large-v3-turbo-ct2"
        baked = self._bake("faster-whisper-large-v3-turbo-ct2")
        self.assertEqual(whisper_engine.resolve_whisper_model_name(), baked)

    def test_full_repo_id_without_local_copy(self):
        whisper_engine.WHISPER_MODEL = "deepdml/faster-whisper-large-v3-turbo-ct2"
        self.assertEqual(
            whisper_engine.resolve_whisper_model_name(),
            "deepdml/faster-whisper-large-v3-turbo-ct2",
        )


if __name__ == "__main__":
    unittest.main()
