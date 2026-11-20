from __future__ import annotations

import numpy as np
import pytest


def generate_sine_wave(duration_sec: float = 1.0, sr: int = 44100, freq: float = 440.0, amp: float = 0.5) -> np.ndarray:
    t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
    return (np.sin(2 * np.pi * freq * t) * amp).astype(np.float32)


@pytest.fixture
def sample_rate() -> int:
    return 44100
