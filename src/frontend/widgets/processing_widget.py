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


def _format_duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class WorkerInfoWidget(QWidget):
    """Displays information about a single worker's processing state."""

    def __init__(self, worker_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker_id = worker_id
        self._file_label = QLabel()
        self._step_label = QLabel()
        self._desc_label = QLabel()
        self._details_label = QLabel()

        self._step_label.setFont(QFont("Consolas", 9))
        self._desc_label.setFont(QFont("Consolas", 9))
        self._details_label.setFont(QFont("Consolas", 8))
        self._details_label.setWordWrap(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(QLabel(f"W{worker_id:02d}"))
        layout.addWidget(self._step_label)
        layout.addWidget(self._desc_label)
        layout.addWidget(self._file_label)
        layout.addWidget(self._details_label)

    def update(self, file_name: str, step: int, total_steps: int, description: str, details: str) -> None:
        self._step_label.setText(f"{step}/{total_steps}")
        self._desc_label.setText(description)
        self._file_label.setText(file_name)
        self._details_label.setText(details)


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
        self._update_timer.setInterval(100)
        self._update_timer.timeout.connect(self._on_timer)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        self._progress_bar.setFixedHeight(24)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat("")
        header_layout.addWidget(self._progress_bar)

        self._status_label.setFont(QFont("Consolas", 9))
        self._status_label.setWordWrap(True)
        header_layout.addWidget(self._status_label)

        main_layout.addLayout(header_layout)

        self._scroll_area = QScrollArea()
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_content = QWidget()
        self._workers_layout = QVBoxLayout(self._scroll_content)
        self._workers_layout.setContentsMargins(4, 4, 4, 4)
        self._workers_layout.setSpacing(2)
        self._scroll_area.setWidget(self._scroll_content)
        main_layout.addWidget(self._scroll_area)

    def _on_timer(self) -> None:
        if self._state.total == 0:
            return
        self._update_display()

    def _update_display(self) -> None:
        fraction = self._state.fraction
        self._progress_bar.setValue(int(fraction * 100))

        elapsed = _format_duration(self._state.elapsed)
        eta = _format_duration(self._state.eta) if self._state.done > 0 and self._state.done < self._state.total else ""
        eta_str = f" ETA {eta}" if eta else ""

        self._status_label.setText(
            f"{fraction * 100:3.0f}%  {self._state.done}/{self._state.total}  "
            f"ok:{self._state.ok}  skip:{self._state.skipped}  fail:{self._state.failed}  "
            f"elapsed:{elapsed}{eta_str}"
        )

        for worker_id, (file_name, step, description, details) in self._state.workers.items():
            if worker_id not in self._worker_widgets:
                widget = WorkerInfoWidget(worker_id)
                self._worker_widgets[worker_id] = widget
                self._workers_layout.addWidget(widget)
            else:
                widget = self._worker_widgets[worker_id]
            widget.update(file_name, step, self._state.total, description, details)

        for worker_id in list(self._worker_widgets.keys()):
            if worker_id not in self._state.workers:
                widget = self._worker_widgets.pop(worker_id)
                self._workers_layout.removeWidget(widget)
                widget.deleteLater()

    def update_state(self, state: ProcessingState) -> None:
        self._state = state
        self._update_display()
        if self._state.total > 0 and not self._update_timer.isActive():
            self._update_timer.start()

    def reset(self) -> None:
        self._update_timer.stop()
        self._state = ProcessingState()
        self._progress_bar.setValue(0)
        self._status_label.setText("")
        for widget in self._worker_widgets.values():
            self._workers_layout.removeWidget(widget)
            widget.deleteLater()
        self._worker_widgets.clear()
