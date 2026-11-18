from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget

from src.frontend.processing.processing_state import ProcessingState
from src.main import NUMBER_OF_STEPS


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


class WorkerInfoWidget(QWidget):
    def __init__(self, worker_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._id_label = QLabel(f"W{worker_id:02d}")
        self._step_label = QLabel()
        self._desc_label = QLabel()
        self._file_label = QLabel()
        self._details_label = QLabel()
        mono = QFont("Consolas", 9)
        for label in (self._id_label, self._step_label, self._desc_label):
            label.setFont(mono)
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
    pause_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = ProcessingState()
        self._is_paused = False
        self._pause_pending = False
        self._progress_bar = QProgressBar()
        self._status_label = QLabel()
        self._pause_button = QPushButton("Pause")
        self._workers_layout: QVBoxLayout | None = None
        self._worker_widgets: dict[int, WorkerInfoWidget] = {}
        self._build_ui()
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(250)
        self._update_timer.timeout.connect(self._on_timer)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self._progress_bar.setFixedHeight(20)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(False)
        layout.addWidget(self._progress_bar)
        status_layout = QHBoxLayout()
        self._status_label.setFont(QFont("Consolas", 9))
        self._status_label.setWordWrap(True)
        status_layout.addWidget(self._status_label, 1)
        self._pause_button.setFixedWidth(90)
        self._pause_button.setEnabled(False)
        self._pause_button.clicked.connect(self._on_pause_clicked)
        status_layout.addWidget(self._pause_button)
        layout.addLayout(status_layout)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        content = QWidget()
        self._workers_layout = QVBoxLayout(content)
        self._workers_layout.setContentsMargins(4, 4, 4, 4)
        self._workers_layout.setSpacing(4)
        self._workers_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

    def _on_pause_clicked(self) -> None:
        if self._pause_pending:
            return
        self._pause_pending = True
        self._pause_button.setEnabled(False)
        self.pause_toggled.emit(not self._is_paused)

    def set_pause_pending(self, pending: bool) -> None:
        self._pause_pending = pending
        running = self._state.total > 0 and self._state.done < self._state.total
        self._pause_button.setEnabled(running and not pending)

    def set_paused(self, paused: bool) -> None:
        self._is_paused = paused
        self._pause_pending = False
        self._pause_button.setText("Resume" if paused else "Pause")
        running = self._state.total > 0 and self._state.done < self._state.total
        self._pause_button.setEnabled(running)

    def _on_timer(self) -> None:
        if self._state.total:
            self._update_display()

    def _update_display(self) -> None:
        assert self._workers_layout is not None
        state = self._state
        fraction = state.fraction
        self._progress_bar.setValue(int(fraction * 100))
        elapsed = _format_duration(state.elapsed)
        eta = _format_duration(state.eta) if 0 < state.done < state.total else ""
        eta_str = f" ETA {eta}" if eta else ""
        paused_str = " [PAUSED]" if self._is_paused else ""
        self._status_label.setText(
            f"{fraction * 100:3.0f}%  {state.done}/{state.total}  "
            f"ok:{state.ok}  skip:{state.skipped}  fail:{state.failed}  "
            f"elapsed:{elapsed}{eta_str}{paused_str}"
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
        self._pause_button.setEnabled(running and not self._pause_pending)
        if running and not self._is_paused and not self._update_timer.isActive():
            self._update_timer.start()
        elif (not running or self._is_paused) and self._update_timer.isActive():
            self._update_timer.stop()

    def reset(self) -> None:
        assert self._workers_layout is not None
        self._update_timer.stop()
        self._is_paused = False
        self._pause_pending = False
        self._pause_button.setText("Pause")
        self._pause_button.setEnabled(False)
        self._state = ProcessingState()
        self._progress_bar.setValue(0)
        self._status_label.setText("")
        for widget in self._worker_widgets.values():
            self._workers_layout.removeWidget(widget)
            widget.deleteLater()
        self._worker_widgets.clear()
