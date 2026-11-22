import contextlib
import logging
import os
import warnings
from typing import Any, TypeAlias, cast

import numpy as np
import pyloudnorm as pyln
from numpy.typing import NDArray
from pydub import AudioSegment
from scipy.signal import lfilter

Float32Array: TypeAlias = NDArray[np.float32]
Float64Array: TypeAlias = NDArray[np.float64]

TARGET_LUFS = -16.0
TRIM_THRESHOLD_DB = 45.0
MAX_PRE_GAIN_DB = 30.0
TRUE_PEAK_CEILING_DB = -1.0


EQ_BANDS: list[tuple[float, float]] = [
    (60.0, 20 * np.log10(1.40)),
    (230.0, 20 * np.log10(1.20)),
    (910.0, 20 * np.log10(0.60)),
    (3600.0, 20 * np.log10(0.90)),
    (14000.0, 20 * np.log10(1.10)),
]
EQ_Q = 1.0

_worker_slot: int | None = None
_progress_queue: Any = None


logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")


def _init_worker(counter: Any, progress_queue: Any = None) -> None:
    global _progress_queue, _worker_slot
    _progress_queue = progress_queue
    with counter.get_lock():
        _worker_slot = counter.value
        counter.value += 1


def _emit(message: tuple[Any, ...]) -> None:
    if _progress_queue is not None:
        with contextlib.suppress(Exception):
            _progress_queue.put(message)


def format_loudness_params(
    lufs_dry: float | None,
    lufs_eq: float | None,
    gain_db: float | None,
) -> str:
    dry_str = f"{lufs_dry:.1f} LUFS" if lufs_dry is not None else "N/A"
    eq_str = f"{lufs_eq:.1f} LUFS" if lufs_eq is not None else "N/A"
    gain_str = f"{gain_db:+.1f} dB" if gain_db is not None else "0.0 dB"
    return f"Dry: {dry_str} | EQ: {eq_str} | Pre-Gain: {gain_str}"


def _peaking_biquad(
    fc: float,
    gain_db: float,
    q: float,
    sr: int,
) -> tuple[Float64Array, Float64Array]:
    a: float = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * fc / sr
    alpha = np.sin(w0) / (2 * q)

    b0 = 1 + alpha * a
    b1 = -2 * np.cos(w0)
    b2 = 1 - alpha * a
    a0 = 1 + alpha / a
    a1 = -2 * np.cos(w0)
    a2 = 1 - alpha / a

    b: Float64Array = np.array([b0 / a0, b1 / a0, b2 / a0], dtype=np.float64)
    a_arr: Float64Array = np.array([1.0, a1 / a0, a2 / a0], dtype=np.float64)

    return b, a_arr


def apply_eq_for_metering(
    mono: Float32Array,
    sr: int,
    bands: list[tuple[float, float]] = EQ_BANDS,
    q: float = EQ_Q,
) -> Float32Array:
    result = mono.astype(np.float64)

    for fc, gain_db in bands:
        if abs(gain_db) < 0.01:
            continue
        if fc >= sr / 2:
            continue
        b, a = _peaking_biquad(fc, gain_db, q, sr)
        result = lfilter(b, a, result)

    return cast("Float32Array", result.astype(np.float32))


def _measure_lufs(mono: Float32Array, sr: int) -> float | None:
    if len(mono) < int(sr * 0.5):
        return None
    meter = pyln.Meter(sr)
    try:
        loudness = meter.integrated_loudness(mono.astype(np.float32))
    except ValueError:
        return None
    return float(loudness) if np.isfinite(loudness) else None


def trim_silence_multi(y: Float32Array, top_db: float) -> Float32Array:
    abs_y = np.max(np.abs(y), axis=1) if y.ndim > 1 else np.abs(y)
    threshold = 10 ** (top_db / -20)
    indices = np.where(abs_y > threshold)[0]

    if len(indices) == 0:
        if y.ndim > 1:
            return cast("Float32Array", np.zeros((0, y.shape[1]), dtype=np.float32))
        return cast("Float32Array", np.zeros((0,), dtype=np.float32))

    return cast("Float32Array", y[indices[0] : indices[-1] + 1].astype(np.float32))


