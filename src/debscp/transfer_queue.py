from __future__ import annotations

import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class TransferState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(slots=True)
class TransferJob:
    label: str
    operation: Callable[[Callable[[int, int], None]], None]
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: TransferState = TransferState.QUEUED
    transferred: int = 0
    total: int = 0
    error: str | None = None


class TransferQueue:
    """A single-worker queue; SFTP clients are intentionally not shared concurrently."""

    def __init__(self, on_update: Callable[[TransferJob], None] | None = None) -> None:
        self.jobs: dict[str, TransferJob] = {}
        self._queue: queue.Queue[TransferJob | None] = queue.Queue()
        self._on_update = on_update or (lambda _job: None)
        self._worker = threading.Thread(target=self._run, name="debscp-transfers", daemon=True)
        self._worker.start()

    def submit(self, job: TransferJob) -> str:
        self.jobs[job.id] = job
        self._queue.put(job)
        self._notify(job)
        return job.id

    def shutdown(self) -> None:
        self._queue.put(None)
        self._worker.join(timeout=5)

    def _notify(self, job: TransferJob) -> None:
        self._on_update(job)

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            job.state = TransferState.RUNNING
            self._notify(job)
            current_job = job

            def progress(transferred: int, total: int, bound_job: TransferJob = current_job) -> None:
                bound_job.transferred, bound_job.total = transferred, total
                self._notify(bound_job)

            try:
                job.operation(progress)
            except Exception as exc:  # noqa: BLE001 - worker boundary records operation failures
                job.state = TransferState.FAILED
                job.error = str(exc)
            else:
                job.state = TransferState.COMPLETE
            self._notify(job)
