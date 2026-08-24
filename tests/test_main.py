from __future__ import annotations

import logging
import multiprocessing
import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import numpy as np
from pydub import AudioSegment

from src import main as main_module
from src.main import (
    EQ_BANDS,
    EQ_Q,
    MAX_PRE_GAIN_DB,
    NUMBER_OF_STEPS,
    SUPPORTED,
    TARGET_LUFS,
    TRIM_THRESHOLD_DB,
    TRUE_PEAK_CEILING_DB,
    _init_worker,
    _measure_lufs,
    _peaking_biquad,
    apply_eq_for_metering,
    check_ffmpeg_installed,
    collect_audio_files,
    dynamic_loudness_control,
    export_audio,
    format_loudness_params,
    limiter,
    load_audio,
    main,
    process_audio,
    remove_long_silences_multi,
    smooth_gain,
    trim_silence_multi,
)
from tests.conftest import generate_sine_wave

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_check_ffmpeg_installed_present(caplog: pytest.LogCaptureFixture) -> None:
    """Test that no warning is logged and True is returned when ffmpeg is found."""
    with (
        patch("src.main.shutil.which", return_value="/usr/bin/ffmpeg") as mock_which,
        caplog.at_level(logging.ERROR, logger="src.main"),
    ):
        result = check_ffmpeg_installed()

    mock_which.assert_called_once_with("ffmpeg")
    assert result is True
    assert caplog.records == []


def test_check_ffmpeg_installed_missing(caplog: pytest.LogCaptureFixture) -> None:
    """Test that a red error is logged and False is returned when ffmpeg is missing."""
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


def test_peaking_biquad() -> None:
    """Test peaking biquad filter coefficient generation."""
    b, a = _peaking_biquad(1000.0, 3.0, 1.0, 44100)
    assert len(b) == 3
    assert len(a) == 3
    assert b.dtype == np.float64
    assert a.dtype == np.float64


def test_apply_eq_for_metering(sample_rate: int) -> None:
    """Test EQ filter application for LUFS metering."""
    sine = generate_sine_wave(duration_sec=0.1, sr=sample_rate)
    out = apply_eq_for_metering(sine, sample_rate)

    assert out.shape == sine.shape
    assert out.dtype == np.float32

    bands = [
        (1000.0, 0.0),
        (24000.0, 5.0),
        (1000.0, 5.0),
    ]
    out2 = apply_eq_for_metering(sine, sample_rate, bands=bands)
    assert out2.shape == sine.shape


def test_trim_silence_multi(sample_rate: int) -> None:
    """Test that leading and trailing silences are accurately trimmed."""
    silence = np.zeros(sample_rate * 1, dtype=np.float32)
    sine = generate_sine_wave(duration_sec=1.0, sr=sample_rate)

    signal = np.concatenate([silence, sine, silence])

    trimmed = trim_silence_multi(signal, top_db=45.0)

    assert len(trimmed) > 0
    assert len(trimmed) <= sample_rate * 1.01
    assert len(trimmed) >= sample_rate * 0.99

    empty_1d = trim_silence_multi(np.zeros(100, dtype=np.float32), top_db=45.0)
    assert len(empty_1d) == 0

    empty_2d = trim_silence_multi(np.zeros((100, 2), dtype=np.float32), top_db=45.0)
    assert len(empty_2d) == 0
    assert empty_2d.shape[1] == 2


def test_remove_long_silences_multi(sample_rate: int) -> None:
    """Test that silences exceeding the minimum duration are removed."""
    sine1 = generate_sine_wave(duration_sec=1.0, sr=sample_rate)
    silence = np.zeros(int(sample_rate * 2.5), dtype=np.float32)
    sine2 = generate_sine_wave(duration_sec=1.0, sr=sample_rate)

    signal = np.concatenate([sine1, silence, sine2]).reshape(-1, 1)

    processed = remove_long_silences_multi(signal, sr=sample_rate, silence_db=45.0, min_silence_sec=2.0)

    assert len(processed) < sample_rate * 2.5
    assert len(processed) >= int(sample_rate * 1.99)

    empty_2d = remove_long_silences_multi(np.zeros((sample_rate * 3, 2), dtype=np.float32), sample_rate)
    assert len(empty_2d) == 0
    assert empty_2d.shape[1] == 2


