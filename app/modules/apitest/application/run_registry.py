"""
In-memory registry for API Endpoint Self-Test runs.

A self-test run is owned by the server (a detached background task), not by
the HTTP request that started it, so a page refresh / browser disconnect can
never lose the run or its results. This registry keeps the run state and
accumulated results queryable via polling endpoints.

The registry is process-local and event-loop safe (all mutations happen inside
the single uvicorn event loop, so no locks are needed). Runs are kept at most
``MAX_RUNS``; the oldest finished run is evicted first (never the active one).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

MAX_RUNS = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunState:
    """Mutable snapshot of one self-test run, readable by the polling API."""

    run_id: str
    suite: str
    cleanup: bool = True
    status: str = "running"  # 'running' | 'completed' | 'failed'
    started_at: str = ""
    finished_at: Optional[str] = None
    expected_total: Optional[int] = None
    tests: List[Dict[str, Any]] = field(default_factory=list)
    latest_progress: Optional[Dict[str, Any]] = None
    summary: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.started_at:
            self.started_at = _now_iso()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "suite": self.suite,
            "cleanup": self.cleanup,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "expected_total": self.expected_total,
            "tests": self.tests,
            "latest_progress": self.latest_progress,
            "summary": self.summary,
            "error": self.error,
        }


class RunRegistry:
    """Process-local store of self-test runs (newest first, capped)."""

    def __init__(self, max_runs: int = MAX_RUNS):
        self._max_runs = max_runs
        self._runs: Dict[str, RunState] = {}
        self._active_run_id: Optional[str] = None

    # ------------------------------------------------------------- lifecycle

    def start(self, run_id: str, suite: str, cleanup: bool = True) -> RunState:
        state = RunState(run_id=run_id, suite=suite, cleanup=cleanup)
        self._runs[run_id] = state
        self._active_run_id = run_id
        self._evict_if_needed(protect=run_id)
        return state

    def finish(self, run_id: str, summary: Optional[Dict[str, Any]] = None,
               error: Optional[str] = None) -> Optional[RunState]:
        state = self._runs.get(run_id)
        if state is None:
            return None
        state.finished_at = _now_iso()
        if error is not None:
            state.status = "failed"
            state.error = error
        else:
            state.status = "completed"
            state.summary = summary
        if self._active_run_id == run_id:
            self._active_run_id = None
        return state

    # ------------------------------------------------------------- queries

    def active_run(self) -> Optional[RunState]:
        if self._active_run_id is None:
            return None
        return self._runs.get(self._active_run_id)

    def get(self, run_id: str) -> Optional[RunState]:
        return self._runs.get(run_id)

    def list(self, limit: int = MAX_RUNS) -> List[RunState]:
        runs = sorted(self._runs.values(), key=lambda r: r.started_at, reverse=True)
        return runs[:limit]

    # ------------------------------------------------------------- recording

    def set_expected_total(self, run_id: str, total: int) -> None:
        state = self._runs.get(run_id)
        if state is not None:
            state.expected_total = int(total)

    def record_test(self, run_id: str, test: Dict[str, Any]) -> None:
        state = self._runs.get(run_id)
        if state is not None:
            state.tests.append(test)

    def record_progress(self, run_id: str, progress: Dict[str, Any]) -> None:
        state = self._runs.get(run_id)
        if state is not None:
            state.latest_progress = progress

    # ------------------------------------------------------------- internal

    def _evict_if_needed(self, protect: Optional[str] = None) -> None:
        """Drop the oldest finished run(s) once the store exceeds the cap."""
        while len(self._runs) > self._max_runs:
            candidates = [
                r for r in self._runs.values()
                if r.run_id != protect and r.status != "running"
            ]
            if not candidates:
                return
            oldest = min(candidates, key=lambda r: r.started_at)
            self._runs.pop(oldest.run_id, None)


# Module-level singleton shared by the router and the background runner.
run_registry = RunRegistry()