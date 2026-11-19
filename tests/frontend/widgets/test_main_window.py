from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QMessageBox

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

        signal_emitted = []
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

        signal_emitted = []
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

        signal_emitted = []
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


def test_pool_runner_worker_processes_with_pool() -> None:
    tasks: list[tuple[str, str]] = [("in.mp3", "out.mp3")]
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

        runner = _PoolRunner(tasks)
        runner.start()

        processes = runner._worker_processes()
        assert len(processes) == 1


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

        signal_emitted = []
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

        signal_emitted = []
        runner.pause_state_changed.connect(signal_emitted.append)
        runner.set_paused(False)

        assert len(signal_emitted) == 0
