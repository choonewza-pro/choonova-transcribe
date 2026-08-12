import unittest
from app.api.web import views_router as vr
from app.api.web.views_router import check_history_access


class FakeRequest:
    def __init__(self, query_params=None, headers=None, cookies=None):
        self.query_params = query_params or {}
        self.headers = headers or {}
        self.cookies = cookies or {}


class TestHistorySecurity(unittest.TestCase):

    def setUp(self):
        # Save original settings to restore later
        self.orig_transcribe_bypass = vr.ALLOW_ACCESS_TRANSCRIBE_HISTORY
        self.orig_compress_bypass = vr.ALLOW_ACCESS_COMPRESS_HISTORY
        self.gateway_key = vr.GATEWAY_API_KEY

    def tearDown(self):
        # Restore original settings
        vr.ALLOW_ACCESS_TRANSCRIBE_HISTORY = self.orig_transcribe_bypass
        vr.ALLOW_ACCESS_COMPRESS_HISTORY = self.orig_compress_bypass

    def test_bypass_transcribe_history(self):
        vr.ALLOW_ACCESS_TRANSCRIBE_HISTORY = True
        
        req = FakeRequest()
        is_allowed, key = check_history_access(req, "transcribe")
        self.assertTrue(is_allowed)
        self.assertIsNone(key)

    def test_bypass_compress_history(self):
        vr.ALLOW_ACCESS_COMPRESS_HISTORY = True
        
        req = FakeRequest()
        is_allowed, key = check_history_access(req, "compress")
        self.assertTrue(is_allowed)
        self.assertIsNone(key)

    def test_no_bypass_missing_key(self):
        vr.ALLOW_ACCESS_TRANSCRIBE_HISTORY = False
        vr.ALLOW_ACCESS_COMPRESS_HISTORY = False
        
        req = FakeRequest()
        is_allowed, key = check_history_access(req, "transcribe")
        self.assertFalse(is_allowed)
        self.assertIsNone(key)

    def test_correct_key_query_param(self):
        vr.ALLOW_ACCESS_TRANSCRIBE_HISTORY = False
        
        req = FakeRequest(query_params={"api_key": self.gateway_key})
        is_allowed, key = check_history_access(req, "transcribe")
        self.assertTrue(is_allowed)
        self.assertEqual(key, self.gateway_key)

    def test_correct_key_cookie(self):
        vr.ALLOW_ACCESS_TRANSCRIBE_HISTORY = False
        
        req = FakeRequest(cookies={"typhoon_asr_api_key": self.gateway_key})
        is_allowed, key = check_history_access(req, "transcribe")
        self.assertTrue(is_allowed)
        self.assertEqual(key, self.gateway_key)

    def test_incorrect_key(self):
        vr.ALLOW_ACCESS_TRANSCRIBE_HISTORY = False
        
        req = FakeRequest(query_params={"api_key": "wrong-key"})
        is_allowed, key = check_history_access(req, "transcribe")
        self.assertFalse(is_allowed)
        self.assertIsNone(key)


if __name__ == "__main__":
    unittest.main()