def test_measure_lufs(sample_rate: int) -> None:
    """Test that LUFS metering requires a minimum audio length and returns valid floats."""
    valid_audio = generate_sine_wave(duration_sec=1.0, sr=sample_rate)
    short_audio = generate_sine_wave(duration_sec=0.1, sr=sample_rate)

    lufs_valid = _measure_lufs(valid_audio, sample_rate)
    lufs_invalid = _measure_lufs(short_audio, sample_rate)

    assert isinstance(lufs_valid, float)
    assert lufs_invalid is None


def test_smooth_gain(sample_rate: int) -> None:
    """Test gain smoothing algorithm."""
    gains = np.array([0.0, 5.0, -5.0, 2.0], dtype=np.float32)
    smoothed = smooth_gain(gains, sample_rate, attack_sec=0.1, release_sec=0.2)

    assert smoothed.shape == gains.shape
    assert smoothed.dtype == np.float32


def test_dynamic_loudness_control(sample_rate: int) -> None:
    """Test dynamic loudness control over varying volumes."""

    sine = generate_sine_wave(duration_sec=9.0, sr=sample_rate).reshape(-1, 1)
    out = dynamic_loudness_control(sine, sample_rate, target_lufs=-16.0, window_sec=8.0)

    assert out.shape == sine.shape
    assert out.dtype == np.float32

    short_sine = generate_sine_wave(duration_sec=1.0, sr=sample_rate).reshape(-1, 1)
    out_short = dynamic_loudness_control(short_sine, sample_rate, target_lufs=-16.0, window_sec=8.0)
    np.testing.assert_array_equal(out_short, short_sine)

    silence = np.zeros((sample_rate * 9, 1), dtype=np.float32)
    out_silence = dynamic_loudness_control(silence, sample_rate, target_lufs=-16.0, window_sec=8.0)
    np.testing.assert_array_equal(out_silence, silence)


def test_limiter(sample_rate: int) -> None:
    """Test that the true peak limiter enforces the maximum ceiling."""
    loud_signal = generate_sine_wave(duration_sec=0.5, sr=sample_rate, amp=2.0)
    ceiling_db = -1.0
    ceiling_lin = 10 ** (ceiling_db / 20)

    limited_signal = limiter(loud_signal, sr=sample_rate, ceiling_db=ceiling_db)
    max_peak = float(np.max(np.abs(limited_signal)))

    assert max_peak <= ceiling_lin + 0.05
    assert max_peak > 0.0

    loud_2d = np.column_stack((loud_signal, loud_signal))
    limited_2d = limiter(loud_2d, sr=sample_rate, ceiling_db=ceiling_db)

    assert limited_2d.shape == loud_2d.shape
    max_peak_2d = float(np.max(np.abs(limited_2d)))
    assert max_peak_2d <= ceiling_lin + 0.05


def test_load_and_export_audio(tmp_path: Path, sample_rate: int) -> None:
    """Test audio I/O mechanisms."""
    sine = generate_sine_wave(duration_sec=0.5, sr=sample_rate)
    sine_2d = np.column_stack((sine, sine))

    out_path = str(tmp_path / "test_out.mp3")

    export_audio(sine_2d, sample_rate, out_path, audio_format="mp3")
    assert os.path.exists(out_path)

    loaded, sr = load_audio(out_path)
    assert loaded is not None
    assert sr is not None
    assert loaded.ndim == 2

    invalid_path = str(tmp_path / "does_not_exist.mp3")
    loaded_inv, sr_inv = load_audio(invalid_path)
    assert loaded_inv is None
    assert sr_inv is None


def test_process_audio_end_to_end(tmp_path: Path, sample_rate: int) -> None:
    """Test the entire audio pipeline by mocking file I/O on disk."""
    sine = generate_sine_wave(duration_sec=2.0, sr=sample_rate, amp=0.5)
    sine_int16 = (sine * 32767).astype(np.int16)

    segment = AudioSegment(sine_int16.tobytes(), frame_rate=sample_rate, sample_width=2, channels=1)

    input_wav = str(tmp_path / "test_input.wav")
    output_mp3 = str(tmp_path / "test_processed.mp3")

    segment.export(input_wav, format="wav")

    task = (input_wav, output_mp3)
    process_audio(task)

    assert os.path.exists(output_mp3)
    assert os.path.getsize(output_mp3) > 0


