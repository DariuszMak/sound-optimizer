import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from pydub import AudioSegment

from src.main import (
    _measure_lufs,
    _peaking_biquad,
    apply_eq_for_metering,
    collect_audio_files,
    dynamic_loudness_control,
    export_audio,
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

    # Test edge case branches (gain < 0.01, fc >= sr/2)
    bands = [
        (1000.0, 0.0),       # Skipped due to 0 gain
        (24000.0, 5.0),      # Skipped due to nyquist limit
        (1000.0, 5.0),       # Processed
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

    # Test completely silent arrays
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

    # Test completely silent arrays (longer than threshold)
    empty_1d = remove_long_silences_multi(np.zeros(sample_rate * 3, dtype=np.float32), sample_rate)
    assert len(empty_1d) == 0

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
    sine = generate_sine_wave(duration_sec=9.0, sr=sample_rate)
    out = dynamic_loudness_control(sine, sample_rate, target_lufs=-16.0, window_sec=8.0)
    
    assert out.shape == sine.shape
    assert out.dtype == np.float32

    # Test with audio too short for dynamic processing
    short_sine = generate_sine_wave(duration_sec=1.0, sr=sample_rate)
    out_short = dynamic_loudness_control(short_sine, sample_rate, target_lufs=-16.0, window_sec=8.0)
    np.testing.assert_array_equal(out_short, short_sine)

    # Test with pure silence which raises ValueError in pyln meter
    silence = np.zeros(sample_rate * 9, dtype=np.float32)
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

    # Test multichannel limiter
    loud_2d = np.column_stack((loud_signal, loud_signal))
    limited_2d = limiter(loud_2d, sr=sample_rate, ceiling_db=ceiling_db)
    
    assert limited_2d.shape == loud_2d.shape
    max_peak_2d = float(np.max(np.abs(limited_2d)))
    assert max_peak_2d <= ceiling_lin + 0.05


def test_load_and_export_audio(tmp_path: "Path", sample_rate: int) -> None:
    """Test audio I/O mechanisms."""
    sine = generate_sine_wave(duration_sec=0.5, sr=sample_rate)
    sine_2d = np.column_stack((sine, sine))
    
    out_path = str(tmp_path / "test_out.mp3")
    
    # Test export (multi-channel)
    export_audio(sine_2d, sample_rate, out_path, audio_format="mp3")
    assert os.path.exists(out_path)
    
    # Test load valid
    loaded, sr = load_audio(out_path)
    assert loaded is not None
    assert sr is not None
    assert loaded.ndim == 2
    
    # Test load invalid path
    invalid_path = str(tmp_path / "does_not_exist.mp3")
    loaded_inv, sr_inv = load_audio(invalid_path)
    assert loaded_inv is None
    assert sr_inv is None


def test_process_audio_end_to_end(tmp_path: "Path", sample_rate: int) -> None:
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


def test_process_audio_edge_cases(tmp_path: "Path", sample_rate: int) -> None:
    """Test early returns and multichannel handling in process_audio."""
    # 1. Output file already exists
    out_existing = str(tmp_path / "exists.mp3")
    with open(out_existing, "w") as f:
        f.write("dummy")
    process_audio(("nonexistent.wav", out_existing)) 

    # 2. Input file invalid
    process_audio(("invalid.wav", str(tmp_path / "out_invalid.mp3")))

    # 3. Trim silence yields empty array
    silence = np.zeros(sample_rate * 2, dtype=np.float32)
    segment_sil = AudioSegment((silence * 32767).astype(np.int16).tobytes(), frame_rate=sample_rate, sample_width=2, channels=1)
    silence_in = str(tmp_path / "silence.wav")
    silence_out = str(tmp_path / "silence_out.mp3")
    segment_sil.export(silence_in, format="wav")
    
    process_audio((silence_in, silence_out))
    assert not os.path.exists(silence_out)

    # 4. Multichannel processing test
    sine = generate_sine_wave(duration_sec=3.0, sr=sample_rate)
    sine_2d = np.column_stack((sine, sine))
    segment_multi = AudioSegment((sine_2d * 32767).astype(np.int16).tobytes(), frame_rate=sample_rate, sample_width=2, channels=2)
    multi_in = str(tmp_path / "multi.wav")
    multi_out = str(tmp_path / "multi_out.mp3")
    segment_multi.export(multi_in, format="wav")
    
    process_audio((multi_in, multi_out))
    assert os.path.exists(multi_out)


def test_collect_audio_files(tmp_path: "Path", monkeypatch: pytest.MonkeyPatch) -> None:
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
    # Test exit on empty tasks
    with patch("src.main.collect_audio_files", return_value=[]):
        main() 

    # Test processing loop with mocked tasks
    tasks = [("in.wav", "out.mp3")]
    with patch("src.main.collect_audio_files", return_value=tasks), \
         patch("src.main.Pool") as mock_pool, \
         patch("src.main.tqdm") as mock_tqdm:
        
        mock_pool_instance = MagicMock()
        mock_pool.return_value.__enter__.return_value = mock_pool_instance
        mock_pool_instance.imap_unordered.return_value = iter([None])
        
        main()
        
        mock_pool_instance.imap_unordered.assert_called_once()