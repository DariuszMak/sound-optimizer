from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from src.main import (
    check_ffmpeg_installed,
    collect_audio_files,
    main,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_check_ffmpeg_installed_present(caplog: pytest.LogCaptureFixture) -> None:
    with (
        patch("src.main.shutil.which", return_value="/usr/bin/ffmpeg") as mock_which,
        caplog.at_level(logging.ERROR, logger="src.main"),
    ):
        result = check_ffmpeg_installed()

    mock_which.assert_called_once_with("ffmpeg")
    assert result is True
    assert caplog.records == []


def test_check_ffmpeg_installed_missing(caplog: pytest.LogCaptureFixture) -> None:
    with (
        patch("src.main.shutil.which", return_value=None) as mock_which,
        caplog.at_level(logging.ERROR, logger="src.main"),
    ):
        result = check_ffmpeg_installed()

    mock_which.assert_called_once_with("ffmpeg")
    assert result is False
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.ERROR
    assert "ffmpeg" in record.message
    assert "\033[91m" in record.message
    assert "\033[0m" in record.message


def test_collect_audio_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    (input_dir / "valid1.wav").touch()
    (input_dir / "valid2.mp3").touch()
    (input_dir / "invalid.txt").touch()

    excluded_dir = input_dir / "processed"
    excluded_dir.mkdir()
    (excluded_dir / "skipped.wav").touch()

    monkeypatch.setattr("src.main.INPUT_ROOT", str(input_dir))
    monkeypatch.setattr("src.main.OUTPUT_ROOT", str(output_dir))
    monkeypatch.setattr("src.main.EXCLUDED_DIRS", {"processed"})

    tasks = collect_audio_files()
    assert len(tasks) == 2
    assert any("valid1.wav" in t[0] for t in tasks)
    assert any("valid2.mp3" in t[0] for t in tasks)


def test_collect_audio_files_edge_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    nested_dir = input_dir / "nested"
    nested_dir.mkdir()

    (nested_dir / "test.WAV").touch()
    (nested_dir / "test.FLAC").touch()

    excluded_dir = input_dir / "__pycache__"
    excluded_dir.mkdir()
    (excluded_dir / "test.mp3").touch()

    monkeypatch.setattr("src.main.INPUT_ROOT", str(input_dir))
    monkeypatch.setattr("src.main.OUTPUT_ROOT", str(tmp_path / "output"))

    tasks = collect_audio_files()
    assert len(tasks) == 2
    extensions = [os.path.splitext(t[0])[1] for t in tasks]
    assert ".WAV" in extensions
    assert ".FLAC" in extensions

    monkeypatch.setattr("src.main.EXCLUDED_DIRS", {".venv", "processed", "__pycache__", "nested"})
    tasks_excluded = collect_audio_files()
    assert len(tasks_excluded) == 0


def test_collect_audio_files_empty_and_mixed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setattr("src.main.INPUT_ROOT", str(empty_dir))
    monkeypatch.setattr("src.main.OUTPUT_ROOT", str(tmp_path / "out_empty"))
    assert collect_audio_files() == []

    mixed_dir = tmp_path / "mixed"
    mixed_dir.mkdir()
    (mixed_dir / "track.wav").touch()
    (mixed_dir / "notes.txt").touch()
    monkeypatch.setattr("src.main.INPUT_ROOT", str(mixed_dir))
    monkeypatch.setattr("src.main.OUTPUT_ROOT", str(tmp_path / "out_mixed"))
    result = collect_audio_files()
    assert len(result) == 1
    assert result[0][0].endswith("track.wav")


def test_main() -> None:
    with (
        patch("src.main.check_ffmpeg_installed", return_value=True),
        patch("src.main.QApplication") as mock_app_cls,
        patch("src.frontend.widgets.main_window.MainWindow") as mock_window,
        patch("sys.exit"),
    ):
        mock_app = MagicMock()
        mock_app_cls.return_value = mock_app
        main()

    mock_app_cls.assert_called_once()
    mock_app.setApplicationName.assert_called_once_with("Sound Optimizer")
    mock_app.setOrganizationName.assert_called_once_with("Sound Optimizer")
    mock_window.assert_called_once()
    window = mock_window.return_value
    window.show.assert_called_once()
    mock_app.exec.assert_called_once()


def test_main_missing_ffmpeg() -> None:
    with (
        patch("src.main.check_ffmpeg_installed", return_value=False) as mock_check,
        patch("src.main.collect_audio_files") as mock_collect,
    ):
        main()

    mock_check.assert_called_once()
    mock_collect.assert_not_called()
