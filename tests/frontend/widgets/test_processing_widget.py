from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from src.frontend.processing.processing_state import ProcessingState
from src.frontend.widgets.processing_widget import ProcessingWidget

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


@pytest.fixture
def widget(qtbot: QtBot) -> ProcessingWidget:
    w = ProcessingWidget()
    qtbot.addWidget(w)
    return w


def test_processing_widget_creates_with_defaults(widget: ProcessingWidget) -> None:
    assert widget.isVisible() is False


def test_processing_widget_reset(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=5, done=2, ok=1, skipped=1, failed=0)
    state.workers[0] = ("file.wav", 3, "Processing", "details")
    widget.update_state(state)
    widget.reset()

    assert widget._state.total == 0
    assert widget._state.done == 0


def test_processing_widget_update_state_applies_values(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=10, done=5, ok=3, skipped=1, failed=1)
    widget.update_state(state)

    assert widget._state.total == 10
    assert widget._state.done == 5
    assert widget._state.ok == 3


def test_processing_widget_update_state_with_workers(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=5)
    state.workers[0] = ("test.wav", 3, "Processing", "info")
    widget.update_state(state)

    assert 0 in widget._worker_widgets


def test_processing_widget_update_state_removes_workers(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=5)
    state.workers[0] = ("test.wav", 3, "Processing", "info")
    widget.update_state(state)
    assert 0 in widget._worker_widgets

    state.workers = {}
    widget.update_state(state)
    assert 0 not in widget._worker_widgets


def test_processing_widget_progress_bar_updates(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=100, done=50)
    widget.update_state(state)

    assert widget._progress_bar.value() == 50


def test_processing_widget_progress_bar_full(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=10, done=10)
    widget.update_state(state)

    assert widget._progress_bar.value() == 100


def test_processing_widget_status_label_shows_counts(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=10, done=5, ok=3, skipped=1, failed=1)
    widget.update_state(state)

    status = widget._status_label.text()
    assert "5/10" in status
    assert "ok:3" in status
    assert "skip:1" in status
    assert "fail:1" in status


def test_processing_widget_status_label_shows_eta(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=10, done=5, started=widget._state.started - 10)
    widget.update_state(state)

    status = widget._status_label.text()
    assert "ETA" in status


def test_processing_widget_status_label_no_eta_when_done(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=10, done=10)
    widget.update_state(state)

    status = widget._status_label.text()
    assert "ETA" not in status


def test_processing_widget_pause_button_initial_state(widget: ProcessingWidget) -> None:
    assert widget._pause_button.isEnabled() is False
    assert widget._pause_button.text() == "Pause"
    assert widget._is_paused is False
    assert widget._pause_pending is False


def test_processing_widget_pause_button_enabled_when_running(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=5, done=2)
    widget.update_state(state)

    assert widget._pause_button.isEnabled() is True


def test_processing_widget_pause_button_disabled_when_completed(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=5, done=5)
    widget.update_state(state)

    assert widget._pause_button.isEnabled() is False


def test_processing_widget_set_paused_shows_resume(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=5, done=2)
    widget.update_state(state)
    widget.set_paused(True)

    assert widget._is_paused is True
    assert widget._pause_button.text() == "Resume"
    assert widget._pause_pending is False


def test_processing_widget_set_paused_shows_pause(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=5, done=2)
    widget.update_state(state)
    widget.set_paused(True)
    widget.set_paused(False)

    assert widget._is_paused is False
    assert widget._pause_button.text() == "Pause"


def test_processing_widget_set_pause_pending(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=5, done=2)
    widget.update_state(state)

    widget.set_pause_pending(True)
    assert widget._pause_pending is True
    assert widget._pause_button.isEnabled() is False

    widget.set_pause_pending(False)
    assert widget._pause_pending is False
    assert widget._pause_button.isEnabled() is True


def test_processing_widget_status_label_shows_paused(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=10, done=5)
    widget.update_state(state)
    widget.set_paused(True)
    widget._update_display()

    status = widget._status_label.text()
    assert "[PAUSED]" in status


def test_processing_widget_status_label_no_paused_when_not_paused(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=10, done=5)
    widget.update_state(state)

    status = widget._status_label.text()
    assert "[PAUSED]" not in status


def test_processing_widget_reset_clears_pause_state(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=5, done=2)
    widget.update_state(state)
    widget.set_paused(True)

    widget.reset()

    assert widget._is_paused is False
    assert widget._pause_pending is False
    assert widget._pause_button.text() == "Pause"
    assert widget._pause_button.isEnabled() is False


def test_processing_widget_on_pause_clicked_pending(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=5, done=2)
    widget.update_state(state)
    widget.set_pause_pending(True)

    widget._on_pause_clicked()

    assert widget._pause_pending is True


def test_processing_widget_on_pause_clicked_not_pending(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=5, done=2)
    widget.update_state(state)
    widget.set_pause_pending(False)

    signal_emitted: list[bool] = []
    widget.pause_toggled.connect(signal_emitted.append)

    widget._on_pause_clicked()

    assert len(signal_emitted) == 1
    assert signal_emitted[0] is True


def test_processing_widget_on_timer_no_total(widget: ProcessingWidget) -> None:
    widget._state = ProcessingState()
    with patch.object(widget, "_update_display") as mock_update:
        widget._on_timer()
    mock_update.assert_not_called()


def test_processing_widget_on_timer_with_total(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=5, done=2)
    widget._state = state
    with patch.object(widget, "_update_display") as mock_update:
        widget._on_timer()
    mock_update.assert_called_once()


def test_processing_widget_update_display_creates_workers(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=5)
    state.workers[0] = ("test.wav", 3, "Processing", "info")
    widget.update_state(state)

    assert 0 in widget._worker_widgets
    worker_widget = widget._worker_widgets[0]
    assert worker_widget._file_label.text() == "test.wav"


def test_processing_widget_reset_stops_timer(widget: ProcessingWidget) -> None:
    state = ProcessingState(total=5, done=2)
    widget.update_state(state)
    widget._update_timer.start()

    with patch.object(widget._update_timer, "stop", wraps=widget._update_timer.stop) as mock_stop:
        widget.reset()

    mock_stop.assert_called_once()
