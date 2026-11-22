from __future__ import annotations

import logging
import os
from io import StringIO
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from rich.console import Console

from src.main import (
    Dashboard,
    _bar,
    _format_duration,
    check_ffmpeg_installed,
    collect_audio_files,
    main,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _render_dashboard(dashboard: Dashboard, width: int, height: int) -> str:
    buffer = StringIO()
    console = Console(file=buffer, width=width, height=height, force_terminal=False, color_system=None)
    console.print(dashboard)
    return buffer.getvalue()


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


def test_format_duration() -> None:
    assert _format_duration(0) == "00:00"
    assert _format_duration(-5) == "00:00"
    assert _format_duration(65) == "01:05"
    assert _format_duration(3661) == "1:01:01"


def test_bar() -> None:
    assert _bar(0.5, 10) == "█████░░░░░"
    assert _bar(0.0, 4) == "░░░░"
    assert _bar(1.0, 4) == "████"
    assert _bar(2.0, 4) == "████"
    assert _bar(-1.0, 4) == "░░░░"


def test_dashboard_apply_counts() -> None:
    dashboard = Dashboard(4)
    dashboard.apply(("step", 0, "a.wav", 1, "Loading", ""))
    dashboard.apply(("step", 1, "b.wav", 2, "Trim Silence", ""))
    assert set(dashboard.workers) == {0, 1}

    dashboard.apply(("done", 0, "a.wav", "ok"))
    dashboard.apply(("done", 1, "b.wav", "skipped"))
    dashboard.apply(("done", 2, "c.wav", "failed"))

    assert dashboard.workers == {}
    assert dashboard.done == 3
    assert dashboard.ok == 1
    assert dashboard.skipped == 1
    assert dashboard.failed == 1


def test_dashboard_render_wide() -> None:
    dashboard = Dashboard(4)
    dashboard.apply(("step", 3, "song.wav", 2, "Trim Silence", "Dry: -20.0 LUFS | EQ: -19.0 LUFS | Pre-Gain: +4.0 dB"))

    output = _render_dashboard(dashboard, width=140, height=20)
    assert "0/4" in output
    assert "W03" in output
    assert "2/7" in output
    assert "Trim Silence" in output
    assert "song.wav" in output
    assert "Dry: -20.0 LUFS" in output


def test_dashboard_render_eta() -> None:
    dashboard = Dashboard(2)
    dashboard.apply(("done", 0, "a.wav", "ok"))

    output = _render_dashboard(dashboard, width=100, height=10)
    assert "1/2" in output
    assert "ETA" in output


def test_dashboard_render_narrow_limits_rows_and_width() -> None:
    dashboard = Dashboard(32)
    for worker_id in range(5):
        dashboard.apply(("step", worker_id, f"very_long_file_name_{worker_id}.flac", 3, "Remove Silences", "details"))

    width = 30
    output = _render_dashboard(dashboard, width=width, height=6)
    lines = [line for line in output.splitlines() if line.strip()]

    assert all(len(line) <= width for line in lines)
    assert "+3 more workers" in output
    assert "W00" in output
    assert "W01" in output
    assert "W04" not in output
    assert "Remove Silences" not in output
    assert "details" not in output


def test_dashboard_rich_console_zero_total() -> None:
    dashboard = Dashboard(0)
    dashboard.apply(("step", 0, "file.wav", 1, "Loading", ""))

    string_io = StringIO()
    console = Console(file=string_io, force_terminal=True, width=80)
    rendered = list(dashboard.__rich_console__(console, console.options))

    assert len(rendered) > 0
    assert "0/0" in str(rendered[0])