def remove_long_silences_multi(
    y: Float32Array,
    sr: int,
    silence_db: float = 45.0,
    min_silence_sec: float = 2.0,
    fade_sec: float = 0.05,
) -> Float32Array:
    threshold = 10 ** (silence_db / -20)
    min_silence_len = int(sr * min_silence_sec)
    fade_len = int(sr * fade_sec)

    mono_mask = np.max(np.abs(y), axis=1) < threshold
    segments: list[tuple[int, int]] = []
    start = 0
    i = 0

    while i < len(y):
        if mono_mask[i]:
            j = i
            while j < len(y) and mono_mask[j]:
                j += 1
            if j - i >= min_silence_len:
                segments.append((start, i))
                start = j
            i = j
        else:
            i += 1

    segments.append((start, len(y)))

    output: list[Float32Array] = []
    for s, e in segments:
        seg = y[s:e].copy()
        if len(seg) > fade_len * 2:
            fade = np.linspace(0, 1, fade_len, dtype=np.float32)
            seg[:fade_len] *= fade[:, None]
            seg[-fade_len:] *= fade[::-1][:, None]
        output.append(cast("Float32Array", seg.astype(np.float32)))

    if output:
        return cast("Float32Array", np.concatenate(output, axis=0).astype(np.float32))
    if y.ndim > 1:
        return cast("Float32Array", np.zeros((0, y.shape[1]), dtype=np.float32))
    return cast("Float32Array", np.zeros((0,), dtype=np.float32))


def smooth_gain(
    gain_db: Float32Array,
    sr: int,
    attack_sec: float = 0.2,
    release_sec: float = 1.5,
) -> Float32Array:
    attack_coeff = np.exp(-1.0 / (sr * attack_sec))
    release_coeff = np.exp(-1.0 / (sr * release_sec))

    smoothed = np.zeros_like(gain_db, dtype=np.float32)
    smoothed[0] = gain_db[0]

    for i in range(1, len(gain_db)):
        coeff = release_coeff if gain_db[i] > smoothed[i - 1] else attack_coeff
        smoothed[i] = coeff * smoothed[i - 1] + (1 - coeff) * gain_db[i]

    return cast("Float32Array", smoothed.astype(np.float32))


