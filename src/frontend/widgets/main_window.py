from __future__ import annotations

import logging
import os
from multiprocessing import Pool, Queue, Value, cpu_count
from queue import Empty
from typing import Any

import psutil
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from src.frontend.processing.processing_state import ProcessingState
from src.frontend.widgets.processing_widget import ProcessingWidget
from src.main import EXCLUDED_DIRS, INPUT_ROOT, OUTPUT_ROOT, SUPPORTED, _init_worker, check_ffmpeg_installed, process_audio

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
    pause_state_changed = Signal(bool)
    pause_failed = Signal(str)

    def __init__(self, tasks: list[tuple[str, str]], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tasks = tasks
        self._state = ProcessingState(total=len(tasks))
        self._pool: Any = None
        self._queue: Any = None
        self._results: list[Any] = []
        self._is_paused = False
        self._suspended_trees: list[tuple[psutil.Process, list[psutil.Process]]] = []
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)

    @property
    def state(self) -> ProcessingState:
        return self._state

    def _worker_processes(self) -> list[psutil.Process]:
        if self._pool is None:
            return []
        return [psutil.Process(worker.pid) for worker in self._pool._pool if worker.pid is not None and worker.is_alive()]

    def _suspend_process_tree(self) -> None:
        trees: list[tuple[psutil.Process, list[psutil.Process]]] = []
        try:
            for worker in self._worker_processes():
                try:
                    worker.suspend()
                except psutil.NoSuchProcess:
                    continue
                tree_entry: tuple[psutil.Process, list[psutil.Process]] = (worker, [])
                trees.append(tree_entry)
                children: list[psutil.Process] = []
                try:
                    children = worker.children(recursive=True)
                except psutil.NoSuchProcess:
                    pass
                suspended_children: list[psutil.Process] = []
                for child in reversed(children):
                    try:
                        child.suspend()
                        suspended_children.append(child)
                    except psutil.NoSuchProcess:
                        continue
                tree_entry[1].extend(reversed(suspended_children))
        except Exception:
            self._resume_process_trees(trees)
            raise
        self._suspended_trees = trees

    @staticmethod
    def _resume_process_trees(trees: list[tuple[psutil.Process, list[psutil.Process]]]) -> None:
        errors: list[str] = []
        for worker, children in trees:
            for child in children:
                try:
                    child.resume()
                except psutil.NoSuchProcess:
                    continue
                except psutil.Error as exc:
                    errors.append(str(exc))
            try:
                worker.resume()
            except psutil.NoSuchProcess:
                continue
            except psutil.Error as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError("; ".join(errors))

    def set_paused(self, paused: bool) -> None:
        if self._pool is None or paused == self._is_paused:
            return
        if paused:
            try:
                self._suspend_process_tree()
            except Exception as exc:
                logger.exception("Unable to suspend processing workers")
                self.pause_failed.emit(f"Could not pause processing: {exc}")
                return
            self._is_paused = True
            self._state.pause()
        else:
            try:
                self._resume_process_trees(self._suspended_trees)
            except Exception as exc:
                logger.exception("Unable to resume processing workers")
                self.pause_failed.emit(f"Could not resume processing: {exc}")
                return
            self._suspended_trees.clear()
            self._is_paused = False
            self._state.resume()
        self.pause_state_changed.emit(self._is_paused)
        self.state_updated.emit(self._state)

    def start(self) -> None:
        slot_counter = Value("i", 0)
        self._queue = Queue()
        self._state = ProcessingState(total=len(self._tasks))
        self._is_paused = False
        workers = max(1, min(cpu_count() - 1, len(self._tasks)))
        self._pool = Pool(workers, initializer=_init_worker, initargs=(slot_counter, self._queue))
        self._results = [self._pool.apply_async(process_audio, (task,)) for task in self._tasks]
        self.state_updated.emit(self._state)
        self._timer.start()

    def shutdown(self) -> None:
        self._timer.stop()
        pool, self._pool = self._pool, None
        if self._is_paused:
            try:
                self._resume_process_trees(self._suspended_trees)
            except Exception:
                logger.exception("Unable to resume workers before pool shutdown")
            self._suspended_trees.clear()
            self._is_paused = False
        if pool is not None:
            pool.terminate()
            pool.join()
        self._queue = None

    def _drain(self, timeout: float | None = None) -> bool:
        if self._queue is None:
            return False
        changed = False
        while True:
            try:
                message = self._queue.get(timeout=timeout) if timeout else self._queue.get_nowait()
            except Empty:
                return changed
            self._state.apply(message)
            changed = True

    def _poll(self) -> None:
        if self._pool is None:
            return
        changed = self._drain()
        finished = self._state.done >= self._state.total
        if not finished and all(result.ready() for result in self._results):
            changed = self._drain(timeout=0.2) or changed
            finished = self._state.done >= self._state.total
        if changed or finished:
            self.state_updated.emit(self._state)
        if finished:
            if self._is_paused:
                try:
                    self._resume_process_trees(self._suspended_trees)
                except Exception:
                    logger.exception("Unable to resume workers before finishing")
                    return
                self._suspended_trees.clear()
                self._is_paused = False
                self._state.resume()
                self.pause_state_changed.emit(False)
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        title = QLabel("Sound Optimizer")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        subtitle = QLabel("Batch audio file normalization and processing")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        buttons = QHBoxLayout()
        self._select_button = QPushButton("Select Audio Files")
        self._select_button.setMinimumHeight(40)
        self._select_button.clicked.connect(self._on_select_files)
        buttons.addWidget(self._select_button)
        self._select_folder_button = QPushButton("Select Folder")
        self._select_folder_button.setMinimumHeight(40)
        self._select_folder_button.clicked.connect(self._on_select_folder)
        buttons.addWidget(self._select_folder_button)
        self._start_button = QPushButton("Start Processing")
        self._start_button.setMinimumHeight(40)
        self._start_button.setEnabled(False)
        self._start_button.clicked.connect(self._on_start_processing)
        buttons.addWidget(self._start_button)
        layout.addLayout(buttons)
        self._file_label = QLabel("No files selected")
        self._file_label.setWordWrap(True)
        self._file_label.setStyleSheet("color: gray;")
        layout.addWidget(self._file_label)
        self._processing_widget = ProcessingWidget()
        layout.addWidget(self._processing_widget, 1)

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
        files, _ = QFileDialog.getOpenFileNames(self, "Select Audio Files", os.path.abspath(INPUT_ROOT), _file_dialog_filter())
        if files:
            self._set_tasks(_build_tasks(files, INPUT_ROOT))

    def _on_select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Folder With Audio Files", os.path.abspath(INPUT_ROOT))
        if folder:
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
            QMessageBox.critical(self, "FFmpeg Required", "FFmpeg is not installed or not found in PATH.\\nPlease install FFmpeg to continue.")
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
            self._runner.pause_state_changed.connect(self._processing_widget.set_paused)
            self._runner.pause_failed.connect(self._on_pause_failed)
        self._runner.start()

    def _on_pause_failed(self, message: str) -> None:
        if self._processing_widget is not None:
            self._processing_widget.set_pause_pending(False)
        QMessageBox.warning(self, "Pause / Resume Failed", message)

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
            answer = QMessageBox.question(self, "Processing in progress", "Processing is still running. Stop it and quit?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._runner.shutdown()
            self._runner = None
        event.accept()


def create_app() -> MainWindow:
    return MainWindow()
