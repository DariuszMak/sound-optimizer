from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from unittest.mock import MagicMock
from unittest.mock import patch

from src.frontend.processing.processing_state import ProcessingState
from src.frontend.widgets.processing_widget import ProcessingWidget


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


def test_processing_widget_pause_button_initial_state(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    assert widget._pause_button.isEnabled() is False
    assert widget._pause_button.text() == "Pause"
    assert widget._is_paused is False
    assert widget._pause_pending is False


def test_processing_widget_pause_button_enabled_when_running(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=5, done=2)
    widget.update_state(state)

    assert widget._pause_button.isEnabled() is True


def test_processing_widget_pause_button_disabled_when_completed(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=5, done=5)
    widget.update_state(state)

    assert widget._pause_button.isEnabled() is False


def test_processing_widget_set_paused_shows_resume(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=5, done=2)
    widget.update_state(state)
    widget.set_paused(True)

    assert widget._is_paused is True
    assert widget._pause_button.text() == "Resume"
    assert widget._pause_pending is False


def test_processing_widget_set_paused_shows_pause(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=5, done=2)
    widget.update_state(state)
    widget.set_paused(True)
    widget.set_paused(False)

    assert widget._is_paused is False
    assert widget._pause_button.text() == "Pause"


def test_processing_widget_set_pause_pending(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=5, done=2)
    widget.update_state(state)

    widget.set_pause_pending(True)
    assert widget._pause_pending is True
    assert widget._pause_button.isEnabled() is False

    widget.set_pause_pending(False)
    assert widget._pause_pending is False
    assert widget._pause_button.isEnabled() is True


def test_processing_widget_status_label_shows_paused(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=10, done=5)
    widget.update_state(state)
    widget.set_paused(True)
    widget._update_display()

    status = widget._status_label.text()
    assert "[PAUSED]" in status


def test_processing_widget_status_label_no_paused_when_not_paused(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=10, done=5)
    widget.update_state(state)

    status = widget._status_label.text()
    assert "[PAUSED]" not in status


def test_processing_widget_reset_clears_pause_state(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=5, done=2)
    widget.update_state(state)
    widget.set_paused(True)

    widget.reset()

    assert widget._is_paused is False
    assert widget._pause_pending is False
    assert widget._pause_button.text() == "Pause"
    assert widget._pause_button.isEnabled() is False


def test_processing_widget_on_pause_clicked_pending(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=5, done=2)
    widget.update_state(state)
    widget.set_pause_pending(True)

    widget._on_pause_clicked()

    assert widget._pause_pending is True


def test_processing_widget_on_pause_clicked_not_pending(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=5, done=2)
    widget.update_state(state)
    widget.set_pause_pending(False)

    signal_emitted: list[bool] = []
    widget.pause_toggled.connect(signal_emitted.append)

    widget._on_pause_clicked()

    assert len(signal_emitted) == 1
    assert signal_emitted[0] is True


def test_processing_widget_on_timer_no_total(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    widget._state = ProcessingState()
    mock_update = patch.object(widget, "_update_display").start()

    widget._on_timer()

    mock_update.stop()
    mock_update.assert_not_called()


def test_processing_widget_on_timer_with_total(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=5, done=2)
    widget._state = state
    mock_update = patch.object(widget, "_update_display").start()

    widget._on_timer()

    mock_update.stop()
    mock_update.assert_called_once()


def test_processing_widget_update_display_creates_workers(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=5)
    state.workers[0] = ("test.wav", 3, "Processing", "info")
    widget.update_state(state)

    assert 0 in widget._worker_widgets
    worker_widget = widget._worker_widgets[0]
    assert worker_widget._file_label.text() == "test.wav"


def test_processing_widget_reset_stops_timer(qtbot: MagicMock) -> None:
    widget = ProcessingWidget()
    qtbot.addWidget(widget)

    state = ProcessingState(total=5, done=2)
    widget.update_state(state)
    widget._update_timer.start()

    stop_called = []
    original_stop = widget._update_timer.stop

    def mock_stop() -> None:
        stop_called.append(True)
        original_stop()

    with patch.object(widget._update_timer, "stop", side_effect=mock_stop):
        widget.reset()

    assert len(stop_called) == 1
