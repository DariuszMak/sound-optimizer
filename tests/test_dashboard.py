from __future__ import annotations

from io import StringIO

from rich.console import Console

from src.dashboard import Dashboard, _bar, _format_duration


def _render_dashboard(dashboard: Dashboard, width: int, height: int) -> str:
    buffer = StringIO()
    console = Console(file=buffer, width=width, height=height, force_terminal=False, color_system=None)
    console.print(dashboard)
    return buffer.getvalue()


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