def test_process_audio_edge_cases(tmp_path: Path, sample_rate: int) -> None:
    """Test early returns and multichannel handling in process_audio."""

    out_existing = str(tmp_path / "exists.mp3")
    with open(out_existing, "w") as f:
        f.write("dummy")
    process_audio(("nonexistent.wav", out_existing))

    process_audio(("invalid.wav", str(tmp_path / "out_invalid.mp3")))

    silence = np.zeros(sample_rate * 2, dtype=np.float32)
    segment_sil = AudioSegment(
        (silence * 32767).astype(np.int16).tobytes(), frame_rate=sample_rate, sample_width=2, channels=1
    )
    silence_in = str(tmp_path / "silence.wav")
    silence_out = str(tmp_path / "silence_out.mp3")
    segment_sil.export(silence_in, format="wav")

    process_audio((silence_in, silence_out))
    assert not os.path.exists(silence_out)

    sine = generate_sine_wave(duration_sec=3.0, sr=sample_rate)
    sine_2d = np.column_stack((sine, sine))
    segment_multi = AudioSegment(
        (sine_2d * 32767).astype(np.int16).tobytes(), frame_rate=sample_rate, sample_width=2, channels=2
    )
    multi_in = str(tmp_path / "multi.wav")
    multi_out = str(tmp_path / "multi_out.mp3")
    segment_multi.export(multi_in, format="wav")

    process_audio((multi_in, multi_out))
    assert os.path.exists(multi_out)


def test_collect_audio_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test file discovery filtering by extension and excluded directories."""
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


def test_main(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the main entrypoint and multiprocessing pool handling."""

    with (
        patch("src.main.check_ffmpeg_installed", return_value=True),
        patch("src.main.collect_audio_files", return_value=[]),
        patch("src.main.wait_for_keypress") as mock_wait_empty,
    ):
        main()

    mock_wait_empty.assert_called_once()

    tasks = [("in.wav", "out.mp3")]
    with (
        patch("src.main.check_ffmpeg_installed", return_value=True),
        patch("src.main.collect_audio_files", return_value=tasks),
        patch("src.main.Pool") as mock_pool,
        patch("src.main.tqdm") as mock_tqdm,
        patch("src.main.wait_for_keypress") as mock_wait,
    ):
        mock_pool_instance = MagicMock()
        mock_pool.return_value.__enter__.return_value = mock_pool_instance
        mock_pool_instance.imap_unordered.return_value = iter([None])
        mock_tqdm.return_value = iter([None])

        main()

        mock_pool_instance.imap_unordered.assert_called_once()
        mock_wait.assert_called_once()

        mock_tqdm.assert_called_once()
        assert mock_tqdm.call_args.kwargs["dynamic_ncols"] is True


def test_main_missing_ffmpeg() -> None:
    """Test that main() exits early without collecting or processing files when ffmpeg is missing."""
    with (
        patch("src.main.check_ffmpeg_installed", return_value=False) as mock_check,
        patch("src.main.collect_audio_files") as mock_collect,
        patch("src.main.Pool") as mock_pool,
        patch("src.main.wait_for_keypress") as mock_wait,
    ):
        main()

        mock_check.assert_called_once()
        mock_collect.assert_not_called()
        mock_pool.assert_not_called()
        mock_wait.assert_called_once()


def test_wait_for_keypress_non_interactive() -> None:
    """Test that non-TTY stdin (piped input, CI) returns immediately without blocking."""
    with (
        patch("src.main.sys.stdin.isatty", return_value=False),
        patch("src.main.os.name", "nt"),
    ):
        main_module.wait_for_keypress()


