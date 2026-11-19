from __future__ import annotations

from queue import Empty
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import psutil  # type: ignore[import-untyped]
import pytest
from PySide6.QtWidgets import QMessageBox

from src.frontend.processing.processing_state import ProcessingState
from src.frontend.widgets.main_window import (
    MainWindow,
    _build_tasks,
    _file_dialog_filter,
    _output_path,
    _PoolRunner,
    _scan_folder,
    create_app,
)
from src.main import SUPPORTED

if TYPE_CHECKING:
    from pathlib import Path

    from pytestqt.qtbot import QtBot


@pytest.fixture(autouse=True)
def auto_mock_message_box(monkeypatch: pytest.MonkeyPatch) -> None:
    """Automatically mock all message boxes globally so no windows pop up during tests."""
    monkeypatch.setattr(QMessageBox, "question", lambda *_, **__: QMessageBox.StandardButton.No)
    monkeypatch.setattr(QMessageBox, "information", lambda *_, **__: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *_, **__: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_, **__: None)


def test_file_dialog_filter() -> None:
    f_filter: str = _file_dialog_filter()
    assert "Audio Files" in f_filter
    assert "All Files (*)" in f_filter


def test_output_path() -> None:
    path: str = _output_path("/path/to/song.mp3", "/path/to")
    assert path.endswith("song_processed.mp3")

    path_val: str = _output_path("absolute/path.mp3", "another/path")
    assert "path_processed.mp3" in path_val


def test_build_tasks() -> None:
    tasks: list[tuple[str, str]] = _build_tasks(["/path/to/file.txt", f"/path/to/song{SUPPORTED[0]}"], "/path")
    assert len(tasks) == 1
    assert tasks[0][0].endswith(SUPPORTED[0])


