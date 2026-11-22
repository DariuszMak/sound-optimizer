import logging
import os
import shutil
import sys
import warnings
from multiprocessing import freeze_support
from typing import TypeAlias

import numpy as np
from numpy.typing import NDArray
from PySide6.QtWidgets import QApplication

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
