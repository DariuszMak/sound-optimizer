from __future__ import annotations

import time

from src.frontend.processing.processing_state import ProcessingState


def test_processing_state_default_values() -> None:
    state = ProcessingState()
    assert state.total == 0
    assert state.done == 0
    assert state.ok == 0
    assert state.skipped == 0
    assert state.failed == 0
    assert abs(state.fraction - 1.0) < 1e-9
    assert state.workers == {}


def test_processing_state_fraction() -> None:
    state = ProcessingState(total=10, done=5)
    assert abs(state.fraction - 0.5) < 1e-9


def test_processing_state_fraction_zero_total() -> None:
    state = ProcessingState(total=0)
    assert abs(state.fraction - 1.0) < 1e-9


def test_processing_state_elapsed() -> None:
    import time

    state = ProcessingState()
    time.sleep(0.05)
    assert state.elapsed >= 0.04


def test_processing_state_eta() -> None:
    state = ProcessingState(total=10, done=5, started=time.monotonic() - 10)
    assert state.eta >= 10


def test_processing_state_eta_zero_done() -> None:
    state = ProcessingState(total=10, done=0)
    assert state.eta == 0


def test_processing_state_apply_step() -> None:
    state = ProcessingState(total=5)
    state.apply(("step", 0, "file.wav", 1, "Loading", ""))
    assert 0 in state.workers
    assert state.workers[0] == ("file.wav", 1, "Loading", "")


def test_processing_state_apply_done() -> None:
    state = ProcessingState(total=5)
    state.apply(("step", 0, "file.wav", 1, "Loading", ""))
    state.apply(("done", 0, "file.wav", "ok"))
    assert 0 not in state.workers
    assert state.done == 1
    assert state.ok == 1


def test_processing_state_apply_done_skipped() -> None:
    state = ProcessingState(total=5)
    state.apply(("done", 0, "file.wav", "skipped"))
    assert state.done == 1
    assert state.skipped == 1


def test_processing_state_apply_done_failed() -> None:
    state = ProcessingState(total=5)
    state.apply(("done", 0, "file.wav", "failed"))
    assert state.done == 1
    assert state.failed == 1


def test_processing_state_apply_multiple_workers() -> None:
    state = ProcessingState(total=5)
    state.apply(("step", 0, "a.wav", 1, "Loading", ""))
    state.apply(("step", 1, "b.wav", 2, "Trim Silence", ""))
    assert len(state.workers) == 2


def test_processing_state_apply_done_removes_worker() -> None:
    state = ProcessingState(total=5)
    state.apply(("step", 0, "a.wav", 1, "Loading", ""))
    state.apply(("step", 1, "b.wav", 2, "Trim Silence", ""))
    state.apply(("done", 0, "a.wav", "ok"))
    assert len(state.workers) == 1
    assert 0 not in state.workers
    assert 1 in state.workers


def test_processing_state_is_paused_default() -> None:
    state = ProcessingState()
    assert state.is_paused is False
    assert state.paused_at is None


def test_processing_state_pause() -> None:
    state = ProcessingState()
    assert state.is_paused is False
    state.pause()
    assert state.is_paused is True
    assert state.paused_at is not None


def test_processing_state_pause_twice() -> None:
    state = ProcessingState()
    state.pause()
    paused_at = state.paused_at
    time.sleep(0.01)
    state.pause()
    assert state.paused_at is not None
    assert state.paused_at == paused_at


def test_processing_state_resume() -> None:
    state = ProcessingState()
    state.pause()
    time.sleep(0.05)
    state.resume()
    assert state.is_paused is False
    assert state.paused_at is None
    assert state.paused_duration > 0


def test_processing_state_resume_without_pause() -> None:
    state = ProcessingState()
    state.resume()
    assert state.is_paused is False
    assert state.paused_at is None


def test_processing_state_elapsed_with_pause() -> None:
    state = ProcessingState()
    time.sleep(0.1)
    elapsed_before_pause = state.elapsed
    state.pause()
    time.sleep(0.15)
    elapsed_during_pause = state.elapsed
    assert elapsed_during_pause - elapsed_before_pause < 0.05
    state.resume()
    time.sleep(0.05)
    elapsed_after_resume = state.elapsed
    assert elapsed_after_resume - elapsed_during_pause > 0.04


def test_processing_state_apply_done_with_all_statuses() -> None:

    state = ProcessingState(total=5)

    state.apply(("done", 0, "file1.wav", "ok"))
    assert state.done == 1
    assert state.ok == 1

    state.apply(("done", 1, "file2.wav", "skipped"))
    assert state.done == 2
    assert state.skipped == 1

    state.apply(("done", 2, "file3.wav", "failed"))
    assert state.done == 3
    assert state.failed == 1
