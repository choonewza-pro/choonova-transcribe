"""
ApiTestRunner — orchestrates the automated API endpoint self-test.

Exercise the running service's own HTTP endpoints (audio transcribe jobs with
word-level and/or speaker detection) using the sample audio asset shipped in
`assets/`, and produce a field-by-field pass/fail report.

Design notes:
- Four suites are supported:
    'word-diar' (audio job, word-level + speaker, thai-whisper / whisperx),
    'word-only' (audio job, word-level only, thai-whisper / whisper),
    'no-word'   (audio job, no word-level / no speaker, typhoon / thai-whisper / whisper),
    'sync'      (synchronous /v1/audio/transcribe, word-level + speaker across
                 thai-whisper / whisper / typhoon — verifies the response
                 `segments` field).
- Async jobs are polled via GET status until a terminal status; the wait is
  bounded by configurable max-wait seconds. Cleanup DELETE always runs so a
  failed or timed-out job leaves no residue.
- All self-requests are authenticated server-side with GATEWAY_API_KEY (the
  injected ApiHttpPort carries it), so the middleware, validation, and auth
  stack are exercised for real.

This class knows only the domain entities and the ApiHttpPort — no FastAPI,
no httpx, no framework outside reading the sample asset file from disk.
"""

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.config import (
    APITEST_POLL_INTERVAL_SEC,
    APITEST_TRANSCRIBE_MAX_WAIT_SEC,
)
from app.modules.apitest.domain.entities import (
    ApiTestReport,
    EndpointTest,
    FieldCheck,
    InputParam,
)
from app.modules.apitest.domain.ports import ApiHttpPort

