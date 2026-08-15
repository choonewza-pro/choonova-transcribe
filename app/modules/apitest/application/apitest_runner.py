"""
ApiTestRunner — orchestrates the automated API endpoint self-test.

Exercise the running service's own HTTP endpoints (healthz, audio transcribe,
long-form media transcribe family, video compress family) using the sample
asset files shipped in `assets/`, and produce a field-by-field pass/fail report.

Design notes:
- Only the Typhoon ASR path is exercised: every transcription test sends
  `language=th` (never `en`/`auto`, which would route to the Whisper engine).
- Async jobs are polled via GET status until a terminal status; the wait is
  bounded by configurable max-wait seconds. Cleanup DELETE always runs so a
  failed or timed-out job leaves no residue.
- All self-requests are authenticated server-side with GATEWAY_API_KEY (the
  injected ApiHttpPort carries it), so the middleware, validation, and auth
  stack are exercised for real.

This class knows only the domain entities and the ApiHttpPort — no FastAPI,
no httpx, no framework outside reading two asset files from disk.
"""

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.config import (
    APITEST_COMPRESS_MAX_WAIT_SEC,
    APITEST_POLL_INTERVAL_SEC,
    APITEST_TRANSCRIBE_MAX_WAIT_SEC,
    COMPRESS_CRF,
    COMPRESS_ENCODER,
    COMPRESS_PRESET,
)
from app.modules.apitest.domain.entities import (
    ApiTestReport,
    EndpointTest,
    FieldCheck,
    InputParam,
)
from app.modules.apitest.domain.ports import ApiHttpPort

AUDIO_ASSET_NAME = "test-audio-th.wav"
VIDEO_ASSET_NAME = "The-Frog-and-The-Ox.mp4"

TERMINAL_STATUSES = ("completed", "failed", "cancelled")

_TYPE_PREDICATES = {
    "str": lambda v: isinstance(v, str),
    "num": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "bool": lambda v: isinstance(v, bool),
    "list": lambda v: isinstance(v, list),
    "obj": lambda v: isinstance(v, dict),
    # present-only: value may legitimately be None (error_message, started_at, ...)
    "any": lambda v: True,
}


class AssetNotFoundError(FileNotFoundError):
    """Raised when a required sample asset file is missing on disk."""


