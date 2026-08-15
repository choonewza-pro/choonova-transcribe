import unittest
import json
from unittest.mock import patch, MagicMock
from fastapi import HTTPException

from app.modules.transcription.application.openai_formatters import (
    format_timestamp,
    format_srt_response,
    format_vtt_response,
    format_verbose_json_response,
    create_openai_error,
)
from app.schemas import (
    ResponseFormat,
    TimestampGranularity,
    OpenAITranscriptionJsonResponse,
    OpenAITranscriptionVerboseJsonResponse,
    OpenAIErrorResponse,
)
from app.api.v1.openai_router import _resolve_model, list_models, get_model
from app.core.security import verify_api_key
from app.core.config import GATEWAY_API_KEY


class TestOpenAICompatFormatters(unittest.TestCase):
    """Test OpenAI response formatters and helpers."""

    def test_format_timestamp_comma(self):
        self.assertEqual(format_timestamp(0.0), "00:00:00,000")
        self.assertEqual(format_timestamp(65.234), "00:01:05,234")
        self.assertEqual(format_timestamp(3661.050), "01:01:01,050")

    def test_format_timestamp_dot_for_vtt(self):
        self.assertEqual(format_timestamp(0.0, "."), "00:00:00.000")
        self.assertEqual(format_timestamp(12.345, "."), "00:00:12.345")

    def test_format_srt_response(self):
        sample_result = {
            "text": "Hello world",
            "segments": [
                {"id": 0, "start": 0.0, "end": 1.5, "text": "Hello", "speaker": "SPEAKER_00"},
                {"id": 1, "start": 1.5, "end": 2.8, "text": "world", "speaker": "SPEAKER_01"},
            ]
        }
        srt = format_srt_response(sample_result)
        self.assertIn("1\n00:00:00,000 --> 00:00:01,500\n[SPEAKER_00]: Hello", srt)
        self.assertIn("2\n00:00:01,500 --> 00:00:02,800\n[SPEAKER_01]: world", srt)

    def test_format_vtt_response(self):
        sample_result = {
            "text": "Hello world",
            "segments": [
                {"id": 0, "start": 0.0, "end": 1.5, "text": "Hello"},
                {"id": 1, "start": 1.5, "end": 2.8, "text": "world"},
            ]
        }
        vtt = format_vtt_response(sample_result)
        self.assertTrue(vtt.startswith("WEBVTT\n"))
        self.assertIn("00:00:00.000 --> 00:00:01.500\nHello", vtt)

    def test_format_verbose_json_response(self):
        sample_result = {
            "text": "Hello world",
            "duration": 3.0,
            "segments": [
                {
                    "id": 0,
                    "seek": 0,
                    "start": 0.0,
                    "end": 1.5,
                    "text": "Hello",
                    "words": [{"word": "Hello", "start": 0.0, "end": 1.5}],
                }
            ],
            "timestamps": [{"word": "Hello", "start": 0.0, "end": 1.5}],
        }
        resp = format_verbose_json_response(
            result=sample_result,
            task="transcribe",
            language="en",
            duration=3.0,
            include_words=True,
            include_segments=True,
        )
        self.assertEqual(resp.task, "transcribe")
        self.assertEqual(resp.language, "en")
        self.assertEqual(resp.duration, 3.0)
        self.assertEqual(resp.text, "Hello world")
        self.assertEqual(len(resp.segments), 1)
        self.assertIsNotNone(resp.words)
        self.assertEqual(len(resp.words), 1)
        self.assertEqual(resp.words[0].word, "Hello")

    def test_create_openai_error(self):
        json_resp = create_openai_error(
            status_code=400,
            message="Invalid model",
            error_type="invalid_request_error",
            param="model",
            code="model_not_found",
        )
        self.assertEqual(json_resp.status_code, 400)
        body = json.loads(json_resp.body.decode("utf-8"))
        self.assertIn("error", body)
        self.assertEqual(body["error"]["message"], "Invalid model")
        self.assertEqual(body["error"]["param"], "model")


class TestOpenAIModelResolutionAndAuth(unittest.TestCase):
    """Test model routing and Bearer authentication."""

    def test_resolve_model(self):
        self.assertEqual(_resolve_model("whisper-1"), "whisper")
        self.assertEqual(_resolve_model("whisper-large-v3-turbo"), "whisper")
        self.assertEqual(_resolve_model("typhoon-asr"), "typhoon")
        self.assertEqual(_resolve_model("typhoon"), "typhoon")
        self.assertEqual(_resolve_model(None), "whisper")

    def test_list_models(self):
        import asyncio
        res = asyncio.run(list_models())
        self.assertEqual(res.get("object"), "list")
        ids = [m["id"] for m in res.get("data", [])]
        self.assertIn("whisper-1", ids)
        self.assertIn("typhoon-asr", ids)

    def test_get_model_found_and_missing(self):
        import asyncio
        m = asyncio.run(get_model("whisper-1"))
        self.assertEqual(m.get("id"), "whisper-1")

        err = asyncio.run(get_model("unknown-model-xyz"))
        self.assertEqual(err.status_code, 404)

    def test_verify_api_key_with_bearer_token(self):
        import asyncio
        # Valid Bearer token
        valid = asyncio.run(verify_api_key(x_api_key=None, authorization=f"Bearer {GATEWAY_API_KEY}"))
        self.assertTrue(valid)

        # Valid x-api-key
        valid_x = asyncio.run(verify_api_key(x_api_key=GATEWAY_API_KEY, authorization=None))
        self.assertTrue(valid_x)

        # Invalid token
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(verify_api_key(x_api_key=None, authorization="Bearer wrong-key"))
        self.assertEqual(ctx.exception.status_code, 403)

        # Missing token
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(verify_api_key(x_api_key=None, authorization=None))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_unsupported_language_returns_400(self):
        from app.api.v1.openai_router import _handle_audio_request
        from unittest.mock import MagicMock
        import asyncio

        dummy_file = MagicMock()
        dummy_file.filename = "audio.mp3"
        dummy_file.read = MagicMock(side_effect=[b"ID3" + b"\x00" * 100, b""])

        res = asyncio.run(
            _handle_audio_request(
                file=dummy_file,
                model="whisper-1",
                language="unsupported_lang_xyz",
                response_format="json",
                temperature=None,
                prompt=None,
                timestamp_granularities=[],
                hotwords=None,
            )
        )
        self.assertEqual(res.status_code, 400)
        body = json.loads(res.body.decode("utf-8"))
        self.assertEqual(body["error"]["type"], "invalid_request_error")
        self.assertEqual(body["error"]["param"], "language")


if __name__ == "__main__":
    unittest.main()
