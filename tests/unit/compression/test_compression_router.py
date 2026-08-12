import unittest
import os
import tempfile
from unittest.mock import MagicMock
from fastapi import HTTPException
from app.api.v1.compression_router import _is_safe_job_path


class TestCompressionRouterHelpers(unittest.TestCase):

    def test_is_safe_job_path_valid(self):
        job_id = "test-job-123"
        base_dir = tempfile.gettempdir()
        file_path = os.path.join(base_dir, job_id, "compressed.mp4")

        self.assertTrue(_is_safe_job_path(file_path, job_id, base_dir))

    def test_is_safe_job_path_with_db_paths(self):
        job_id = "test-job-456"
        base_dir = "/tmp/choonova-transcribe-jobs"
        real_job_dir = tempfile.mkdtemp(suffix=f"_{job_id}")
        # Rename or mock dirname to end with job_id
        target_dir = os.path.join(tempfile.gettempdir(), job_id)
        os.makedirs(target_dir, exist_ok=True)
        file_path = os.path.join(target_dir, "compressed.mp4")

        try:
            self.assertTrue(
                _is_safe_job_path(
                    file_path, job_id, base_dir,
                    job_output_path=file_path, job_input_path=None
                )
            )
        finally:
            if os.path.exists(target_dir):
                import shutil
                shutil.rmtree(target_dir, ignore_errors=True)

    def test_is_safe_job_path_traversal_rejected(self):
        job_id = "test-job-789"
        base_dir = tempfile.gettempdir()
        traversal_path = os.path.join(base_dir, job_id, "..", "secret.txt")

        self.assertFalse(_is_safe_job_path(traversal_path, job_id, base_dir))


if __name__ == "__main__":
    unittest.main()
