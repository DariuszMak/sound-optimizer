from __future__ import annotations

import logging
import os
from multiprocessing import Pool, Queue, Value, cpu_count
from queue import Empty
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QFont
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
    EXCLUDED_DIRS,
    INPUT_ROOT,
    OUTPUT_ROOT,
    SUPPORTED,
    _init_worker,
    check_ffmpeg_installed,
    process_audio,
)

logger = logging.getLogger(__name__)

_POLL_INTERVAL_MS = 100


def _file_dialog_filter() -> str:
    patterns: list[str] = []
    for ext in SUPPORTED:
        patterns.extend((f"*{ext}", f"*{ext.upper()}"))
    return f"Audio Files ({' '.join(patterns)});;All Files (*)"


def _output_path(input_path: str, base_dir: str) -> str:
    try:
        relative_path = os.path.relpath(input_path, base_dir)
    except ValueError:
        relative_path = os.path.basename(input_path)
    if relative_path == os.pardir or relative_path.startswith(os.pardir + os.sep):
        relative_path = os.path.basename(input_path)
    relative_base = os.path.splitext(relative_path)[0]
    return os.path.join(OUTPUT_ROOT, relative_base + "_processed.mp3")


def _build_tasks(input_paths: list[str], base_dir: str) -> list[tuple[str, str]]:
    tasks: list[tuple[str, str]] = []
    used_outputs: set[str] = set()
    for raw_path in input_paths:
        input_path = os.path.normpath(raw_path)
        if not input_path.lower().endswith(SUPPORTED):
            continue
        output_path = _output_path(input_path, base_dir)

        stem, ext = os.path.splitext(output_path)
        counter = 2
        while output_path in used_outputs:
            output_path = f"{stem}_{counter}{ext}"
            counter += 1
        used_outputs.add(output_path)

        tasks.append((input_path, output_path))
    return tasks


def _scan_folder(folder: str) -> list[str]:
    found: list[str] = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        found.extend(os.path.join(root, name) for name in sorted(files) if name.lower().endswith(SUPPORTED))
    return found


class _PoolRunner(QObject):
    state_updated = Signal(object)
    finished = Signal(object)

    def __init__(self, tasks: list[tuple[str, str]], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tasks = tasks
        self._state = ProcessingState(total=len(tasks))
        self._pool: Any = None
        self._queue: Any = None
        self._results: list[Any] = []
        self._is_paused = False

        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)

    @property
    def state(self) -> ProcessingState:
        return self._state

    def set_paused(self, paused: bool) -> None:
        self._is_paused = paused
        if paused:
            self._timer.stop()
        else:
            self._timer.start()

    def start(self) -> None:
        slot_counter = Value("i", 0)
        self._queue = Queue()
        self._state = ProcessingState(total=len(self._tasks))
        self._is_paused = False

        workers = max(1, cpu_count() - 1)
        self._pool = Pool(
            workers,
            initializer=_init_worker,
            initargs=(slot_counter, self._queue),
        )
        self._results = [self._pool.apply_async(process_audio, (task,)) for task in self._tasks]

        self.state_updated.emit(self._state)
        self._timer.start()

    def shutdown(self) -> None:
        self._timer.stop()
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.terminate()
            pool.join()
        self._queue = None

    def _drain(self, timeout: float | None = None) -> bool:
        queue = self._queue
        if queue is None:
            return False
        changed = False
        while True:
            try:
                message = queue.get(timeout=timeout) if timeout else queue.get_nowait()
            except Empty:
                return changed
            self._state.apply(message)
            changed = True

    def _poll(self) -> None:
        if self._pool is None or self._is_paused:
            return

        changed = self._drain()
        finished = self._state.done >= self._state.total

        if not finished and all(r.ready() for r in self._results):
            changed = self._drain(timeout=0.2) or changed
            finished = True

        if changed or finished:
            self.state_updated.emit(self._state)
        if finished:
            self._finish()

    def _finish(self) -> None:
        self._timer.stop()
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.close()
            pool.join()
        self._queue = None
        self.finished.emit(self._state)


class MainWindow(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sound Optimizer")
        self.setMinimumSize(600, 400)
        self._processing_widget: ProcessingWidget | None = None
        self._runner: _PoolRunner | None = None
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

        self._select_folder_button = QPushButton("Select Folder")
        self._select_folder_button.setMinimumHeight(40)
        self._select_folder_button.clicked.connect(self._on_select_folder)
        button_layout.addWidget(self._select_folder_button)

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
        main_layout.addWidget(self._processing_widget, 1)

    def _set_tasks(self, tasks: list[tuple[str, str]]) -> None:
        if not tasks:
            QMessageBox.information(self, "No audio files", "No supported audio files were found.")
            return
        self._tasks = tasks
        self._file_label.setText(f"{len(tasks)} file(s) selected - output goes to '{OUTPUT_ROOT}'")
        self._file_label.setStyleSheet("")
        self._start_button.setEnabled(True)
        if self._processing_widget is not None:
            self._processing_widget.reset()

    def _on_select_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Audio Files",
            os.path.abspath(INPUT_ROOT),
            _file_dialog_filter(),
        )
        if not files:
            return
        self._set_tasks(_build_tasks(files, INPUT_ROOT))

    def _on_select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Folder With Audio Files",
            os.path.abspath(INPUT_ROOT),
        )
        if not folder:
            return
        folder = os.path.normpath(folder)
        self._set_tasks(_build_tasks(_scan_folder(folder), folder))

    def _set_busy(self, busy: bool) -> None:
        self._is_processing = busy
        self._select_button.setEnabled(not busy)
        self._select_folder_button.setEnabled(not busy)
        self._start_button.setEnabled(not busy and bool(self._tasks))

    def _on_start_processing(self) -> None:
        if not self._tasks or self._is_processing:
            return

        if not check_ffmpeg_installed():
            QMessageBox.critical(
                self,
                "FFmpeg Required",
                "FFmpeg is not installed or not found in PATH.\nPlease install FFmpeg to continue.",
            )
            return

        self._set_busy(True)
        self._file_label.setText("Processing...")
        if self._processing_widget is not None:
            self._processing_widget.reset()

        self._runner = _PoolRunner(self._tasks, self)
        self._runner.state_updated.connect(self._on_state_updated)
        self._runner.finished.connect(self._on_processing_finished)
        if self._processing_widget is not None:
            self._processing_widget.pause_toggled.connect(self._runner.set_paused)
        self._runner.start()

    def _on_state_updated(self, state: ProcessingState) -> None:
        if self._processing_widget is not None:
            self._processing_widget.update_state(state)

    def _on_processing_finished(self, state: ProcessingState) -> None:
        summary = f"Processing done. OK: {state.ok} | Skipped: {state.skipped} | Failed: {state.failed}"
        logger.info(summary)
        self._file_label.setText(summary)
        self._set_busy(False)
        if self._runner is not None:
            self._runner.deleteLater()
            self._runner = None

    def closeEvent(self, event: QCloseEvent) -> None:  # ruff: ignore[invalid-function-name]
        if self._runner is not None:
            answer = QMessageBox.question(
                self,
                "Processing in progress",
                "Processing is still running. Stop it and quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._runner.shutdown()
            self._runner = None
        event.accept()


def create_app() -> MainWindow:
    return MainWindow()
