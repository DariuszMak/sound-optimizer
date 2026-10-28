import contextlib
import logging
import os
import shutil
import sys
import time
import warnings
from multiprocessing import Pool, Queue, Value, cpu_count, freeze_support
from queue import Empty
from typing import Any, TypeAlias, cast

import numpy as np
import pyloudnorm as pyln
from numpy.typing import NDArray
from pydub import AudioSegment
from rich.console import Console, ConsoleOptions, RenderResult
from rich.live import Live
from rich.text import Text
from scipy.signal import lfilter

Float32Array: TypeAlias = NDArray[np.float32]
Float64Array: TypeAlias = NDArray[np.float64]

TARGET_LUFS = -16.0
TRIM_THRESHOLD_DB = 45.0
MAX_PRE_GAIN_DB = 30.0
TRUE_PEAK_CEILING_DB = -1.0

SUPPORTED = (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".wma", ".mpc")
INPUT_ROOT = "."
OUTPUT_ROOT = "processed"
EXCLUDED_DIRS = {".venv", "processed", "__pycache__"}

NUMBER_OF_STEPS = 7

FFMPEG_BINARY = "ffmpeg"
ANSI_RED = "\033[91m"
ANSI_RESET = "\033[0m"

logger = logging.getLogger(__name__)

EQ_BANDS: list[tuple[float, float]] = [
    (60.0, 20 * np.log10(1.40)),
    (230.0, 20 * np.log10(1.20)),
    (910.0, 20 * np.log10(0.60)),
    (3600.0, 20 * np.log10(0.90)),
    (14000.0, 20 * np.log10(1.10)),
]
EQ_Q = 1.0

warnings.filterwarnings("ignore")

_worker_slot: int | None = None
_progress_queue: Any = None


def _init_worker(counter: Any, progress_queue: Any = None) -> None:
    global _worker_slot, _progress_queue
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


def check_ffmpeg_installed() -> bool:
    if shutil.which(FFMPEG_BINARY) is None:
        logger.error(
            "%sERROR: ffmpeg was not found on your system PATH. "
            "Please install ffmpeg (https://ffmpeg.org/download.html) and "
            "ensure it is available on PATH before running this script.%s",
            ANSI_RED,
            ANSI_RESET,
        )
        return False
    return True


def wait_for_keypress() -> None:
    if not sys.stdin.isatty():
        return

    logger.info("Press any key to continue...")

    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.getch()
        else:
            import termios
            import tty

            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)  # type: ignore[attr-defined]
            try:
                tty.setraw(fd)  # type: ignore[attr-defined]
                sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)  # type: ignore[attr-defined]
    except Exception:
        with contextlib.suppress(Exception):
            input()


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


def collect_audio_files() -> list[tuple[str, str]]:
    tasks: list[tuple[str, str]] = []
    for root, dirs, files in os.walk(INPUT_ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for file in files:
            if file.lower().endswith(SUPPORTED):
                input_path = os.path.join(root, file)
                relative_path = os.path.relpath(input_path, INPUT_ROOT)
                relative_base = os.path.splitext(relative_path)[0]
                output_path = os.path.join(OUTPUT_ROOT, relative_base + "_processed.mp3")
                tasks.append((input_path, output_path))
    return tasks


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _bar(fraction: float, width: int) -> str:
    fraction = min(1.0, max(0.0, fraction))
    filled = int(round(width * fraction))
    return "█" * filled + "░" * (width - filled)


class Dashboard:
    def __init__(self, total: int) -> None:
        self.total = total
        self.done = 0
        self.ok = 0
        self.skipped = 0
        self.failed = 0
        self.workers: dict[int, tuple[str, int, str, str]] = {}
        self.started = time.monotonic()

    def apply(self, message: tuple[Any, ...]) -> None:
        kind = message[0]
        if kind == "step":
            _, worker_id, file_name, step, description, details = message
            self.workers[worker_id] = (file_name, step, description, details)
        elif kind == "done":
            _, worker_id, _file_name, status = message
            self.workers.pop(worker_id, None)
            self.done += 1
            if status == "ok":
                self.ok += 1
            elif status == "skipped":
                self.skipped += 1
            else:
                self.failed += 1

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        width = max(20, options.max_width)
        height = max(3, console.size.height)

        elapsed = time.monotonic() - self.started
        fraction = self.done / self.total if self.total else 1.0
        eta = (elapsed / self.done) * (self.total - self.done) if self.done else 0.0
        bar_width = 20 if width >= 70 else 10 if width >= 40 else 0

        header = Text(no_wrap=True, overflow="ellipsis")
        header.append(f"{fraction * 100:3.0f}% ", style="bold")
        if bar_width:
            header.append(_bar(fraction, bar_width) + " ", style="cyan")
        header.append(f"{self.done}/{self.total} ")
        header.append(f"ok:{self.ok} ", style="green")
        header.append(f"skip:{self.skipped} ", style="yellow")
        header.append(f"fail:{self.failed} ", style="red")
        header.append(f"{_format_duration(elapsed)}", style="dim")
        if self.done and self.done < self.total:
            header.append(f" ETA {_format_duration(eta)}", style="dim")
        yield header

        available = max(1, height - 3)
        items = sorted(self.workers.items())
        if len(items) > available:
            shown = items[: max(1, available - 1)]
            hidden = len(items) - len(shown)
        else:
            shown = items
            hidden = 0

        for worker_id, (file_name, step, description, details) in shown:
            row = Text(no_wrap=True, overflow="ellipsis")
            row.append(f"W{worker_id:02d} ", style="bold")
            row.append(f"{step}/{NUMBER_OF_STEPS} ", style="cyan")
            if width >= 50:
                row.append(f"{description:<16} ")
            row.append(file_name, style="white")
            if details and width >= 110:
                row.append(f"  {details}", style="dim")
            yield row

        if hidden:
            yield Text(f"+{hidden} more workers", style="dim", no_wrap=True)


def run_pool(tasks: list[tuple[str, str]]) -> Dashboard:
    workers = max(1, cpu_count() - 1)
    slot_counter = Value("i", 0)
    progress_queue: Any = Queue()
    dashboard = Dashboard(len(tasks))
    console = Console()

    with Pool(workers, initializer=_init_worker, initargs=(slot_counter, progress_queue)) as pool:
        results = [pool.apply_async(process_audio, (task,)) for task in tasks]
        with Live(
            dashboard,
            console=console,
            refresh_per_second=10,
            vertical_overflow="crop",
            transient=False,
        ):
            while dashboard.done < dashboard.total:
                try:
                    dashboard.apply(progress_queue.get(timeout=0.1))
                    while True:
                        dashboard.apply(progress_queue.get_nowait())
                except Empty:
                    if all(r.ready() for r in results):
                        break

    return dashboard


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        if not check_ffmpeg_installed():
            return

        tasks = collect_audio_files()
        if not tasks:
            return

        dashboard = run_pool(tasks)

        logger.info(
            "Processing done. OK: %d | Skipped: %d | Failed: %d",
            dashboard.ok,
            dashboard.skipped,
            dashboard.failed,
        )
    finally:
        wait_for_keypress()


if __name__ == "__main__":
    freeze_support()
    main()
