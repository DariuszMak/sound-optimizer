from __future__ import annotations

import logging
import os
from multiprocessing import Pool, Queue, Value, cpu_count
from queue import Empty
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.frontend.processing.processing_state import ProcessingState
from src.frontend.widgets.processing_widget import ProcessingWidget
from src.main import (
    OUTPUT_ROOT,
    SUPPORTED,
    check_ffmpeg_installed,
    process_audio,
)

logger = logging.getLogger(__name__)


class MainWindow(QWidget):
    """Main application window for the sound optimizer."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sound Optimizer")
        self.setMinimumSize(600, 400)
        self._processing_widget: ProcessingWidget | None = None
        self._tasks: list[tuple[str, str]] = []
        self._is_processing = False
        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        title_label = QLabel("Sound Optimizer")
        title_label.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)

        subtitle = QLabel("Batch audio file normalization and processing")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        main_layout.addWidget(subtitle)

        button_layout = QHBoxLayout()
        self._select_button = QPushButton("Select Audio Files")
        self._select_button.setMinimumHeight(40)
        self._select_button.clicked.connect(self._on_select_files)
        button_layout.addWidget(self._select_button)

        self._start_button = QPushButton("Start Processing")
        self._start_button.setMinimumHeight(40)
        self._start_button.setEnabled(False)
        self._start_button.clicked.connect(self._on_start_processing)
        button_layout.addWidget(self._start_button)

        main_layout.addLayout(button_layout)

        self._file_label = QLabel("No files selected")
        self._file_label.setWordWrap(True)
        self._file_label.setStyleSheet("color: gray;")
        main_layout.addWidget(self._file_label)

        self._processing_widget = ProcessingWidget()
        main_layout.addWidget(self._processing_widget)

    def _on_select_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Audio Files",
            "",
            f"Audio Files ({' '.join(SUPPORTED)});;All Files (*)",
        )
        if not files:
            return

        self._tasks = [(f, os.path.join(OUTPUT_ROOT, os.path.basename(f))) for f in files]
        self._file_label.setText(f"{len(self._tasks)} file(s) selected")
        self._file_label.setStyleSheet("")
        self._start_button.setEnabled(True)

    def _on_start_processing(self) -> None:
        if not self._tasks or self._is_processing:
            return

        if not check_ffmpeg_installed():
            QMessageBox.critical(
                self,
                "FFmpeg Required",
                "FFmpeg is not installed or not found in PATH.\n"
                "Please install FFmpeg to continue.",
            )
            return

        self._is_processing = True
        self._start_button.setEnabled(False)
        self._select_button.setEnabled(False)
        self._file_label.setText("Processing...")

        self._processing_worker = _ProcessingWorker(self._tasks)
        self._processing_worker.state_updated.connect(self._on_state_updated)
        self._processing_worker.finished.connect(self._on_processing_finished)
        self._processing_worker.start_processing()

    def _on_state_updated(self, state: ProcessingState) -> None:
        if self._processing_widget is not None:
            self._processing_widget.update_state(state)

    def _on_processing_finished(self) -> None:
        self._is_processing = False
        self._start_button.setEnabled(True)
        self._select_button.setEnabled(True)
        if self._processing_widget is not None:
            self._processing_widget.reset()


class _ProcessingWorker(QTimer):
    """Background worker that runs the processing pool and emits state updates."""

    def __init__(self, tasks: list[tuple[str, str]]) -> None:
        super().__init__()
        self._tasks = tasks
        self._state = ProcessingState(total=len(tasks))
        self._pool: Pool | None = None
        self._queue: Any = None
        self._slot_counter: Any = None
        self._results: list[Any] = []

        self.timeout.connect(self._on_timeout)

    def start_processing(self) -> None:
        self._slot_counter = Value("i", 0)
        self._queue = Queue()
        self._state = ProcessingState(total=len(self._tasks))

        workers = max(1, cpu_count() - 1)
        self._pool = Pool(
            workers,
            initializer=_init_worker,
            initargs=(self._slot_counter, self._queue),
        )
        self._results = [self._pool.apply_async(process_audio, (task,)) for task in self._tasks]

        self.start(100)

    def _on_timeout(self) -> None:
        if self._pool is None or self._queue is None:
            return

        while True:
            try:
                message = self._queue.get(timeout=0.01)
                self._state.apply(message)
            except Empty:
                break

        if self._state.done < self._state.total and all(r.ready() for r in self._results):
            self.stop()
            if self._pool is not None:
                self._pool.terminate()
                self._pool.join()
            return

        if self._state.done >= self._state.total:
            self.stop()
            if self._pool is not None:
                self._pool.terminate()
                self._pool.join()


def _init_worker(counter: Value, progress_queue: Any) -> None:
    global _worker_slot, _progress_queue
    _progress_queue = progress_queue
    with counter.get_lock():
        _worker_slot = counter.value
        counter.value += 1


def create_app() -> MainWindow:
    """Factory function to create and return the main application window."""
    app = MainWindow()
    return app