def dynamic_loudness_control(
    y: Float32Array,
    sr: int,
    target_lufs: float,
    window_sec: float = 8.0,
    max_gain_db: float = 5.0,
) -> Float32Array:
    meter = pyln.Meter(sr)
    window_size = max(1, int(sr * window_sec))
    hop = max(1, window_size // 2)

    gains_db_list: list[float] = []
    positions_list: list[int] = []

    for start in range(0, len(y) - window_size, hop):
        segment = y[start : start + window_size]
        try:
            loudness = meter.integrated_loudness(segment)
        except ValueError:
            continue
        gain_db = float(np.clip(target_lufs - loudness, -max_gain_db, max_gain_db))
        gains_db_list.append(gain_db)
        positions_list.append(start + window_size // 2)

    if not gains_db_list:
        return y

    positions = np.array(positions_list, dtype=np.float32)
    gains_db = np.array(gains_db_list, dtype=np.float32)
    full_positions = np.arange(len(y), dtype=np.float32)
    gain_curve_db = np.interp(full_positions, positions, gains_db).astype(np.float32)
    gain_curve_db = smooth_gain(gain_curve_db, sr)
    gain_curve = np.power(10.0, gain_curve_db / 20.0).astype(np.float32)

    return cast("Float32Array", (y * gain_curve[:, None]).astype(np.float32))


def limiter(
    y: Float32Array,
    sr: int,
    ceiling_db: float = -1.0,
    release_ms: float = 50.0,
) -> Float32Array:
    ceiling = 10 ** (ceiling_db / 20)
    gain = 1.0
    release = np.exp(-1.0 / (sr * release_ms / 1000))
    out = np.zeros_like(y, dtype=np.float32)

    for i in range(len(y)):
        peak = np.max(np.abs(y[i])) if y.ndim > 1 else abs(y[i])
        gain = ceiling / (peak + 1e-9) if peak * gain > ceiling else gain + (1.0 - gain) * (1 - release)
        out[i] = y[i] * gain

    return cast("Float32Array", out.astype(np.float32))


def load_audio(path: str) -> tuple[Float32Array | None, int | None]:
    try:
        audio = AudioSegment.from_file(path)
        arr = np.array(audio.get_array_of_samples(), dtype=np.float32)
        channels = int(audio.channels)
        sr = int(audio.frame_rate)
        arr = arr.reshape((-1, channels))
        arr /= float(np.iinfo(audio.array_type).max)
    except Exception:
        return None, None
    return arr, sr


def export_audio(
    y: Float32Array,
    sr: int,
    output_path: str,
    audio_format: str = "mp3",
    bitrate: str = "320k",
) -> None:
    y = np.clip(y, -0.999, 0.999)
    y_int16 = (y * 32767.0).astype(np.int16)
    channels = 1 if y.ndim == 1 else y.shape[1]

    if y.ndim > 1:
        y_int16 = y_int16.flatten()

    segment = AudioSegment(
        y_int16.tobytes(),
        frame_rate=sr,
        sample_width=2,
        channels=channels,
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    export_kwargs = {"bitrate": bitrate} if audio_format.lower() == "mp3" else {}
    segment.export(output_path, format=audio_format.lower(), **export_kwargs)


def process_audio(task: tuple[str, str]) -> None:
    input_path, output_path = task
    worker_id = _worker_slot if _worker_slot is not None else 0
    file_name = os.path.basename(input_path)
    status = "failed"

    def report(step: int, description: str, details: str = "") -> None:
        _emit(("step", worker_id, file_name, step, description, details))

    try:
        if os.path.exists(output_path):
            status = "skipped"
            return

        report(1, "Loading")
        y, sr = load_audio(input_path)
        if y is None or sr is None or len(y) == 0:
            return

        report(2, "Trim Silence")
        y = trim_silence_multi(y, TRIM_THRESHOLD_DB)
        if len(y) == 0:
            status = "skipped"
            return

        report(3, "Remove Silences")
        y = remove_long_silences_multi(y, sr)
        if len(y) == 0:
            status = "skipped"
            return

        report(4, "Metering LUFS")
        mono_dry = y.mean(axis=1).astype(np.float32) if y.ndim > 1 else y.copy()

        mono_eq = apply_eq_for_metering(mono_dry, sr)
        lufs_eq = _measure_lufs(mono_eq, sr)

        lufs_dry = _measure_lufs(mono_dry, sr)

        if lufs_eq is not None and lufs_dry is not None:
            eq_compensation_db = lufs_eq - lufs_dry
            target_for_dry = TARGET_LUFS - eq_compensation_db
        else:
            target_for_dry = TARGET_LUFS

        gain_db: float | None = None
        if lufs_dry is not None:
            gain_db = float(np.clip(target_for_dry - lufs_dry, -MAX_PRE_GAIN_DB, MAX_PRE_GAIN_DB))
            gain_lin = 10 ** (gain_db / 20.0)
            y = (y * gain_lin).astype(np.float32)
            mono_dry = (mono_dry * gain_lin).astype(np.float32)

        details = format_loudness_params(lufs_dry, lufs_eq, gain_db)

        report(5, "Dynamic Loudness", details)
        y = dynamic_loudness_control(y, sr, TARGET_LUFS)

        report(6, "Peak Limiter", details)
        if y.ndim > 1:
            y = np.stack(
                [limiter(y[:, c], sr, TRUE_PEAK_CEILING_DB) for c in range(y.shape[1])],
                axis=1,
            ).astype(np.float32)
        else:
            y = limiter(y, sr, TRUE_PEAK_CEILING_DB)

        report(7, "Exporting Audio", details)
        export_audio(y.astype(np.float32), sr, output_path)
        status = "ok"
    except Exception:
        status = "failed"
    finally:
        _emit(("done", worker_id, file_name, status))
