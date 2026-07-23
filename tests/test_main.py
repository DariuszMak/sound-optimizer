import os

import numpy as np
import pytest
from pydub import AudioSegment

from src.main import (
    _measure_lufs,
    limiter,
    process_audio,
    remove_long_silences_multi,
    trim_silence_multi,
)

# --- FIXTURES & HELPERS ---


def generate_sine_wave(duration_sec: float = 1.0, sr: int = 44100, freq: float = 440.0, amp: float = 0.5) -> np.ndarray:
    """Generates a simple sine wave for testing."""
    t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
    return (np.sin(2 * np.pi * freq * t) * amp).astype(np.float32)


@pytest.fixture
def sample_rate() -> int:
    return 44100


# --- UNIT TESTS ---


def test_trim_silence_multi(sample_rate: int) -> None:
    """Test that leading and trailing silences are accurately trimmed."""
    silence = np.zeros(sample_rate * 1, dtype=np.float32)  # 1 sec silence
    sine = generate_sine_wave(duration_sec=1.0, sr=sample_rate)  # 1 sec audio

    # 1s silence + 1s audio + 1s silence
    signal = np.concatenate([silence, sine, silence])

    # Assuming threshold is 45.0 dB as used in the script
    trimmed = trim_silence_multi(signal, top_db=45.0)

    # The output length should closely match the 1 second of actual audio
    assert len(trimmed) > 0
    assert len(trimmed) <= sample_rate * 1.01
    assert len(trimmed) >= sample_rate * 0.99


def test_remove_long_silences_multi(sample_rate: int) -> None:
    """Test that silences exceeding the minimum duration are removed."""
    sine1 = generate_sine_wave(duration_sec=1.0, sr=sample_rate)
    silence = np.zeros(int(sample_rate * 2.5), dtype=np.float32)  # 2.5 sec silence
    sine2 = generate_sine_wave(duration_sec=1.0, sr=sample_rate)
    
    # Reshape to a 2D array (samples, channels) as expected by the source code
    signal = np.concatenate([sine1, silence, sine2]).reshape(-1, 1)
    
    processed = remove_long_silences_multi(
        signal, 
        sr=sample_rate, 
        silence_db=45.0, 
        min_silence_sec=2.0
    )
    
    # Total input is 4.5s. Since 2.5s silence > 2.0s limit, it should be removed.
    # Output should be roughly 2s (plus small crossfade leniency).
    assert len(processed) < sample_rate * 2.5
    assert len(processed) >= sample_rate * 2.0

def test_measure_lufs(sample_rate: int) -> None:
    """Test that LUFS metering requires a minimum audio length and returns valid floats."""
    valid_audio = generate_sine_wave(duration_sec=1.0, sr=sample_rate)
    short_audio = generate_sine_wave(duration_sec=0.1, sr=sample_rate)

    lufs_valid = _measure_lufs(valid_audio, sample_rate)
    lufs_invalid = _measure_lufs(short_audio, sample_rate)

    # 0.5s is the minimum length for LUFS calculation in the script
    assert isinstance(lufs_valid, float)
    assert lufs_invalid is None


def test_limiter(sample_rate: int) -> None:
    """Test that the true peak limiter enforces the maximum ceiling."""
    # Generate signal that drastically exceeds standard 0 dBFS (amplitude = 2.0)
    loud_signal = generate_sine_wave(duration_sec=0.5, sr=sample_rate, amp=2.0)
    ceiling_db = -1.0
    ceiling_lin = 10 ** (ceiling_db / 20)

    limited_signal = limiter(loud_signal, sr=sample_rate, ceiling_db=ceiling_db)
    max_peak = float(np.max(np.abs(limited_signal)))

    # Max peak must be equal to or closely below the ceiling linear value
    assert max_peak <= ceiling_lin + 0.05
    assert max_peak > 0.0


# --- INTEGRATION TESTS ---


def test_process_audio_end_to_end(tmp_path: pytest.TempPathFactory, sample_rate: int) -> None:
    """Test the entire audio pipeline by mocking file I/O on disk."""
    # Create valid dummy audio data
    sine = generate_sine_wave(duration_sec=2.0, sr=sample_rate, amp=0.5)
    sine_int16 = (sine * 32767).astype(np.int16)

    segment = AudioSegment(sine_int16.tobytes(), frame_rate=sample_rate, sample_width=2, channels=1)

    # Temporary paths mimicking the actual pipeline requirements
    input_wav = str(tmp_path / "test_input.wav")
    output_mp3 = str(tmp_path / "test_processed.mp3")

    segment.export(input_wav, format="wav")

    # Process task tuple exactly as imap_unordered provides it
    task = (input_wav, output_mp3)
    process_audio(task)

    # Verify the pipeline created an MP3 output and didn't crash
    assert os.path.exists(output_mp3)
    assert os.path.getsize(output_mp3) > 0
