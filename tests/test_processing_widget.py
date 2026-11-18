from __future__ import annotations

from typing import TYPE_CHECKING

from src.frontend.processing.processing_state import ProcessingState
from src.frontend.widgets.processing_widget import ProcessingWidget

if TYPE_CHECKING:
    from unittest.mock import MagicMock


def test_processing_widget_creates_with_defaults(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    assert widget.isVisible() is False


def test_processing_widget_reset(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=5, done=2, ok=1, skipped=1, failed=0)
    state.workers[0] = ("file.wav", 3, "Processing", "details")
    widget.update_state(state)
    widget.reset()

    assert widget._state.total == 0
    assert widget._state.done == 0


def test_processing_widget_update_state_applies_values(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=10, done=5, ok=3, skipped=1, failed=1)
    widget.update_state(state)

    assert widget._state.total == 10
    assert widget._state.done == 5
    assert widget._state.ok == 3


def test_processing_widget_update_state_with_workers(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=5)
    state.workers[0] = ("test.wav", 3, "Processing", "info")
    widget.update_state(state)

    assert 0 in widget._worker_widgets


def test_processing_widget_update_state_removes_workers(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=5)
    state.workers[0] = ("test.wav", 3, "Processing", "info")
    widget.update_state(state)
    assert 0 in widget._worker_widgets

    state.workers = {}
    widget.update_state(state)
    assert 0 not in widget._worker_widgets


def test_processing_widget_progress_bar_updates(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=100, done=50)
    widget.update_state(state)

    assert widget._progress_bar.value() == 50


def test_processing_widget_progress_bar_full(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=10, done=10)
    widget.update_state(state)

    assert widget._progress_bar.value() == 100


def test_processing_widget_status_label_shows_counts(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=10, done=5, ok=3, skipped=1, failed=1)
    widget.update_state(state)

    status = widget._status_label.text()
    assert "5/10" in status
    assert "ok:3" in status
    assert "skip:1" in status
    assert "fail:1" in status


def test_processing_widget_status_label_shows_eta(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=10, done=5, started=widget._state.started - 10)
    widget.update_state(state)

    status = widget._status_label.text()
    assert "ETA" in status


def test_processing_widget_status_label_no_eta_when_done(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=10, done=10)
    widget.update_state(state)

    status = widget._status_label.text()
    assert "ETA" not in status