AUDIO_ASSET_NAME = "test-audio-th.wav"

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

    # (model, lang, with_timestamps, enable_diarization, expect_words, expect_speaker)
    SYNC_MODELS = (
        ("thai-whisper", "th", True, True, True, True),
        ("thai-whisper", "th", True, False, True, False),
        ("whisper", "th", True, False, True, False),
        ("typhoon", "th", False, False, False, False),
    )

    def __init__(
        self,
        http: ApiHttpPort,
        assets_dir: str,
        max_transcribe_wait: Optional[float] = None,
        poll_interval: Optional[float] = None,
        api_key: str = "",
    ):
        self._http = http
        self._api_key = api_key
        self._assets_dir = assets_dir
        self._audio_path = os.path.join(assets_dir, AUDIO_ASSET_NAME)
        self._max_transcribe_wait = (
            float(max_transcribe_wait)
            if max_transcribe_wait is not None
            else float(APITEST_TRANSCRIBE_MAX_WAIT_SEC)
        )
        self._poll_interval = (
            float(poll_interval)
            if poll_interval is not None
            else float(APITEST_POLL_INTERVAL_SEC)
        )

    # ------------------------------------------------------------- assets

    def check_assets(self) -> None:
        """Raise AssetNotFoundError if the sample audio asset is missing on disk."""
        if not os.path.isfile(self._audio_path):
            raise AssetNotFoundError(
                f"ไม่พบไฟล์ทดสอบในโฟลเดอร์ assets/: {AUDIO_ASSET_NAME} (ควรอยู่ที่ {self._assets_dir})"
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
            },
        }

    async def run(
        self,
        suite: str = "word-diar",
        cleanup: bool = True,
        on_test: Optional[Callable[[EndpointTest], Any]] = None,
        on_progress: Optional[Callable[[Dict[str, Any]], Any]] = None,
        on_start: Optional[Callable[[int], Any]] = None,
    ) -> ApiTestReport:
        """Run the selected self-test suite and return the aggregated report.

        suite options:
          - 'word-diar': audio-job word-level + speaker detection (thai-whisper, whisperx)
          - 'word-only': audio-job word-level, no diarization (thai-whisper, whisper)
          - 'no-word': audio-job no word-level, no diarization (typhoon, thai-whisper, whisper)
          - 'sync': synchronous /v1/audio/transcribe word-level + speaker (thai-whisper, whisper, typhoon)
        """
        self.check_assets()
        report = ApiTestReport(started_at=_now_iso())

        suite = (suite or "word-diar").lower().strip()
        if suite not in ("word-diar", "word-only", "no-word", "sync"):
            suite = "word-diar"

        if on_start is not None:
            await on_start(self._expected_total(cleanup, suite=suite))

        async def push(test: EndpointTest) -> None:
            test.order = len(report.tests) + 1
            report.tests.append(test)
            if on_test is not None:
                await on_test(test)

        try:
            if suite == "word-diar":
                if not self._diarization_enabled():
                    raise ValueError(
                        "Speaker Diarization is disabled on this server "
                        "(DIARIZATION_ENABLED=false). Cannot run the 'word-diar' suite."
                    )
                await self._audio_word_family(
                    models=(("thai-whisper", "th"), ("whisperx", "auto")),
                    with_timestamps=True, enable_diarization=True, expect_words=True,
                    expect_speaker=True,
                    cleanup=cleanup, push=push, on_progress=on_progress,
                )
            elif suite == "word-only":
                await self._audio_word_family(
                    models=(("thai-whisper", "th"), ("whisper", "th")),
                    with_timestamps=True, enable_diarization=False, expect_words=True,
                    expect_speaker=False,
                    cleanup=cleanup, push=push, on_progress=on_progress,
                )
            elif suite == "no-word":
                await self._audio_word_family(
                    models=(("typhoon", "th"), ("thai-whisper", "th"), ("whisper", "th")),
                    with_timestamps=False, enable_diarization=False, expect_words=False,
                    expect_speaker=False,
                    cleanup=cleanup, push=push, on_progress=on_progress,
                )
            elif suite == "sync":
                await self._sync_family(
                    models=self._sync_models(),
                    push=push,
                )
        finally:
            report.finished_at = _now_iso()
        return report

    # ------------------------------------------------------------- diarization availability

    @staticmethod
    def _diarization_enabled() -> bool:
        """Current speaker-diarization master switch (DIARIZATION_ENABLED)."""
        from app.config import DIARIZATION_ENABLED
        return DIARIZATION_ENABLED

    def _sync_models(self):
        """Sync-suite cards; diarization cards are dropped when the switch is off."""
        if self._diarization_enabled():
            return list(self.SYNC_MODELS)
        return [m for m in self.SYNC_MODELS if not m[3]]

    # ------------------------------------------------------------- audio word-level job family

    async def _audio_word_family(
        self,
        models,
        with_timestamps: bool,
        enable_diarization: bool,
        expect_words: bool,
        expect_speaker: bool,
        cleanup: bool,
        push: Callable[[EndpointTest], Any],
        on_progress: Optional[Callable[[Dict[str, Any]], Any]],
    ) -> None:
        """For each (model, lang): create an audio job, poll status, verify the
        presence/absence of word-level data in result.segments, then cleanup."""
        for model, lang in models:
            create_test, job_id = await self._audio_job_create(
                model, lang, with_timestamps, enable_diarization
            )
            await push(create_test)

            status_test, terminal = await self._audio_job_status(
                job_id, expect_words, expect_speaker, on_progress
            ) if job_id else (self._skipped_result(
                "GET", "/v1/media/transcribe/jobs/{id}",
                "สถานะงานถอดความ (poll)", "ข้าม: สร้างงานไม่สำเร็จ"), None)
            await push(status_test)

            if cleanup and job_id:
                await push(await self._delete_transcribe(job_id))

    async def _audio_job_create(
        self,
        model: str,
        lang: str,
        with_timestamps: bool,
        enable_diarization: bool,
    ) -> Tuple[EndpointTest, Optional[str]]:
        method, path, expected, name = "POST", "/v1/audio/transcribe/jobs", 202, \
            f"สร้างงานถอดเสียง word-level (model={model})"
        with open(self._audio_path, "rb") as fh:
            audio_bytes = fh.read()
        inputs = [
            InputParam("file", f"{AUDIO_ASSET_NAME} ({len(audio_bytes):,} bytes)", "file"),
            InputParam("language", lang, "field"),
            InputParam("model", model, "field"),
            InputParam("with_timestamps", str(with_timestamps).lower(), "field"),
            InputParam("enable_diarization", str(enable_diarization).lower(), "field"),
        ]
        specs = [("status", "str"), ("id", "str"), ("filename", "str"),
                 ("language", "str"), ("model", "any"), ("enable_diarization", "bool"),
                 ("message", "str")]
        start = time.monotonic()
        job_id: Optional[str] = None
        try:
            status, body = await self._http.post_multipart(
                path,
                files={"file": (AUDIO_ASSET_NAME, audio_bytes, "audio/wav")},
                data={
                    "language": lang,
                    "model": model,
                    "with_timestamps": str(with_timestamps).lower(),
                    "enable_diarization": str(enable_diarization).lower(),
                },
                headers=self._auth_headers(),
                timeout=60,
            )
            checks = self._check_fields(body, specs)
            if isinstance(body, dict):
                checks.append(_value_check("status==accepted", body.get("status") == "accepted", body.get("status")))
                checks.append(_value_check(f"language=={lang}", body.get("language") == lang, body.get("language")))
                checks.append(_value_check("enable_diarization ตรง", body.get("enable_diarization") is enable_diarization, body.get("enable_diarization")))
                raw_id = body.get("id")
                job_id = raw_id.strip() if isinstance(raw_id, str) else None
                checks.append(_value_check("id ไม่ว่าง", bool(job_id), raw_id))
            passed = status == expected and all(c.passed for c in checks)
            return EndpointTest(method, path, name, status, passed,
                                time.monotonic() - start, inputs, checks), job_id
        except Exception as e:  # noqa: BLE001
            return self._error_test(method, path, name, expected, inputs, specs, e), None

    async def _audio_job_status(
        self,
        job_id: str,
        expect_words: bool,
        expect_speaker: bool,
        on_progress,
    ) -> Tuple[EndpointTest, Optional[Dict[str, Any]]]:
        method, path, expected, name = "GET", f"/v1/media/transcribe/jobs/{job_id}", 200, \
            "สถานะงานถอดความ word-level (poll)"
        specs = [
            ("id", "str"), ("type", "str"), ("filename", "str"), ("file_size_bytes", "int"),
            ("language", "str"), ("model", "any"), ("status", "str"), ("stage", "str"),
            ("progress", "num"), ("duration", "num"), ("result", "obj"), ("created_at", "str"),
            ("updated_at", "str"),
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
        err = ""
        if st == "completed":
            result = terminal.get("result")
            segments = result.get("segments") if isinstance(result, dict) else None
            has_words = self._segments_have_words(segments)
            has_speaker = self._segments_have_speaker(segments)
            if expect_words:
                checks.append(_value_check("segments ไม่ว่าง", isinstance(segments, list) and len(segments) > 0, segments))
                checks.append(_value_check("มี word-level data (word/text)", has_words, segments))
                if expect_speaker:
                    checks.append(_value_check("มี speaker ใน segments", has_speaker, segments))
            else:
                checks.append(_value_check("ไม่มี word-level data", not has_words, segments))
        elif st == "failed":
            eobj = terminal.get("error")
            err = (eobj or {}).get("message") if isinstance(eobj, dict) else str(terminal.get("error"))
            checks.append(_value_check("งานสำเร็จ", False, st))
        else:
            checks.append(_value_check("งานสำเร็จ (completed)", st == "completed", st))

        passed = st == "completed" and all(c.passed for c in checks)
        return EndpointTest(method, path, name, expected, passed, time.monotonic() - start,
                            [], checks, error_msg=err or ""), terminal

    def _segments_have_words(self, segments) -> bool:
        """True when result.segments carries word-level data.

        Word-level data is exposed as `word`/`text` fields on each segment
        (TranscriptionSegment schema syncs word<->text); nested `words` arrays
        are stripped by response serialization, so they are not checked here.
        """
        if not isinstance(segments, list) or not segments:
            return False
        for seg in segments:
            if not isinstance(seg, dict):
                return False
            val = seg.get("word") or seg.get("text")
            if not val or not str(val).strip():
                return False
        return True

    def _segments_have_speaker(self, segments) -> bool:
        """True when at least one segment carries a non-empty speaker label."""
        if not isinstance(segments, list) or not segments:
            return False
        for seg in segments:
            if isinstance(seg, dict) and str(seg.get("speaker") or "").strip():
                return True
        return False

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

    # ------------------------------------------------------------- sync /v1/audio/transcribe family

    async def _sync_family(
        self,
        models,
        push: Callable[[EndpointTest], Any],
    ) -> None:
        """POST /v1/audio/transcribe synchronously per model and verify the
        response `segments` field (word-level data / speaker labels)."""
        for model, lang, with_timestamps, enable_diarization, expect_words, expect_speaker in models:
            await push(await self._sync_transcribe(
                model, lang, with_timestamps, enable_diarization,
                expect_words, expect_speaker,
            ))

    async def _sync_transcribe(
        self,
        model: str,
        lang: str,
        with_timestamps: bool,
        enable_diarization: bool,
        expect_words: bool,
        expect_speaker: bool,
    ) -> EndpointTest:
        method, path, expected, name = "POST", "/v1/audio/transcribe", 200, \
            f"ถอดเสียงทันที word-level (model={model})"
        with open(self._audio_path, "rb") as fh:
            audio_bytes = fh.read()
        inputs = [
            InputParam("file", f"{AUDIO_ASSET_NAME} ({len(audio_bytes):,} bytes)", "file"),
            InputParam("language", lang, "field"),
            InputParam("model", model, "field"),
            InputParam("with_timestamps", str(with_timestamps).lower(), "field"),
            InputParam("enable_diarization", str(enable_diarization).lower(), "field"),
        ]
        specs = [
            ("status", "str"), ("text", "str"), ("duration_seconds", "num"),
            ("elapsed_seconds", "num"), ("rtf", "num"), ("segments", "any"),
            ("model", "any"),
        ]
        # Diarization runs a full ASR + PyAnnote pass synchronously in the
        # worker subprocess — allow generous room beyond the default 60s.
        request_timeout = 180.0 if enable_diarization else 90.0
        start = time.monotonic()
        try:
            status, body = await self._http.post_multipart(
                path,
                files={"file": (AUDIO_ASSET_NAME, audio_bytes, "audio/wav")},
                data={
                    "language": lang,
                    "model": model,
                    "with_timestamps": str(with_timestamps).lower(),
                    "enable_diarization": str(enable_diarization).lower(),
                },
                headers=self._auth_headers(),
                timeout=request_timeout,
            )
            checks = self._check_fields(body, specs)
            if isinstance(body, dict):
                checks.append(_value_check(
                    "status==success", body.get("status") == "success", body.get("status")))
                segments = body.get("segments")
                has_words = self._segments_have_words(segments)
                has_speaker = self._segments_have_speaker(segments)
                if expect_words:
                    checks.append(_value_check("segments มี word-level data", has_words, segments))
                    if expect_speaker:
                        checks.append(_value_check("มี speaker ใน segments", has_speaker, segments))
                else:
                    checks.append(_value_check("ไม่มี word-level data", not has_words, segments))
            passed = status == expected and all(c.passed for c in checks)
            return EndpointTest(method, path, name, status, passed,
                                time.monotonic() - start, inputs, checks)
        except Exception as e:  # noqa: BLE001
            return self._error_test(method, path, name, expected, inputs, specs, e)

    # ------------------------------------------------------------- shared helpers

    def _expected_total(self, cleanup: bool, suite: str = "word-diar") -> int:
        """Predicted test count assuming the async job creates succeed."""
        if suite == "sync":
            # N model cards × sync transcribe request (no cleanup)
            return len(self._sync_models())
        if suite == "no-word":
            # 3 models × (create + status + cleanup)
            return 9 if cleanup else 6
        # word-diar / word-only: 2 models × (create + status + cleanup)
        return 6 if cleanup else 4

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