def test_wait_for_keypress_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the Windows code path uses msvcrt.getch() to read a single keypress."""
    import sys
    import types

    mock_msvcrt = types.ModuleType("msvcrt")
    mock_msvcrt.getch = MagicMock(return_value=b"x")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "msvcrt", mock_msvcrt)

    with (
        patch("src.main.sys.stdin.isatty", return_value=True),
        patch("src.main.os.name", "nt"),
    ):
        main_module.wait_for_keypress()

    mock_msvcrt.getch.assert_called_once()


def test_wait_for_keypress_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the POSIX code path reads a single raw keypress via termios/tty."""
    import sys
    import types

    mock_termios = types.ModuleType("termios")
    mock_termios.tcgetattr = MagicMock(return_value=["old_settings"])  # type: ignore[attr-defined]
    mock_termios.tcsetattr = MagicMock()  # type: ignore[attr-defined]
    mock_termios.TCSADRAIN = 1  # type: ignore[attr-defined]

    mock_tty = types.ModuleType("tty")
    mock_tty.setraw = MagicMock()  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "termios", mock_termios)
    monkeypatch.setitem(sys.modules, "tty", mock_tty)

    with (
        patch("src.main.sys.stdin.isatty", return_value=True),
        patch("src.main.sys.stdin.fileno", return_value=0),
        patch("src.main.sys.stdin.read", return_value="x") as mock_read,
        patch("src.main.os.name", "posix"),
    ):
        main_module.wait_for_keypress()

    mock_tty.setraw.assert_called_once_with(0)
    mock_read.assert_called_once_with(1)
    mock_termios.tcsetattr.assert_called_once_with(0, 1, ["old_settings"])


def test_format_loudness_params() -> None:
    """Test formatting of sound loudness parameters for console output."""
    formatted = format_loudness_params(lufs_dry=-20.5, lufs_eq=-18.2, gain_db=4.5)
    assert "Dry: -20.5 LUFS" in formatted
    assert "EQ: -18.2 LUFS" in formatted
    assert "Pre-Gain: +4.5 dB" in formatted

    formatted_none = format_loudness_params(lufs_dry=None, lufs_eq=None, gain_db=None)
    assert "Dry: N/A" in formatted_none
    assert "EQ: N/A" in formatted_none
    assert "Pre-Gain: 0.0 dB" in formatted_none


def test_init_worker() -> None:
    """Test worker slot initialization for multiprocessing."""
    counter = multiprocessing.Value("i", 0)

    _init_worker(counter)
    assert main_module._worker_slot == 0
    assert counter.value == 1

    _init_worker(counter)
    assert main_module._worker_slot == 1
    assert counter.value == 2


def test_process_audio_visualization(tmp_path: Path, sample_rate: int) -> None:
    """Test process_audio progress bar visualization updates and loudness parameters display."""
    sine = generate_sine_wave(duration_sec=2.0, sr=sample_rate, amp=0.5)
    sine_int16 = (sine * 32767).astype(np.int16)
    segment = AudioSegment(sine_int16.tobytes(), frame_rate=sample_rate, sample_width=2, channels=1)

    input_wav = str(tmp_path / "test_vis_input.wav")
    output_mp3 = str(tmp_path / "test_vis_output.mp3")
    segment.export(input_wav, format="wav")

    with patch("src.main.tqdm") as mock_tqdm:
        mock_pbar = MagicMock()
        mock_tqdm.return_value = mock_pbar

        process_audio((input_wav, output_mp3))

        mock_tqdm.assert_called_once()
        assert mock_tqdm.call_args.kwargs["dynamic_ncols"] is True
        assert mock_pbar.update.call_count == NUMBER_OF_STEPS
        mock_pbar.set_postfix_str.assert_called_once()
        postfix_arg = mock_pbar.set_postfix_str.call_args[0][0]
        assert "Dry:" in postfix_arg
        assert "Pre-Gain:" in postfix_arg
        mock_pbar.close.assert_called_once()


def test_constants() -> None:
    assert [
        (60.0, 20 * np.log10(1.40)),
        (230.0, 20 * np.log10(1.20)),
        (910.0, 20 * np.log10(0.60)),
        (3600.0, 20 * np.log10(0.90)),
        (14000.0, 20 * np.log10(1.10)),
    ] == EQ_BANDS
    assert EQ_Q == 1.0
    assert TARGET_LUFS == -16.0
    assert TRIM_THRESHOLD_DB == 45.0
    assert MAX_PRE_GAIN_DB == 30.0
    assert TRUE_PEAK_CEILING_DB == -1.0
    assert SUPPORTED == (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".wma", ".mpc")


