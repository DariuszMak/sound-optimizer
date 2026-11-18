from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import cast


@dataclass
class ProcessingState:
    total: int = 0
    done: int = 0
    ok: int = 0
    skipped: int = 0
    failed: int = 0
    started: float = field(default_factory=time.monotonic)
    workers: dict[int, tuple[str, int, str, str]] = field(default_factory=dict)
    paused_at: float | None = None
    paused_duration: float = 0.0

    @property
    def fraction(self) -> float:
        return 1.0 if self.total == 0 else self.done / self.total

    @property
    def elapsed(self) -> float:
        now = self.paused_at if self.paused_at is not None else time.monotonic()
        return now - self.started - self.paused_duration

    @property
    def eta(self) -> float:
        return 0.0 if self.done == 0 else (self.elapsed / self.done) * (self.total - self.done)

    @property
    def is_paused(self) -> bool:
        return self.paused_at is not None

    def pause(self) -> None:
        if self.paused_at is None:
            self.paused_at = time.monotonic()

    def resume(self) -> None:
        if self.paused_at is not None:
            self.paused_duration += time.monotonic() - self.paused_at
            self.paused_at = None

    def apply(self, message: tuple[object, ...]) -> None:
        if message[0] == "step":
            _, worker_id, file_name, step, description, details = message
            self.workers[int(cast("int", worker_id))] = (
                str(file_name),
                int(cast("int", step)),
                str(description),
                str(details),
            )
        elif message[0] == "done":
            _, worker_id, _file_name, status = message
            self.workers.pop(int(cast("int", worker_id)), None)
            self.done += 1
            if status == "ok":
                self.ok += 1
            elif status == "skipped":
                self.skipped += 1
            elif status == "failed":
                self.failed += 1
