from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.frontend.processing.processing_state import ProcessingState
from src.main import NUMBER_OF_STEPS


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class WorkerInfoWidget(QWidget):
    """Displays information about a single worker's processing state."""

    def __init__(self, worker_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker_id = worker_id
        self._id_label = QLabel(f"W{worker_id:02d}")
        self._step_label = QLabel()
        self._desc_label = QLabel()
        self._file_label = QLabel()
        self._details_label = QLabel()

        mono = QFont("Consolas", 9)
        self._id_label.setFont(mono)
        self._step_label.setFont(mono)
        self._desc_label.setFont(mono)
        self._details_label.setFont(QFont("Consolas", 8))
        self._details_label.setStyleSheet("color: gray;")
        self._details_label.setWordWrap(True)

        self._id_label.setFixedWidth(36)
        self._step_label.setFixedWidth(36)
        self._desc_label.setMinimumWidth(130)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        top_row.addWidget(self._id_label)
        top_row.addWidget(self._step_label)
        top_row.addWidget(self._desc_label)
        top_row.addWidget(self._file_label, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(0)
        layout.addLayout(top_row)
        layout.addWidget(self._details_label)

    def set_info(self, file_name: str, step: int, description: str, details: str) -> None:
        self._step_label.setText(f"{step}/{NUMBER_OF_STEPS}")
        self._desc_label.setText(description)
        self._file_label.setText(file_name)
        self._details_label.setText(details)
        self._details_label.setVisible(bool(details))


class ProcessingWidget(QWidget):
    """Live processing dashboard widget that displays worker progress."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = ProcessingState()
        self._progress_bar = QProgressBar()
        self._status_label = QLabel()
        self._workers_layout: QVBoxLayout | None = None
        self._scroll_area: QScrollArea | None = None
        self._scroll_content: QWidget | None = None
        self._worker_widgets: dict[int, WorkerInfoWidget] = {}

        self._build_ui()

        self._update_timer = QTimer(self)
        self._update_timer.setInterval(250)
        self._update_timer.timeout.connect(self._on_timer)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        self._progress_bar.setFixedHeight(20)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(False)
        main_layout.addWidget(self._progress_bar)

        self._status_label.setFont(QFont("Consolas", 9))
        self._status_label.setWordWrap(True)
        main_layout.addWidget(self._status_label)

        self._scroll_area = QScrollArea()
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_content = QWidget()
        self._workers_layout = QVBoxLayout(self._scroll_content)
        self._workers_layout.setContentsMargins(4, 4, 4, 4)
        self._workers_layout.setSpacing(4)
        self._workers_layout.addStretch(1)
        self._scroll_area.setWidget(self._scroll_content)
        main_layout.addWidget(self._scroll_area, 1)

    def _on_timer(self) -> None:
        if self._state.total == 0:
            return
        self._update_display()

    def _update_display(self) -> None:
        assert self._workers_layout is not None

        state = self._state
        fraction = state.fraction
        self._progress_bar.setValue(int(fraction * 100))

        elapsed = _format_duration(state.elapsed)
        eta = _format_duration(state.eta) if 0 < state.done < state.total else ""
        eta_str = f" ETA {eta}" if eta else ""

        self._status_label.setText(
            f"{fraction * 100:3.0f}%  {state.done}/{state.total}  "
            f"ok:{state.ok}  skip:{state.skipped}  fail:{state.failed}  "
            f"elapsed:{elapsed}{eta_str}"
        )

        for worker_id, (file_name, step, description, details) in sorted(state.workers.items()):
            widget = self._worker_widgets.get(worker_id)
            if widget is None:
                widget = WorkerInfoWidget(worker_id)

                index = sum(1 for existing in self._worker_widgets if existing < worker_id)
                self._workers_layout.insertWidget(index, widget)
                self._worker_widgets[worker_id] = widget
            widget.set_info(file_name, step, description, details)

        for worker_id in list(self._worker_widgets):
            if worker_id not in state.workers:
                widget = self._worker_widgets.pop(worker_id)
                self._workers_layout.removeWidget(widget)
                widget.deleteLater()

    def update_state(self, state: ProcessingState) -> None:
        self._state = state
        self._update_display()
        running = state.total > 0 and state.done < state.total
        if running and not self._update_timer.isActive():
            self._update_timer.start()
        elif not running and self._update_timer.isActive():
            # Batch finished: freeze the elapsed time instead of ticking forever.
            self._update_timer.stop()

    def reset(self) -> None:
        assert self._workers_layout is not None

        self._update_timer.stop()
        self._state = ProcessingState()
        self._progress_bar.setValue(0)
        self._status_label.setText("")
        for widget in self._worker_widgets.values():
            self._workers_layout.removeWidget(widget)
            widget.deleteLater()
        self._worker_widgets.clear()
