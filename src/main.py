import logging
import os
import shutil
import sys
import time
import warnings
from multiprocessing import freeze_support
from typing import TYPE_CHECKING, Any, TypeAlias

import numpy as np
from numpy.typing import NDArray
from PySide6.QtWidgets import QApplication
from rich.text import Text

if TYPE_CHECKING:
    from rich.console import Console, ConsoleOptions, RenderResult

Float32Array: TypeAlias = NDArray[np.float32]
Float64Array: TypeAlias = NDArray[np.float64]


SUPPORTED = (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".wma", ".mpc")
INPUT_ROOT = "."
OUTPUT_ROOT = "processed"
EXCLUDED_DIRS = {".venv", "processed", "__pycache__"}

NUMBER_OF_STEPS = 7

FFMPEG_BINARY = "ffmpeg"
ANSI_RED = "\033[91m"
ANSI_RESET = "\033[0m"

logger = logging.getLogger(__name__)


warnings.filterwarnings("ignore")


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
    filled = round(width * fraction)
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        if not check_ffmpeg_installed():
            return

        app = QApplication(sys.argv)
        app.setApplicationName("Sound Optimizer")
        app.setOrganizationName("Sound Optimizer")

        from src.frontend.widgets.main_window import MainWindow

        window = MainWindow()
        window.show()

        sys.exit(app.exec())
    finally:
        logger.info("Main function closed")


if __name__ == "__main__":
    freeze_support()
    main()