def test_peaking_biquad_edge_cases() -> None:
    b_zero, a_zero = _peaking_biquad(1000.0, 0.0, 1.0, 44100)
    np.testing.assert_almost_equal(b_zero, a_zero)
    b_neg, a_neg = _peaking_biquad(1000.0, -5.0, 1.0, 44100)
    assert len(b_neg) == 3
    assert len(a_neg) == 3
    b_nyq, a_nyq = _peaking_biquad(22050.0, 3.0, 1.0, 44100)
    assert len(b_nyq) == 3
    assert len(a_nyq) == 3


def test_apply_eq_for_metering_edge_cases(sample_rate: int) -> None:
    sine = generate_sine_wave(duration_sec=0.1, sr=sample_rate)
    out_nyq = apply_eq_for_metering(sine, sample_rate, bands=[(sample_rate / 2.0, 5.0)])
    np.testing.assert_array_equal(out_nyq, sine)
    out_zero = apply_eq_for_metering(sine, sample_rate, bands=[(1000.0, 0.0)])
    np.testing.assert_array_almost_equal(out_zero, sine, decimal=5)
    out_all = apply_eq_for_metering(sine, sample_rate, bands=[(100.0, 0.0), (1000.0, 0.0)])
    np.testing.assert_array_almost_equal(out_all, sine, decimal=5)


def test_trim_silence_multi_edge_cases() -> None:
    threshold = 10 ** (45.0 / -20)
    y_exact = np.array([threshold, threshold], dtype=np.float32)
    out_exact = trim_silence_multi(y_exact, 45.0)
    assert len(out_exact) == 0

    y_partial = np.array([threshold * 0.5, threshold * 1.1, threshold * 0.5], dtype=np.float32)
    out_partial = trim_silence_multi(y_partial, 45.0)
    assert len(out_partial) == 1
    assert out_partial[0] == np.float32(threshold * 1.1)


def test_remove_long_silences_multi_edge_cases(sample_rate: int) -> None:
    threshold = 10 ** (45.0 / -20)
    min_silence_len = int(sample_rate * 2.0)
    fade_len = int(sample_rate * 0.05)

    y_exact = np.full(min_silence_len, threshold * 0.9, dtype=np.float32)
    out_exact = remove_long_silences_multi(y_exact, sample_rate, silence_db=45.0, min_silence_sec=2.0)
    assert len(out_exact) == 0

    y_adj = np.concatenate([y_exact, y_exact])
    out_adj = remove_long_silences_multi(y_adj, sample_rate, silence_db=45.0, min_silence_sec=2.0)
    assert len(out_adj) == 0

    y_fade = np.concatenate([np.full(fade_len * 3, threshold * 2.0, dtype=np.float32), y_exact])
    out_fade = remove_long_silences_multi(y_fade, sample_rate, silence_db=45.0, min_silence_sec=2.0, fade_sec=0.05)
    assert len(out_fade) == fade_len * 3
    assert out_fade[0] == 0.0


def test_smooth_gain_edge_cases(sample_rate: int) -> None:
    gain_const = np.array([5.0, 5.0, 5.0], dtype=np.float32)
    out_const = smooth_gain(gain_const, sample_rate)
    np.testing.assert_array_equal(out_const, gain_const)

    gain_mono = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    out_mono = smooth_gain(gain_mono, sample_rate)
    assert out_mono[2] > out_mono[1] > out_mono[0]

    gain_single = np.array([5.0], dtype=np.float32)
    out_single = smooth_gain(gain_single, sample_rate)
    assert out_single[0] == 5.0