class ApiTestRunner:
    """Run one self-test pass and aggregate the per-endpoint results."""

    def __init__(
        self,
        http: ApiHttpPort,
        assets_dir: str,
        max_transcribe_wait: Optional[float] = None,
        max_compress_wait: Optional[float] = None,
        poll_interval: Optional[float] = None,
        api_key: str = "",
    ):
        self._http = http
        self._api_key = api_key
        self._assets_dir = assets_dir
        self._audio_path = os.path.join(assets_dir, AUDIO_ASSET_NAME)
        self._video_path = os.path.join(assets_dir, VIDEO_ASSET_NAME)
        self._max_transcribe_wait = (
            float(max_transcribe_wait)
            if max_transcribe_wait is not None
            else float(APITEST_TRANSCRIBE_MAX_WAIT_SEC)
        )
        self._max_compress_wait = (
            float(max_compress_wait)
            if max_compress_wait is not None
            else float(APITEST_COMPRESS_MAX_WAIT_SEC)
        )
        self._poll_interval = (
            float(poll_interval)
            if poll_interval is not None
            else float(APITEST_POLL_INTERVAL_SEC)
        )

    # ------------------------------------------------------------- assets

    def check_assets(self) -> None:
        """Raise AssetNotFoundError if either sample asset is missing on disk."""
        missing = [p for p in (self._audio_path, self._video_path) if not os.path.isfile(p)]
        if missing:
            names = ", ".join(os.path.basename(p) for p in missing)
            raise AssetNotFoundError(
                f"ไม่พบไฟล์ทดสอบในโฟลเดอร์ assets/: {names} (ควรอยู่ที่ {self._assets_dir})"
            )

    def asset_info(self) -> Dict[str, Any]:
        def _info(path: str) -> Dict[str, Any]:
            return {
                "filename": os.path.basename(path),
                "exists": os.path.isfile(path),
                "size_bytes": os.path.getsize(path) if os.path.isfile(path) else 0,
            }

        return {
            "assets_dir": self._assets_dir,
            "assets": {
                AUDIO_ASSET_NAME: _info(self._audio_path),
                VIDEO_ASSET_NAME: _info(self._video_path),
            },
        }

    async def run(
        self,
        suite: str = "typhoon",
        cleanup: bool = True,
        on_test: Optional[Callable[[EndpointTest], Any]] = None,
        on_progress: Optional[Callable[[Dict[str, Any]], Any]] = None,
        on_start: Optional[Callable[[int], Any]] = None,
    ) -> ApiTestReport:
        """Run the selected self-test suite and return the aggregated report.

        suite options:
          - 'typhoon': Baseline Typhoon Thai ASR + FFmpeg Video Compression (default)
          - 'pyannote': Typhoon + PyAnnote 3.1 Thai Speaker Diarization
          - 'whisperx': WhisperX English/Auto Speaker Diarization + Forced Alignment
        """
        self.check_assets()
        report = ApiTestReport(started_at=_now_iso())

        suite = (suite or "typhoon").lower().strip()
        if suite not in ("typhoon", "pyannote", "whisperx"):
            suite = "typhoon"

        if on_start is not None:
            await on_start(self._expected_total(cleanup, suite=suite))

        async def push(test: EndpointTest) -> None:
            test.order = len(report.tests) + 1
            report.tests.append(test)
            if on_test is not None:
                await on_test(test)

        try:
            if suite == "typhoon":
                await push(await self._test_health())
                await push(await self._test_audio_sync())
                await self._transcribe_family(cleanup=cleanup, push=push, on_progress=on_progress)
                await self._compress_family(cleanup=cleanup, push=push, on_progress=on_progress)
            elif suite == "pyannote":
                await push(await self._test_health())
                await push(await self._test_audio_sync_diarize(lang="th"))
                await self._transcribe_family_diarize(lang="th", cleanup=cleanup, push=push, on_progress=on_progress)
            elif suite == "whisperx":
                await push(await self._test_health())
                await push(await self._test_audio_sync_diarize(lang="en"))
                await self._transcribe_family_diarize(lang="auto", cleanup=cleanup, push=push, on_progress=on_progress)
        finally:
            report.finished_at = _now_iso()
        return report

    # ------------------------------------------------------------- health

    async def _test_health(self) -> EndpointTest:
        method, path, expected, name = "GET", "/healthz", 200, "ตรวจสอบบริการ (/healthz)"
        specs = [
            ("status", "str"), ("service", "str"), ("device", "str"),
            ("execution_device", "str"), ("model_load_mode", "str"),
            ("model_idle_timeout_sec", "num"), ("typhoon_model_state", "str"),
            ("whisper_model_state", "str"),
        ]
        start = time.monotonic()
        try:
            status, body = await self._http.get(path, timeout=30)
            checks = self._check_fields(body, specs)
            if isinstance(body, dict):
                checks.append(_value_check("status==ok", body.get("status") == "ok", body.get("status")))
            passed = status == expected and all(c.passed for c in checks)
            return EndpointTest(method, path, name, status, passed,
                                time.monotonic() - start, [], checks)
        except Exception as e:  # noqa: BLE001
            return self._error_test(method, path, name, expected, [], specs, e)

    # ------------------------------------------------------------- audio sync

    async def _test_audio_sync(self) -> EndpointTest:
        method, path, expected, name = "POST", "/v1/audio/transcribe", 200, "ถอดไฟล์เสียง (Typhoon)"
        with open(self._audio_path, "rb") as fh:
            audio_bytes = fh.read()
        inputs = [
            InputParam("file", f"{AUDIO_ASSET_NAME} ({len(audio_bytes):,} bytes)", "file"),
            InputParam("language", "th", "field"),
            InputParam("with_timestamps", "true", "field"),
            InputParam("model", "typhoon", "field"),
        ]
        specs = [
            ("status", "str"), ("text", "str"), ("duration_seconds", "num"),
            ("elapsed_seconds", "num"), ("rtf", "num"), ("timestamps", "list"),
        ]
        start = time.monotonic()
        try:
            status, body = await self._http.post_multipart(
                path,
                files={"file": (AUDIO_ASSET_NAME, audio_bytes, "audio/wav")},
                data={"language": "th", "with_timestamps": "true", "model": "typhoon"},
                headers=self._auth_headers(),
                timeout=120,
            )
            checks = self._check_fields(body, specs)
            if isinstance(body, dict):
                checks.append(_value_check("status==success", body.get("status") == "success", body.get("status")))
                checks.append(_value_check("text ไม่ว่าง", bool(body.get("text") and str(body["text"]).strip()), body.get("text")))
                checks.append(_value_check("duration_seconds>0", (body.get("duration_seconds") or 0) > 0, body.get("duration_seconds")))
                checks.append(_value_check("timestamps ไม่ว่าง", isinstance(body.get("timestamps"), list) and len(body["timestamps"]) > 0, body.get("timestamps")))
            passed = status == expected and all(c.passed for c in checks)
            return EndpointTest(method, path, name, status, passed,
                                time.monotonic() - start, inputs, checks)
        except Exception as e:  # noqa: BLE001
            return self._error_test(method, path, name, expected, inputs, specs, e)

    async def _test_audio_sync_diarize(self, lang: str = "th") -> EndpointTest:
        diar_model = "thai-whisper" if lang == "th" else "whisperx"
        engine_name = "Thai Whisper + PyAnnote" if lang == "th" else "WhisperX"
        method, path, expected, name = "POST", "/v1/audio/transcribe", 200, f"ถอดไฟล์เสียงพร้อมระบุผู้พูด ({engine_name})"
        with open(self._audio_path, "rb") as fh:
            audio_bytes = fh.read()
        inputs = [
            InputParam("file", f"{AUDIO_ASSET_NAME} ({len(audio_bytes):,} bytes)", "file"),
            InputParam("language", lang, "field"),
            InputParam("with_timestamps", "true", "field"),
            InputParam("enable_diarization", "true", "field"),
            InputParam("model", diar_model, "field"),
        ]
        specs = [
            ("status", "str"), ("text", "str"), ("duration_seconds", "num"),
            ("elapsed_seconds", "num"), ("rtf", "num"), ("timestamps", "list"),
        ]
        start = time.monotonic()
        try:
            status, body = await self._http.post_multipart(
                path,
                files={"file": (AUDIO_ASSET_NAME, audio_bytes, "audio/wav")},
                data={"language": lang, "with_timestamps": "true", "enable_diarization": "true", "model": diar_model},
                headers=self._auth_headers(),
                timeout=180,
            )
            checks = self._check_fields(body, specs)
            if isinstance(body, dict):
                checks.append(_value_check("status==success", body.get("status") == "success", body.get("status")))
                checks.append(_value_check("text ไม่ว่าง", bool(body.get("text") and str(body["text"]).strip()), body.get("text")))
                checks.append(_value_check("duration_seconds>0", (body.get("duration_seconds") or 0) > 0, body.get("duration_seconds")))
                ts = body.get("timestamps")
                checks.append(_value_check("timestamps ไม่ว่าง", isinstance(ts, list) and len(ts) > 0, ts))
                has_speaker = isinstance(ts, list) and any(item.get("speaker") for item in ts if isinstance(item, dict))
                checks.append(_value_check("พบ speaker ใน timestamps", has_speaker, ts[0].get("speaker") if ts and isinstance(ts[0], dict) else None))
            passed = status == expected and all(c.passed for c in checks)
            return EndpointTest(method, path, name, status, passed,
                                time.monotonic() - start, inputs, checks)
        except Exception as e:  # noqa: BLE001
            return self._error_test(method, path, name, expected, inputs, specs, e)

    # ------------------------------------------------------------- transcribe family

    async def _transcribe_family(
        self,
        cleanup: bool,
        push: Callable[[EndpointTest], Any],
        on_progress: Optional[Callable[[Dict[str, Any]], Any]],
    ) -> None:
        create_test, job_id = await self._transcribe_create()
        await push(create_test)

        await push(await self._transcribe_list())

        status_test, terminal = await self._transcribe_status(job_id, on_progress) if job_id \
            else (self._skipped_result("GET", "/v1/media/transcribe/jobs/{id}",
                                       "สถานะงานถอดความ (poll)", "ข้าม: สร้างงานไม่สำเร็จ"), None)
        await push(status_test)

        if terminal is not None:
            if status_test.passed:
                await push(await self._export_txt(job_id))
                await push(await self._export_srt(job_id))
                await push(await self._export_json(job_id))
            else:
                await push(self._skipped_result("GET", f"/v1/media/transcribe/jobs/{job_id}/export/txt",
                                                "Export .txt", "ข้าม: งานยังไม่สำเร็จ (completed)"))
                await push(self._skipped_result("GET", f"/v1/media/transcribe/jobs/{job_id}/export/srt",
                                                "Export .srt (คำบรรยาย)", "ข้าม: งานยังไม่สำเร็จ (completed)"))
                await push(self._skipped_result("GET", f"/v1/media/transcribe/jobs/{job_id}/export/json",
                                                "Export .json", "ข้าม: งานยังไม่สำเร็จ (completed)"))

        if cleanup and job_id:
            await push(await self._delete_transcribe(job_id))

    async def _transcribe_family_diarize(
        self,
        lang: str,
        cleanup: bool,
        push: Callable[[EndpointTest], Any],
        on_progress: Optional[Callable[[Dict[str, Any]], Any]],
    ) -> None:
        create_test, job_id = await self._transcribe_create_diarize(lang=lang)
        await push(create_test)

        await push(await self._transcribe_list())

        status_test, terminal = await self._transcribe_status(job_id, on_progress) if job_id \
            else (self._skipped_result("GET", "/v1/media/transcribe/jobs/{id}",
                                       "สถานะงานถอดความ (poll)", "ข้าม: สร้างงานไม่สำเร็จ"), None)
        await push(status_test)

        if terminal is not None:
            if status_test.passed:
                await push(await self._export_txt(job_id))
                await push(await self._export_srt(job_id))
                await push(await self._export_json(job_id))
            else:
                await push(self._skipped_result("GET", f"/v1/media/transcribe/jobs/{job_id}/export/txt",
                                                "Export .txt", "ข้าม: งานยังไม่สำเร็จ (completed)"))
                await push(self._skipped_result("GET", f"/v1/media/transcribe/jobs/{job_id}/export/srt",
                                                "Export .srt (คำบรรยาย)", "ข้าม: งานยังไม่สำเร็จ (completed)"))
                await push(self._skipped_result("GET", f"/v1/media/transcribe/jobs/{job_id}/export/json",
                                                "Export .json", "ข้าม: งานยังไม่สำเร็จ (completed)"))

        if cleanup and job_id:
            await push(await self._delete_transcribe(job_id))

    async def _transcribe_create(self) -> Tuple[EndpointTest, Optional[str]]:
        method, path, expected, name = "POST", "/v1/media/transcribe/jobs", 202, "สร้างงานถอดความยาว"
        with open(self._video_path, "rb") as fh:
            video_bytes = fh.read()
        inputs = [
            InputParam("file", f"{VIDEO_ASSET_NAME} ({len(video_bytes):,} bytes)", "file"),
            InputParam("language", "th", "field"),
        ]
        specs = [("status", "str"), ("id", "str"), ("filename", "str"),
                 ("language", "str"), ("message", "str")]
        start = time.monotonic()
        job_id: Optional[str] = None
        try:
            status, body = await self._http.post_multipart(
                path,
                files={"file": (VIDEO_ASSET_NAME, video_bytes, "video/mp4")},
                data={"language": "th"},
                headers=self._auth_headers(),
                timeout=60,
            )
            checks = self._check_fields(body, specs)
            if isinstance(body, dict):
                checks.append(_value_check("status==accepted", body.get("status") == "accepted", body.get("status")))
                checks.append(_value_check("language==th", body.get("language") == "th", body.get("language")))
                raw_id = body.get("id")
                job_id = raw_id.strip() if isinstance(raw_id, str) else None
                checks.append(_value_check("id ไม่ว่าง", bool(job_id), raw_id))
            passed = status == expected and all(c.passed for c in checks)
            return EndpointTest(method, path, name, status, passed,
                                time.monotonic() - start, inputs, checks), job_id
        except Exception as e:  # noqa: BLE001
            return self._error_test(method, path, name, expected, inputs, specs, e), None

    async def _transcribe_create_diarize(self, lang: str = "th") -> Tuple[EndpointTest, Optional[str]]:
        engine_name = "Typhoon + PyAnnote" if lang == "th" else "WhisperX"
        method, path, expected, name = "POST", "/v1/media/transcribe/jobs", 202, f"สร้างงานถอดความยาว ({engine_name})"
        with open(self._video_path, "rb") as fh:
            video_bytes = fh.read()
        inputs = [
            InputParam("file", f"{VIDEO_ASSET_NAME} ({len(video_bytes):,} bytes)", "file"),
            InputParam("language", lang, "field"),
            InputParam("enable_diarization", "true", "field"),
        ]
        specs = [("status", "str"), ("id", "str"), ("filename", "str"),
                 ("language", "str"), ("enable_diarization", "bool"), ("message", "str")]
        start = time.monotonic()
        job_id: Optional[str] = None
        try:
            status, body = await self._http.post_multipart(
                path,
                files={"file": (VIDEO_ASSET_NAME, video_bytes, "video/mp4")},
                data={"language": lang, "enable_diarization": "true"},
                headers=self._auth_headers(),
                timeout=60,
            )
            checks = self._check_fields(body, specs)
            if isinstance(body, dict):
                checks.append(_value_check("status==accepted", body.get("status") == "accepted", body.get("status")))
                checks.append(_value_check(f"language=={lang}", body.get("language") == lang, body.get("language")))
                checks.append(_value_check("enable_diarization==True", body.get("enable_diarization") is True, body.get("enable_diarization")))
                raw_id = body.get("id")
                job_id = raw_id.strip() if isinstance(raw_id, str) else None
                checks.append(_value_check("id ไม่ว่าง", bool(job_id), raw_id))
            passed = status == expected and all(c.passed for c in checks)
            return EndpointTest(method, path, name, status, passed,
                                time.monotonic() - start, inputs, checks), job_id
        except Exception as e:  # noqa: BLE001
            return self._error_test(method, path, name, expected, inputs, specs, e), None

    async def _transcribe_list(self) -> EndpointTest:
        return await self._list_test(
            "/v1/media/transcribe/jobs?limit=5&include_text=false",
            "รายการงานถอดความ",
            ["id", "filename", "status", "progress", "stage", "created_at"],
        )

    async def _transcribe_status(self, job_id: str, on_progress) -> Tuple[EndpointTest, Optional[Dict[str, Any]]]:
        method, path, expected, name = "GET", f"/v1/media/transcribe/jobs/{job_id}", 200, "สถานะงานถอดความ (poll)"
        specs = [
            ("id", "str"), ("type", "str"), ("filename", "str"), ("file_size_bytes", "int"),
            ("language", "str"), ("model", "any"), ("status", "str"), ("stage", "str"),
            ("progress", "num"), ("total_chunks", "int"), ("completed_chunks", "int"),
            ("duration", "num"), ("processing_time", "num"), ("target_chunk_sec", "num"),
            ("max_chunk_sec", "num"), ("result", "obj"), ("created_at", "str"),
            ("updated_at", "str"), ("started_at", "any"), ("completed_at", "any"),
        ]
        start = time.monotonic()
        terminal, wait_time = await self._poll_terminal(
            path, self._max_transcribe_wait, on_progress
        )
        if terminal is None:
            checks = [FieldCheck("status", "str", False, False, None,
                                 f"หมดเวลารอ ({int(self._max_transcribe_wait)}s) — งานยังไม่จบ")]
            return EndpointTest(method, path, name, 0, False, time.monotonic() - start,
                                [], checks, error_msg="หน้าที่รอสถานะหมดเวลา"), None

        checks = self._check_fields(terminal, specs)
        st = terminal.get("status")
        checks.append(_value_check("status เป็น terminal", st in TERMINAL_STATUSES, st))
        err = None
        if st == "completed":
            checks.append(_value_check("file_size_bytes>0", (terminal.get("file_size_bytes") or 0) > 0, terminal.get("file_size_bytes")))
            checks.append(_value_check("duration>0", (terminal.get("duration") or 0) > 0, terminal.get("duration")))
            result = terminal.get("result")
            result_ok = isinstance(result, dict) and bool(str(result.get("text") or "").strip())
            checks.append(_value_check("result.text ไม่ว่าง", result_ok, (result or {}).get("text") if isinstance(result, dict) else None))
        elif st == "failed":
            eobj = terminal.get("error")
            err = (eobj or {}).get("message") if isinstance(eobj, dict) else str(terminal.get("error"))
            checks.append(_value_check("งานสำเร็จ", False, st))
        else:
            checks.append(_value_check("งานสำเร็จ (completed)", st == "completed", st))

        passed = st == "completed" and all(c.passed for c in checks)
        if st == "failed":
            passed = False
        return EndpointTest(method, path, name, expected, passed, time.monotonic() - start,
                            [], checks, error_msg=err or ""), terminal

    async def _export_txt(self, job_id: str) -> EndpointTest:
        path = f"/v1/media/transcribe/jobs/{job_id}/export/txt"
        return await self._export_test(path, "Export .txt", "text")

    async def _export_srt(self, job_id: str) -> EndpointTest:
        path = f"/v1/media/transcribe/jobs/{job_id}/export/srt"
        return await self._export_test(path, "Export .srt (คำบรรยาย)", "text")

    async def _export_json(self, job_id: str) -> EndpointTest:
        path = f"/v1/media/transcribe/jobs/{job_id}/export/json"
        return await self._export_test(path, "Export .json", "json")

    async def _export_test(self, path: str, name_th: str, fmt: str) -> EndpointTest:
        method, expected = "GET", 200
        start = time.monotonic()
        try:
            status, body = await self._http.get(path, headers=self._auth_headers(), timeout=60)
            if fmt == "text":
                ok = status == expected and isinstance(body, str) and bool(body.strip())
                checks = [FieldCheck("body", "text", body is not None, ok,
                                     body[:80] + "…" if isinstance(body, str) and body else body,
                                     "" if ok else "body ไม่ใช่ข้อความหรือว่าง")]
            else:
                checks = self._check_fields(body, [("id", "str"), ("filename", "str"),
                                                   ("duration", "num"), ("text", "any")])
                if isinstance(body, dict):
                    checks.append(_value_check("text มีค่า", bool(str(body.get("text") or "").strip()), body.get("text")))
            passed = status == expected and all(c.passed for c in checks)
            return EndpointTest(method, path, name_th, status, passed,
                                time.monotonic() - start, [], checks)
        except Exception as e:  # noqa: BLE001
            return self._error_test(method, path, name_th, expected, [], [], e)

    async def _delete_transcribe(self, job_id: str) -> EndpointTest:
        method, path, expected, name = "DELETE", f"/v1/media/transcribe/jobs/{job_id}", 200, "ลบงานทดสอบถอดความ (cleanup)"
        specs = [("status", "str"), ("message", "str")]
        start = time.monotonic()
        try:
            status, body = await self._http.delete(path, headers=self._auth_headers(), timeout=60)
            checks = self._check_fields(body, specs)
            if isinstance(body, dict):
                checks.append(_value_check("status==success", body.get("status") == "success", body.get("status")))
            passed = status == expected and all(c.passed for c in checks)
            return EndpointTest(method, path, name, status, passed,
                                time.monotonic() - start, [], checks)
        except Exception as e:  # noqa: BLE001
            return self._error_test(method, path, name, expected, [], specs, e)

    # ------------------------------------------------------------- compress family

    async def _compress_family(
        self,
        cleanup: bool,
        push: Callable[[EndpointTest], Any],
        on_progress: Optional[Callable[[Dict[str, Any]], Any]],
    ) -> None:
        create_test, job_id = await self._compress_create()
        await push(create_test)

        await push(await self._compress_list())
        await push(await self._compress_retention())

        status_test, terminal = await self._compress_status(job_id, on_progress) if job_id \
            else (self._skipped_result("GET", "/v1/media/compress/jobs/{job_id}",
                                       "สถานะงานบีบอัด (poll)", "ข้าม: สร้างงานไม่สำเร็จ"), None)
        await push(status_test)

        if cleanup and job_id:
            await push(await self._delete_compress(job_id))

    async def _compress_create(self) -> Tuple[EndpointTest, Optional[str]]:
        method, path, expected, name = "POST", "/v1/media/compress/jobs", 202, "สร้างงานบีบอัดวิดีโอ"
        with open(self._video_path, "rb") as fh:
            video_bytes = fh.read()
        inputs = [
            InputParam("file", f"{VIDEO_ASSET_NAME} ({len(video_bytes):,} bytes)", "file"),
            InputParam("crf", str(COMPRESS_CRF), "field"),
            InputParam("preset", COMPRESS_PRESET, "field"),
            InputParam("encoder", COMPRESS_ENCODER, "field"),
            InputParam("target_width", "0 (ไม่ปรับขนาด)", "field"),
            InputParam("bitrate_kbps", "0 (ไม่จำกัด)", "field"),
        ]
        specs = [("status", "str"), ("job_id", "str"), ("filename", "str"),
                 ("queue_position", "int"), ("queue_length", "int"), ("message", "str")]
        start = time.monotonic()
        job_id: Optional[str] = None
        try:
            status, body = await self._http.post_multipart(
                path,
                files={"file": (VIDEO_ASSET_NAME, video_bytes, "video/mp4")},
                data={"crf": str(COMPRESS_CRF), "preset": COMPRESS_PRESET,
                      "encoder": COMPRESS_ENCODER, "target_width": "0", "bitrate_kbps": "0"},
                headers=self._auth_headers(),
                timeout=60,
            )
            checks = self._check_fields(body, specs)
            if isinstance(body, dict):
                checks.append(_value_check("status==accepted", body.get("status") == "accepted", body.get("status")))
                raw_id = body.get("job_id")
                job_id = raw_id.strip() if isinstance(raw_id, str) else None
                checks.append(_value_check("job_id ไม่ว่าง", bool(job_id), raw_id))
            passed = status == expected and all(c.passed for c in checks)
            return EndpointTest(method, path, name, status, passed,
                                time.monotonic() - start, inputs, checks), job_id
        except Exception as e:  # noqa: BLE001
            return self._error_test(method, path, name, expected, inputs, specs, e), None

    async def _compress_list(self) -> EndpointTest:
        return await self._list_test(
            "/v1/media/compress/jobs?limit=5",
            "รายการงานบีบอัด",
            ["job_id", "filename", "status", "progress_pct", "current_stage", "created_at"],
        )

    async def _compress_retention(self) -> EndpointTest:
        method, path, expected, name = "GET", "/v1/media/compress/retention", 200, "ข้อมูล retention การบีบอัด"
        specs = [("retention_hours", "num"), ("last_cleanup_at", "any"), ("last_cleanup_count", "int")]
        start = time.monotonic()
        try:
            status, body = await self._http.get(path, headers=self._auth_headers(), timeout=30)
            checks = self._check_fields(body, specs)
            if isinstance(body, dict):
                checks.append(_value_check("retention_hours>0", (body.get("retention_hours") or 0) > 0, body.get("retention_hours")))
            passed = status == expected and all(c.passed for c in checks)
            return EndpointTest(method, path, name, status, passed,
                                time.monotonic() - start, [], checks)
        except Exception as e:  # noqa: BLE001
            return self._error_test(method, path, name, expected, [], specs, e)

    async def _compress_status(self, job_id: str, on_progress) -> Tuple[EndpointTest, Optional[Dict[str, Any]]]:
        method, path, expected, name = "GET", f"/v1/media/compress/jobs/{job_id}", 200, "สถานะงานบีบอัด (poll)"
        specs = [
            ("job_id", "str"), ("filename", "str"), ("file_size_bytes", "int"), ("status", "str"),
            ("progress_pct", "num"), ("current_stage", "str"), ("target_width", "int"),
            ("bitrate_kbps", "int"), ("crf", "int"), ("preset", "str"), ("encoder", "str"),
            ("trim_start", "num"), ("trim_end", "num"), ("audio_extract_format", "str"),
            ("input_width", "int"), ("input_height", "int"), ("duration_seconds", "num"),
            ("output_path", "str"), ("output_size_bytes", "int"), ("output_width", "int"),
            ("output_height", "int"), ("elapsed_seconds", "num"), ("queue_position", "int"),
            ("queue_length", "int"), ("audio_extract_path", "any"), ("audio_extract_size_bytes", "int"),
            ("audio_exists", "bool"), ("error_message", "any"), ("created_at", "str"),
            ("updated_at", "str"),
        ]
        start = time.monotonic()
        terminal, wait_time = await self._poll_terminal(
            path, self._max_compress_wait, on_progress
        )
        if terminal is None:
            checks = [FieldCheck("status", "str", False, False, None,
                                 f"หมดเวลารอ ({int(self._max_compress_wait)}s) — งานยังไม่จบ")]
            return EndpointTest(method, path, name, 0, False, time.monotonic() - start,
                                [], checks, error_msg="หน้าที่รอสถานะหมดเวลา"), None

        checks = self._check_fields(terminal, specs)
        st = terminal.get("status")
        checks.append(_value_check("status เป็น terminal", st in TERMINAL_STATUSES, st))
        err = terminal.get("error_message") or ""
        if st == "completed":
            checks.append(_value_check("file_size_bytes>0", (terminal.get("file_size_bytes") or 0) > 0, terminal.get("file_size_bytes")))
            checks.append(_value_check("input_width>0", (terminal.get("input_width") or 0) > 0, terminal.get("input_width")))
            checks.append(_value_check("input_height>0", (terminal.get("input_height") or 0) > 0, terminal.get("input_height")))
            checks.append(_value_check("duration_seconds>0", (terminal.get("duration_seconds") or 0) > 0, terminal.get("duration_seconds")))
            checks.append(_value_check("output_path มีค่า", bool(str(terminal.get("output_path") or "").strip()), terminal.get("output_path")))
            checks.append(_value_check("output_size_bytes>0", (terminal.get("output_size_bytes") or 0) > 0, terminal.get("output_size_bytes")))
            checks.append(_value_check("output_width>0", (terminal.get("output_width") or 0) > 0, terminal.get("output_width")))
            checks.append(_value_check("output_height>0", (terminal.get("output_height") or 0) > 0, terminal.get("output_height")))
        else:
            checks.append(_value_check("งานสำเร็จ (completed)", st == "completed", st))

        passed = st == "completed" and all(c.passed for c in checks)
        return EndpointTest(method, path, name, expected, passed, time.monotonic() - start,
                            [], checks, error_msg=err or ""), terminal

    async def _delete_compress(self, job_id: str) -> EndpointTest:
        method, path, expected, name = "DELETE", f"/v1/media/compress/jobs/{job_id}", 200, "ลบงานทดสอบบีบอัด (cleanup)"
        specs = [("status", "str"), ("message", "str")]
        start = time.monotonic()
        try:
            status, body = await self._http.delete(path, headers=self._auth_headers(), timeout=60)
            checks = self._check_fields(body, specs)
            if isinstance(body, dict):
                checks.append(_value_check("status==success", body.get("status") == "success", body.get("status")))
            passed = status == expected and all(c.passed for c in checks)
            return EndpointTest(method, path, name, status, passed,
                                time.monotonic() - start, [], checks)
        except Exception as e:  # noqa: BLE001
            return self._error_test(method, path, name, expected, [], specs, e)

    # ------------------------------------------------------------- shared helpers

    def _expected_total(self, cleanup: bool, suite: str = "typhoon") -> int:
        """Predicted test count assuming the async job creates succeed."""
        if suite == "typhoon":
            n = 2
            n += 6
            n += 1 if cleanup else 0
            n += 4
            n += 1 if cleanup else 0
            return n
        elif suite in ("pyannote", "whisperx"):
            # health (1) + audio sync diarize (1) + create (1) + list (1) + status (1) + export txt (1) + export srt (1) + export json (1) + cleanup (1 if cleanup else 0)
            return 8 + (1 if cleanup else 0)
        return 2 + 6 + (1 if cleanup else 0) + 4 + (1 if cleanup else 0)

    def _auth_headers(self) -> Dict[str, str]:
        return {"x-api-key": self._api_key} if self._api_key else {}

    async def _poll_terminal(self, path: str, max_wait: float, on_progress) -> Tuple[Optional[Dict[str, Any]], float]:
        start = time.monotonic()
        while time.monotonic() - start < max_wait:
            status_code, body = await self._http.get(path, headers=self._auth_headers(), timeout=60)
            if status_code == 200 and isinstance(body, dict):
                st = body.get("status")
                if st in TERMINAL_STATUSES:
                    return body, time.monotonic() - start
                if on_progress is not None:
                    await on_progress({
                        "path": path,
                        "status": st or str(status_code),
                        "progress": body.get("progress") if "progress" in body else body.get("progress_pct"),
                        "stage": body.get("stage") or body.get("current_stage") or "",
                    })
            await asyncio.sleep(self._poll_interval)
        return None, time.monotonic() - start

    async def _list_test(self, path: str, name_th: str, row_keys: List[str]) -> EndpointTest:
        method, expected = "GET", 200
        start = time.monotonic()
        try:
            status, body = await self._http.get(path, headers=self._auth_headers(), timeout=30)
            checks = _list_row_checks(body, row_keys)
            passed = status == expected and all(c.passed for c in checks)
            return EndpointTest(method, path, name_th, status, passed,
                                time.monotonic() - start, [], checks)
        except Exception as e:  # noqa: BLE001
            return self._error_test(method, path, name_th, expected, [], [], e)

    def _skipped_result(self, method, path, name_th, reason) -> EndpointTest:
        return EndpointTest(method, path, name_th, 0, False, 0.0, [],
                            [FieldCheck("status", "str", False, False, None, reason)],
                            error_msg=reason)

    def _check_fields(self, body, specs) -> List[FieldCheck]:
        return _check_fields(body, specs, _TYPE_PREDICATES)

    def _error_test(self, method, path, name_th, expected, inputs, specs, exc) -> EndpointTest:
        checks = [FieldCheck(n, t, False, False, None, f"request error: {exc}") for n, t in specs]
        return EndpointTest(method, path, name_th, 0, False, 0.0, inputs,
                            checks, error_msg=str(exc))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _value_check(label: str, ok: bool, val: Any) -> FieldCheck:
    return FieldCheck(label, "value", val is not None or bool(ok), bool(ok), val,
                      "" if ok else f"rule ผิด: {label}")