def test_scan_folder(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    excluded = tmp_path / "excluded"
    excluded.mkdir()

    audio_file = sub / f"test{SUPPORTED[0]}"
    audio_file.write_text("dummy")

    txt_file = sub / "test.txt"
    txt_file.write_text("dummy")

    ex_file = excluded / f"ex{SUPPORTED[0]}"
    ex_file.write_text("dummy")

    with patch("src.frontend.widgets.main_window.EXCLUDED_DIRS", {"excluded"}):
        found: list[str] = _scan_folder(str(tmp_path))
        assert len(found) == 1
        assert str(audio_file) in found[0]


def test_main_window_init(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == "Sound Optimizer"
    assert window._start_button.isEnabled() is False
    assert window._file_label.text() == "No files selected"


def test_create_app(qtbot: QtBot) -> None:
    app = create_app()
    qtbot.addWidget(app)
    assert isinstance(app, MainWindow)


def test_set_tasks_empty(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._set_tasks([])
    assert window._start_button.isEnabled() is False


def test_set_tasks_valid(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    tasks: list[tuple[str, str]] = [("input.mp3", "output.mp3")]
    window._set_tasks(tasks)
    assert window._start_button.isEnabled() is True
    assert "1 file(s) selected" in window._file_label.text()


@patch("PySide6.QtWidgets.QFileDialog.getOpenFileNames")
def test_on_select_files(mock_file_dialog: MagicMock, qtbot: QtBot) -> None:
    mock_file_dialog.return_value = (["/path/to/file.mp3"], "")
    window = MainWindow()
    qtbot.addWidget(window)
    window._on_select_files()
    assert window._start_button.isEnabled() is True


@patch("PySide6.QtWidgets.QFileDialog.getOpenFileNames")
def test_on_select_files_cancelled(mock_file_dialog: MagicMock, qtbot: QtBot) -> None:
    mock_file_dialog.return_value = ([], "")
    window = MainWindow()
    qtbot.addWidget(window)
    window._on_select_files()
    assert window._start_button.isEnabled() is False


@patch("PySide6.QtWidgets.QFileDialog.getExistingDirectory")
def test_on_select_folder(mock_dir_dialog: MagicMock, qtbot: QtBot, tmp_path: Path) -> None:
    audio_file = tmp_path / f"song{SUPPORTED[0]}"
    audio_file.write_text("data")
    mock_dir_dialog.return_value = str(tmp_path)

    window = MainWindow()
    qtbot.addWidget(window)
    window._on_select_folder()
    assert window._start_button.isEnabled() is True


@patch("PySide6.QtWidgets.QFileDialog.getExistingDirectory")
def test_on_select_folder_cancelled(mock_dir_dialog: MagicMock, qtbot: QtBot) -> None:
    mock_dir_dialog.return_value = ""
    window = MainWindow()
    qtbot.addWidget(window)
    window._on_select_folder()
    assert window._start_button.isEnabled() is False


@patch("src.frontend.widgets.main_window.check_ffmpeg_installed")
def test_on_start_processing_no_ffmpeg(mock_ffmpeg: MagicMock, qtbot: QtBot) -> None:
    mock_ffmpeg.return_value = False
    window = MainWindow()
    qtbot.addWidget(window)
    window._tasks = [("in.mp3", "out.mp3")]
    window._on_start_processing()
    assert window._is_processing is False


@patch("src.frontend.widgets.main_window.check_ffmpeg_installed")
@patch("src.frontend.widgets.main_window._PoolRunner")
def test_on_start_processing_success(mock_runner_cls: MagicMock, mock_ffmpeg: MagicMock, qtbot: QtBot) -> None:
    mock_ffmpeg.return_value = True
    mock_runner = MagicMock()
    mock_runner_cls.return_value = mock_runner

    window = MainWindow()
    qtbot.addWidget(window)
    window._tasks = [("in.mp3", "out.mp3")]

    window._on_start_processing()
    mock_runner.start.assert_called_once()
    assert window._is_processing is True


def test_pool_runner_lifecycle() -> None:
    tasks: list[tuple[str, str]] = [("in.mp3", "out.mp3")]
    runner = _PoolRunner(tasks)
    assert runner.state.total == 1

    with (
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
    ):
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool
        runner.start()
        assert runner._pool is not None

        runner.shutdown()
        assert runner._pool is None


def test_close_event_no_runner(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    event = MagicMock()
    window.closeEvent(event)
    event.accept.assert_called_once()


def test_close_event_with_runner_yes(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    mock_runner = MagicMock()
    window._runner = mock_runner

    monkeypatch.setattr(QMessageBox, "question", lambda *_, **__: QMessageBox.StandardButton.Yes)

    event = MagicMock()
    window.closeEvent(event)
    event.accept.assert_called_once()
    mock_runner.shutdown.assert_called_once()


def test_close_event_with_runner_no(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    mock_runner = MagicMock()
    window._runner = mock_runner

    monkeypatch.setattr(QMessageBox, "question", lambda *_, **__: QMessageBox.StandardButton.No)

    event = MagicMock()
    window.closeEvent(event)
    event.ignore.assert_called_once()
    mock_runner.shutdown.assert_not_called()


def test_pool_runner_pause_resume() -> None:
    tasks: list[tuple[str, str]] = [("in.mp3", "out.mp3")]
    with (
        patch("src.frontend.widgets.main_window.QTimer") as mock_timer_cls,
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
        patch("src.frontend.widgets.main_window.psutil"),
    ):
        mock_timer = MagicMock()
        mock_timer_cls.return_value = mock_timer
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool

        runner = _PoolRunner(tasks)
        runner.start()

        runner.set_paused(True)
        assert runner._is_paused is True
        assert runner._state.is_paused is True
        mock_timer.stop.assert_not_called()

        runner.set_paused(False)
        assert runner._is_paused is False
        assert runner._state.is_paused is False


def test_pool_runner_set_paused_emits_signal() -> None:
    tasks: list[tuple[str, str]] = [("in.mp3", "out.mp3")]
    with (
        patch("src.frontend.widgets.main_window.QTimer") as mock_timer_cls,
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
        patch("src.frontend.widgets.main_window.psutil"),
    ):
        mock_timer = MagicMock()
        mock_timer_cls.return_value = mock_timer
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool

        runner = _PoolRunner(tasks)
        runner.start()

        signal_emitted: list[Any] = []
        runner.pause_state_changed.connect(signal_emitted.append)
        runner.set_paused(True)

        assert len(signal_emitted) == 1
        assert signal_emitted[0] is True


def test_pool_runner_set_paused_emits_signal_on_resume() -> None:
    tasks: list[tuple[str, str]] = [("in.mp3", "out.mp3")]
    with (
        patch("src.frontend.widgets.main_window.QTimer") as mock_timer_cls,
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
        patch("src.frontend.widgets.main_window.psutil"),
    ):
        mock_timer = MagicMock()
        mock_timer_cls.return_value = mock_timer
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool

        runner = _PoolRunner(tasks)
        runner.start()
        runner.set_paused(True)

        signal_emitted: list[Any] = []
        runner.pause_state_changed.connect(signal_emitted.append)
        runner.set_paused(False)

        assert len(signal_emitted) == 1
        assert signal_emitted[0] is False


def test_pool_runner_pause_failed_signal() -> None:
    tasks: list[tuple[str, str]] = [("in.mp3", "out.mp3")]
    with (
        patch("src.frontend.widgets.main_window.QTimer") as mock_timer_cls,
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
        patch("src.frontend.widgets.main_window.psutil") as mock_psutil,
    ):
        mock_timer = MagicMock()
        mock_timer_cls.return_value = mock_timer
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool

        mock_worker = MagicMock()
        mock_worker.pid = 1234
        mock_worker.is_alive.return_value = True
        mock_pool._pool = [mock_worker]

        mock_suspended_process = MagicMock()
        mock_suspended_process.suspend.side_effect = Exception("simulated failure")
        mock_psutil.Process.return_value = mock_suspended_process

        runner = _PoolRunner(tasks)
        runner.start()

        signal_emitted: list[Any] = []
        runner.pause_failed.connect(signal_emitted.append)
        runner.set_paused(True)

        assert len(signal_emitted) == 1
        assert "Could not pause processing" in signal_emitted[0]
        assert runner._is_paused is False


def test_pool_runner_shutdown_resumes_paused() -> None:
    tasks: list[tuple[str, str]] = [("in.mp3", "out.mp3")]
    with (
        patch("src.frontend.widgets.main_window.QTimer") as mock_timer_cls,
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
        patch("src.frontend.widgets.main_window.psutil"),
    ):
        mock_timer = MagicMock()
        mock_timer_cls.return_value = mock_timer
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool

        runner = _PoolRunner(tasks)
        runner.start()
        runner.set_paused(True)

        assert runner._is_paused is True
        runner.shutdown()
        assert runner._is_paused is False


def test_pool_runner_worker_processes_empty() -> None:
    runner = _PoolRunner([])
    assert runner._worker_processes() == []


def test_main_window_on_pause_failed(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    mock_widget = MagicMock()
    window._processing_widget = mock_widget

    window._on_pause_failed("Test error message")

    mock_widget.set_pause_pending.assert_called_once_with(False)


def test_main_window_pause_connections(qtbot: QtBot) -> None:
    tasks: list[tuple[str, str]] = [("in.mp3", "out.mp3")]
    window = MainWindow()
    qtbot.addWidget(window)
    window._tasks = tasks

    with (
        patch("src.frontend.widgets.main_window.check_ffmpeg_installed", return_value=True),
        patch("src.frontend.widgets.main_window._PoolRunner") as mock_runner_cls,
    ):
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner

        window._on_start_processing()

        mock_runner.start.assert_called_once()
        mock_runner.pause_state_changed.connect.assert_called()
        mock_runner.pause_failed.connect.assert_called()


def test_pool_runner_set_paused_no_op_when_already_paused() -> None:
    tasks: list[tuple[str, str]] = [("in.mp3", "out.mp3")]
    with (
        patch("src.frontend.widgets.main_window.QTimer") as mock_timer_cls,
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
        patch("src.frontend.widgets.main_window.psutil"),
    ):
        mock_timer = MagicMock()
        mock_timer_cls.return_value = mock_timer
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool

        runner = _PoolRunner(tasks)
        runner.start()
        runner.set_paused(True)

        signal_emitted: list[Any] = []
        runner.pause_state_changed.connect(signal_emitted.append)
        runner.set_paused(True)

        assert len(signal_emitted) == 0


def test_pool_runner_set_paused_no_op_when_already_resumed() -> None:
    tasks: list[tuple[str, str]] = [("in.mp3", "out.mp3")]
    with (
        patch("src.frontend.widgets.main_window.QTimer") as mock_timer_cls,
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
        patch("src.frontend.widgets.main_window.psutil"),
    ):
        mock_timer = MagicMock()
        mock_timer_cls.return_value = mock_timer
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool

        runner = _PoolRunner(tasks)
        runner.start()
        runner.set_paused(True)
        runner.set_paused(False)

        signal_emitted: list[Any] = []
        runner.pause_state_changed.connect(signal_emitted.append)
        runner.set_paused(False)

        assert len(signal_emitted) == 0


# === Additional coverage for _output_path ===


def test_output_path_value_error_same_drive() -> None:
    with patch("os.path.relpath", side_effect=ValueError("path is on mount 'D:', start on mount 'C:")):
        path: str = _output_path("D:\\music\\song.mp3", "C:\\")
        assert path.endswith("song_processed.mp3")


def test_output_path_pardir_relative() -> None:
    with patch("os.path.relpath", return_value="../other/file.mp3"):
        path: str = _output_path("C:\\other\\file.mp3", "C:\\")
        assert path.endswith("file_processed.mp3")


def test_build_tasks_duplicate_output_paths() -> None:
    tasks: list[tuple[str, str]] = _build_tasks(
        ["/base/dir/song.mp3", "/base/subdir/song.mp3"],
        "/base/dir",
    )
    assert len(tasks) == 2
    assert tasks[0][1] != tasks[1][1]
    assert "_2.mp3" in tasks[1][1]


def test_build_tasks_all_filtered_out() -> None:
    tasks: list[tuple[str, str]] = _build_tasks(["/path/file.txt", "/path/file.docx"], "/path")
    assert len(tasks) == 0


def test_build_tasks_case_insensitive() -> None:
    tasks: list[tuple[str, str]] = _build_tasks(["/path/file.WAV"], "/path")
    assert len(tasks) == 1


# === Additional coverage for _PoolRunner ===


def test_pool_runner_worker_processes_none_pool() -> None:
    runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
    processes = runner._worker_processes()
    assert processes == []


def test_pool_runner_worker_processes_with_pool(qtbot: QtBot) -> None:
    with (
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
        patch("src.frontend.widgets.main_window.psutil"),
    ):
        mock_pool = MagicMock()
        mock_worker = MagicMock()
        mock_worker.pid = 1234
        mock_worker.is_alive.return_value = True
        mock_pool._pool = [mock_worker]
        mock_pool_cls.return_value = mock_pool

        runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
        runner._pool = mock_pool

        processes = runner._worker_processes()
        assert len(processes) == 1


def test_pool_runner_set_paused_to_true() -> None:
    with (
        patch("src.frontend.widgets.main_window.QTimer") as mock_timer_cls,
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
        patch("src.frontend.widgets.main_window.psutil"),
        patch("src.frontend.widgets.main_window._PoolRunner._suspend_process_tree") as mock_suspend,
    ):
        mock_timer = MagicMock()
        mock_timer_cls.return_value = mock_timer
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool

        runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
        runner.start()

        signal_emitted: list[bool] = []
        runner.pause_state_changed.connect(signal_emitted.append)

        runner.set_paused(True)

        assert runner._is_paused is True
        assert runner._state.is_paused is True
        mock_suspend.assert_called_once()
        assert len(signal_emitted) == 1
        assert signal_emitted[0] is True


def test_pool_runner_set_paused_to_false() -> None:
    with (
        patch("src.frontend.widgets.main_window.QTimer") as mock_timer_cls,
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
        patch("src.frontend.widgets.main_window.psutil"),
        patch("src.frontend.widgets.main_window._PoolRunner._resume_process_trees") as mock_resume,
    ):
        mock_timer = MagicMock()
        mock_timer_cls.return_value = mock_timer
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool

        runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
        runner.start()
        runner._is_paused = True
        runner._suspended_trees = [(MagicMock(), [])]

        signal_emitted: list[bool] = []
        runner.pause_state_changed.connect(signal_emitted.append)

        runner.set_paused(False)

        assert runner._is_paused is False
        assert runner._state.is_paused is False
        assert runner._suspended_trees == []
        mock_resume.assert_called_once()
        assert len(signal_emitted) == 1
        assert signal_emitted[0] is False


def test_pool_runner_shutdown() -> None:
    with (
        patch("src.frontend.widgets.main_window.QTimer") as mock_timer_cls,
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
        patch("src.frontend.widgets.main_window.psutil"),
    ):
        mock_timer = MagicMock()
        mock_timer_cls.return_value = mock_timer
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool

        runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
        runner.start()

        runner.shutdown()

        mock_timer.stop.assert_called_once()
        mock_pool.terminate.assert_called_once()
        mock_pool.join.assert_called_once()
        assert runner._pool is None
        assert runner._queue is None


def test_pool_runner_shutdown_while_paused() -> None:
    with (
        patch("src.frontend.widgets.main_window.QTimer") as mock_timer_cls,
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
        patch("src.frontend.widgets.main_window.psutil"),
        patch("src.frontend.widgets.main_window._PoolRunner._resume_process_trees") as mock_resume,
    ):
        mock_timer = MagicMock()
        mock_timer_cls.return_value = mock_timer
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool

        runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
        runner.start()
        runner._is_paused = True
        runner._suspended_trees = [(MagicMock(), [])]

        runner.shutdown()

        mock_resume.assert_called_once()
        assert runner._is_paused is False
        assert runner._suspended_trees == []


def test_pool_runner_poll_done_message(qtbot: QtBot) -> None:
    with (
        patch("src.frontend.widgets.main_window.QTimer") as mock_timer_cls,
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue") as mock_queue_cls,
        patch("src.frontend.widgets.main_window.psutil"),
    ):
        mock_timer = MagicMock()
        mock_timer_cls.return_value = mock_timer
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool
        mock_queue = MagicMock()
        mock_queue.get_nowait.side_effect = [
            ("done", 0, "in.mp3", "ok"),
            Empty,
        ]
        mock_queue_cls.return_value = mock_queue

        runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
        runner.start()
        runner._poll()
        assert runner._state.done == 1
        assert runner._state.ok == 1


def test_pool_runner_poll_all_finished(qtbot: QtBot) -> None:
    with (
        patch("src.frontend.widgets.main_window.QTimer") as mock_timer_cls,
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue") as mock_queue_cls,
        patch("src.frontend.widgets.main_window.psutil"),
        patch("src.frontend.widgets.main_window._PoolRunner._finish") as mock_finish,
    ):
        mock_timer = MagicMock()
        mock_timer_cls.return_value = mock_timer
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool
        mock_queue = MagicMock()
        mock_queue.get_nowait.side_effect = Empty
        mock_queue_cls.return_value = mock_queue

        runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
        runner.start()
        runner._state.done = 1
        runner._state.total = 1
        runner._poll()
        mock_finish.assert_called_once()


def test_pool_runner_poll_all_finished_paused(qtbot: QtBot) -> None:
    with (
        patch("src.frontend.widgets.main_window.QTimer") as mock_timer_cls,
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue") as mock_queue_cls,
        patch("src.frontend.widgets.main_window.psutil"),
        patch("src.frontend.widgets.main_window._PoolRunner._resume_process_trees") as mock_resume,
        patch("src.frontend.widgets.main_window._PoolRunner._finish") as mock_finish,
    ):
        mock_timer = MagicMock()
        mock_timer_cls.return_value = mock_timer
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool
        mock_queue = MagicMock()
        mock_queue.get_nowait.side_effect = Empty
        mock_queue_cls.return_value = mock_queue

        runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
        runner.start()
        runner._is_paused = True
        runner._suspended_trees = [(MagicMock(), [])]
        runner._state.done = 1
        runner._state.total = 1
        runner._poll()
        mock_resume.assert_called_once()
        assert runner._is_paused is False
        mock_finish.assert_called_once()


def test_pool_runner_drain_empty_queue() -> None:
    with patch("src.frontend.widgets.main_window.Queue") as mock_queue_cls:
        mock_queue = MagicMock()
        mock_queue.get_nowait.side_effect = Empty
        mock_queue_cls.return_value = mock_queue
        runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
        runner._queue = mock_queue
        result = runner._drain()
        assert result is False


def test_pool_runner_drain_with_messages() -> None:
    with patch("src.frontend.widgets.main_window.Queue") as mock_queue_cls:
        mock_queue = MagicMock()
        mock_queue.get_nowait.side_effect = [
            ("step", 0, "file.wav", 1, "Loading", ""),
            ("done", 0, "file.wav", "ok"),
            Empty,
        ]
        mock_queue_cls.return_value = mock_queue
        runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
        runner._queue = mock_queue
        runner._state = ProcessingState(total=1)
        result = runner._drain()
        assert result is True
        assert runner._state.done == 1
        assert runner._state.ok == 1


def test_pool_runner_drain_none_queue() -> None:
    runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
    runner._queue = None
    result = runner._drain()
    assert result is False


def test_pool_runner_poll_pool_none() -> None:
    runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
    runner._pool = None
    runner._poll()


def test_pool_runner_finish() -> None:
    with (
        patch("src.frontend.widgets.main_window.QTimer") as mock_timer_cls,
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
        patch("src.frontend.widgets.main_window.psutil"),
    ):
        mock_timer = MagicMock()
        mock_timer_cls.return_value = mock_timer
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool
        runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
        runner.start()
        signal_emitted: list[ProcessingState] = []
        runner.finished.connect(signal_emitted.append)
        runner._finish()
        mock_timer.stop.assert_called_once()
        mock_pool.close.assert_called_once()
        mock_pool.join.assert_called_once()
        assert runner._pool is None
        assert runner._queue is None
        assert len(signal_emitted) == 1
        assert signal_emitted[0].total == 1


def test_pool_runner_finish_while_paused() -> None:
    # Test _finish when paused - _finish doesn't handle paused state directly,
    # that's handled in _poll before calling _finish
    with (
        patch("src.frontend.widgets.main_window.QTimer") as mock_timer_cls,
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
        patch("src.frontend.widgets.main_window.psutil"),
    ):
        mock_timer = MagicMock()
        mock_timer_cls.return_value = mock_timer
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool

        runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
        runner.start()
        runner._is_paused = True
        runner._suspended_trees = [(MagicMock(), [])]

        signal_emitted: list[ProcessingState] = []
        runner.finished.connect(signal_emitted.append)

        runner._finish()

        mock_timer.stop.assert_called_once()
        mock_pool.close.assert_called_once()
        mock_pool.join.assert_called_once()
        assert runner._pool is None
        assert runner._queue is None
        assert len(signal_emitted) == 1


def test_pool_runner_poll_finished_while_paused() -> None:
    # Test _poll when all finished and paused - should resume and then finish
    with (
        patch("src.frontend.widgets.main_window.QTimer") as mock_timer_cls,
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue") as mock_queue_cls,
        patch("src.frontend.widgets.main_window.psutil"),
        patch("src.frontend.widgets.main_window._PoolRunner._resume_process_trees") as mock_resume,
        patch("src.frontend.widgets.main_window._PoolRunner._finish") as mock_finish,
    ):
        mock_timer = MagicMock()
        mock_timer_cls.return_value = mock_timer
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool
        mock_queue = MagicMock()
        mock_queue.get_nowait.side_effect = Empty
        mock_queue_cls.return_value = mock_queue

        runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
        runner.start()
        runner._is_paused = True
        runner._suspended_trees = [(MagicMock(), [])]
        runner._state.done = 1
        runner._state.total = 1

        runner._poll()

        mock_resume.assert_called_once()
        assert runner._is_paused is False
        mock_finish.assert_called_once()


def test_main_window_on_start_processing_empty_tasks(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._tasks = []
    window._set_busy(False)
    with patch("src.frontend.widgets.main_window.check_ffmpeg_installed", return_value=True):
        window._on_start_processing()
    assert window._is_processing is False


def test_main_window_on_start_processing_already_processing(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._tasks = [("in.mp3", "out.mp3")]
    window._is_processing = True
    with patch("src.frontend.widgets.main_window.check_ffmpeg_installed", return_value=True):
        window._on_start_processing()
    assert window._is_processing is True


def test_main_window_on_pause_failed_with_widget(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    mock_widget = MagicMock()
    window._processing_widget = mock_widget
    window._on_pause_failed("Test error")
    mock_widget.set_pause_pending.assert_called_once_with(False)


def test_main_window_on_pause_failed_no_widget(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._processing_widget = None
    window._on_pause_failed("Test error")


def test_main_window_on_state_updated(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    mock_widget = MagicMock()
    window._processing_widget = mock_widget
    state = ProcessingState(total=10, done=5)
    window._on_state_updated(state)
    mock_widget.update_state.assert_called_once_with(state)


def test_main_window_on_state_updated_no_widget(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._processing_widget = None
    state = ProcessingState(total=10, done=5)
    window._on_state_updated(state)


def test_main_window_on_processing_finished(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    mock_runner = MagicMock()
    window._runner = mock_runner
    state = ProcessingState(total=5, done=5, ok=3, skipped=1, failed=1)
    window._on_processing_finished(state)
    assert window._is_processing is False
    assert window._runner is None
    assert "Processing done" in window._file_label.text()


def test_main_window_on_processing_finished_no_runner(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._runner = None
    state = ProcessingState(total=5, done=5)
    window._on_processing_finished(state)


def test_pool_runner_suspend_process_tree() -> None:
    with (
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
        patch("src.frontend.widgets.main_window.psutil"),
    ):
        mock_pool = MagicMock()
        mock_worker = MagicMock()
        mock_worker.pid = 1234
        mock_worker.is_alive.return_value = True
        mock_pool._pool = [mock_worker]
        mock_pool_cls.return_value = mock_pool
        runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
        runner.start()
        runner._pool = mock_pool
        runner._suspend_process_tree()
        assert len(runner._suspended_trees) == 1


def test_pool_runner_suspend_process_tree_no_processes() -> None:
    with (
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
        patch("src.frontend.widgets.main_window.psutil"),
    ):
        mock_pool = MagicMock()
        mock_pool._pool = []
        mock_pool_cls.return_value = mock_pool
        runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
        runner.start()
        runner._pool = mock_pool
        runner._suspend_process_tree()
        assert runner._suspended_trees == []


def test_pool_runner_suspend_process_tree_with_children() -> None:
    with (
        patch("src.frontend.widgets.main_window.Pool") as mock_pool_cls,
        patch("src.frontend.widgets.main_window.Queue"),
        patch("src.frontend.widgets.main_window.psutil") as mock_psutil,
    ):
        mock_pool = MagicMock()
        mock_worker = MagicMock()
        mock_worker.pid = 1234
        mock_worker.is_alive.return_value = True
        mock_child = MagicMock()
        mock_child.is_alive.return_value = True
        mock_worker.children.return_value = [mock_child]
        mock_pool._pool = [mock_worker]
        mock_pool_cls.return_value = mock_pool

        # Mock psutil.Process to return a mock that has the right attributes
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.is_alive.return_value = True
        mock_proc.children.return_value = [mock_child]
        mock_psutil.Process.return_value = mock_proc

        runner = _PoolRunner(tasks=[("in.mp3", "out.mp3")])
        runner.start()
        # Override the pool set by start() with our mock that has workers
        runner._pool = mock_pool

        runner._suspend_process_tree()

        assert len(runner._suspended_trees) == 1
        assert len(runner._suspended_trees[0][1]) == 1


def test_pool_runner_resume_process_trees() -> None:
    mock_worker = MagicMock()
    mock_child = MagicMock()
    trees: list[tuple[Any, list[Any]]] = [(mock_worker, [mock_child])]
    _PoolRunner._resume_process_trees(trees)
    mock_child.resume.assert_called_once()
    mock_worker.resume.assert_called_once()


def test_pool_runner_resume_process_trees_with_error() -> None:
    mock_worker = MagicMock()
    mock_child = MagicMock()
    mock_child.resume.side_effect = psutil.Error("Child error")
    trees: list[tuple[Any, list[Any]]] = [(mock_worker, [mock_child])]
    with pytest.raises(RuntimeError):
        _PoolRunner._resume_process_trees(trees)


def test_pool_runner_resume_process_trees_no_such_process() -> None:
    mock_worker = MagicMock()
    mock_child = MagicMock()
    mock_child.resume.side_effect = psutil.NoSuchProcess(1234)
    trees: list[tuple[Any, list[Any]]] = [(mock_worker, [mock_child])]
    _PoolRunner._resume_process_trees(trees)


def test_scan_folder_excluded_dirs(tmp_path: Path) -> None:
    excluded = tmp_path / "__pycache__"
    excluded.mkdir()
    (excluded / "cached.pyc").write_text("dummy")
    audio_file = tmp_path / "test.wav"
    audio_file.write_text("dummy")
    found = _scan_folder(str(tmp_path))
    assert len(found) == 1
    assert str(audio_file) in found


def test_scan_folder_empty_folder(tmp_path: Path) -> None:
    found = _scan_folder(str(tmp_path))
    assert found == []


def test_scan_folder_nested_subdirs(tmp_path: Path) -> None:
    sub1 = tmp_path / "sub1"
    sub2 = tmp_path / "sub1" / "sub2"
    sub1.mkdir()
    sub2.mkdir()
    (sub1 / "a.wav").write_text("dummy")
    (sub2 / "b.flac").write_text("dummy")
    found = _scan_folder(str(tmp_path))
    assert len(found) == 2


def test_file_dialog_filter_includes_all_supported() -> None:
    f_filter = _file_dialog_filter()
    for ext in SUPPORTED:
        assert f"*{ext}" in f_filter
        assert f"*{ext.upper()}" in f_filter


def test_file_dialog_filter_format() -> None:
    f_filter = _file_dialog_filter()
    assert f_filter.startswith("Audio Files")
    assert ";;" in f_filter
    assert "All Files (*)" in f_filter