def test_limiter_edge_cases(sample_rate: int) -> None:
    ceiling_db = -1.0
    ceiling = 10 ** (ceiling_db / 20)

    y_below = np.array([ceiling * 0.5, ceiling * 0.5], dtype=np.float32)
    out_below = limiter(y_below, sample_rate, ceiling_db=ceiling_db)
    np.testing.assert_array_almost_equal(out_below, y_below)

    y_exact = np.array([ceiling, ceiling], dtype=np.float32)
    out_exact = limiter(y_exact, sample_rate, ceiling_db=ceiling_db)
    np.testing.assert_array_almost_equal(out_exact, y_exact)

    y_short = np.array([ceiling * 2.0], dtype=np.float32)
    out_short = limiter(y_short, sample_rate, ceiling_db=ceiling_db)
    assert out_short[0] <= ceiling + 1e-5


def test_export_audio_edge_cases(tmp_path: Path, sample_rate: int) -> None:
    y_mono = generate_sine_wave(duration_sec=0.1, sr=sample_rate)
    y_stereo = np.column_stack((y_mono, y_mono))
    y_clip = y_mono * 5.0

    wav_path = str(tmp_path / "out.wav")
    flac_path = str(tmp_path / "out.flac")
    clip_path = str(tmp_path / "clip.mp3")

    export_audio(y_mono, sample_rate, wav_path, audio_format="wav")
    assert os.path.exists(wav_path)

    export_audio(y_stereo, sample_rate, flac_path, audio_format="flac")
    assert os.path.exists(flac_path)

    export_audio(y_clip, sample_rate, clip_path, audio_format="mp3")
    assert os.path.exists(clip_path)


def test_load_audio_edge_cases(tmp_path: Path, sample_rate: int) -> None:
    y_mono = generate_sine_wave(duration_sec=0.1, sr=sample_rate)
    wav_path = str(tmp_path / "test_edge.wav")
    export_audio(y_mono, sample_rate, wav_path, audio_format="wav")

    arr, sr = load_audio(wav_path)
    assert arr is not None
    assert sr == sample_rate

    bad_path = str(tmp_path / "bad.wav")
    with open(bad_path, "wb") as f:
        f.write(b"not an audio file")
    arr_bad, sr_bad = load_audio(bad_path)
    assert arr_bad is None
    assert sr_bad is None


def test_process_audio_lufs_flows(tmp_path: Path, sample_rate: int) -> None:
    sine = generate_sine_wave(duration_sec=1.0, sr=sample_rate)
    sine_int16 = (sine * 32767).astype(np.int16)
    segment = AudioSegment(sine_int16.tobytes(), frame_rate=sample_rate, sample_width=2, channels=1)

    in_wav = str(tmp_path / "flow.wav")
    out_mp3 = str(tmp_path / "flow_out.mp3")
    segment.export(in_wav, format="wav")

    with patch("src.main._measure_lufs") as mock_measure:
        mock_measure.side_effect = [-14.0, -10.0]
        process_audio((in_wav, out_mp3))
        assert mock_measure.call_count == 2
        assert os.path.exists(out_mp3)

    out_mp3_2 = str(tmp_path / "flow_out2.mp3")
    with patch("src.main._measure_lufs", return_value=None):
        process_audio((in_wav, out_mp3_2))
        assert os.path.exists(out_mp3_2)


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


def test_format_loudness_params_edge_cases() -> None:
    assert format_loudness_params(None, -10.0, None) == "Dry: N/A | EQ: -10.0 LUFS | Pre-Gain: 0.0 dB"
    assert format_loudness_params(-15.0, None, 5.0) == "Dry: -15.0 LUFS | EQ: N/A | Pre-Gain: +5.0 dB"
    assert format_loudness_params(None, None, None) == "Dry: N/A | EQ: N/A | Pre-Gain: 0.0 dB"


def test_measure_lufs_edge_cases(sample_rate: int) -> None:
    short_audio = np.zeros(int(sample_rate * 0.4), dtype=np.float32)
    assert _measure_lufs(short_audio, sample_rate) is None

    with patch("pyloudnorm.Meter.integrated_loudness", return_value=np.nan):
        valid_audio = np.zeros(sample_rate, dtype=np.float32)
        assert _measure_lufs(valid_audio, sample_rate) is None

    with patch("pyloudnorm.Meter.integrated_loudness", side_effect=ValueError):
        valid_audio = np.zeros(sample_rate, dtype=np.float32)
        assert _measure_lufs(valid_audio, sample_rate) is None