def _check_fields(body: Optional[Any], specs, type_preds) -> List[FieldCheck]:
    if body is None or not isinstance(body, dict):
        return [FieldCheck(name, type_code, False, False, None, "response ไม่ใช่ JSON object")
                for name, type_code in specs]
    checks: List[FieldCheck] = []
    for name, type_code in specs:
        present = name in body
        val = body.get(name)
        ok = type_preds[type_code](val) if present else False
        note = "" if ok else ("field ไม่พบ" if not present else f"type ไม่ถูก (ได้ {type(val).__name__})")
        checks.append(FieldCheck(name, type_code, present, ok, val if present else None, note))
    return checks


def _list_row_checks(body: Optional[Any], row_keys: List[str]) -> List[FieldCheck]:
    if not isinstance(body, (list, tuple)):
        checks = [FieldCheck("array", "list", False, False, None, "response ไม่ใช่ array")]
        checks += [FieldCheck(f"row.{k}", "present", False, False, None, "response ไม่ใช่ array") for k in row_keys]
        return checks
    checks = [FieldCheck("array", "list", True, len(body) > 0, len(body), "" if body else "array ว่าง")]
    if not body:
        return checks
    first = body[0]
    row_ok = isinstance(first, dict)
    for key in row_keys:
        present = row_ok and key in first
        val = first.get(key) if present else None
        checks.append(FieldCheck(f"row.{key}", "present", present, present, val,
                                 "" if present else f"field '{key}' ไม่พบในรายการ"))
    return checks