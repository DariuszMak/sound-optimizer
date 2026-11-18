from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ProcessingState:
    """Pure data model for tracking audio processing progress."""

    total: int = 0
    done: int = 0
    ok: int = 0
    skipped: int = 0
    failed: int = 0
    started: float = field(default_factory=time.monotonic)
    workers: dict[int, tuple[str, int, str, str]] = field(default_factory=dict)

    @property
    def fraction(self) -> float:
        if self.total == 0:
            return 1.0
        return self.done / self.total

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    @property
    def eta(self) -> float:
        if self.done == 0:
            return 0.0
        return (self.elapsed / self.done) * (self.total - self.done)

    def apply(self, message: tuple) -> None:
        if message[0] == "step":
            _, worker_id, file_name, step, description, details = message
            self.workers[worker_id] = (file_name, step, description, details)
        elif message[0] == "done":
            _, worker_id, file_name, status = message
            self.workers.pop(worker_id, None)
            self.done += 1
            if status == "ok":
                self.ok += 1
            elif status == "skipped":
                self.skipped += 1
            elif status == "failed":
                self.failed += 1
