from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from pytestqt.qtbot import QtBot
from PySide6.QtWidgets import QMessageBox

from src.frontend.widgets.main_window import (
    MainWindow,
    _PoolRunner,
    _build_tasks,
    _file_dialog_filter,
    _output_path,
    _scan_folder,
    create_app,
)
from src.main import SUPPORTED


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
    with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
        window._set_tasks([])
        mock_info.assert_called_once()


def test_set_tasks_valid(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    tasks: list[tuple[str, str]] = [("input.mp3", "output.mp3")]
    window._set_tasks(tasks)
    assert window._start_button.isEnabled() is True
    assert "1 file(s) selected" in window._file_label.text()


@patch("PySide6.QtWidgets.QFileDialog.getOpenFileNames")
def test_on_select_files(mock_file_dialog: MagicMock, qtbot: QtBot)
