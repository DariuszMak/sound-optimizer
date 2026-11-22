from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from src.main import NUMBER_OF_STEPS


class WorkerInfoWidget(QWidget):
    def __init__(self, worker_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._id_label = QLabel(f"W{worker_id:02d}")
        self._step_label = QLabel()
        self._desc_label = QLabel()
        self._file_label = QLabel()
        self._details_label = QLabel()
        mono = QFont("Consolas", 9)
        for label in (self._id_label, self._step_label, self._desc_label):
            label.setFont(mono)
        self._details_label.setFont(QFont("Consolas", 8))
        self._details_label.setStyleSheet("color: gray;")
        self._details_label.setWordWrap(True)
        self._id_label.setFixedWidth(36)
        self._step_label.setFixedWidth(36)
        self._desc_label.setMinimumWidth(130)
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        top_row.addWidget(self._id_label)
        top_row.addWidget(self._step_label)
        top_row.addWidget(self._desc_label)
        top_row.addWidget(self._file_label, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(0)
        layout.addLayout(top_row)
        layout.addWidget(self._details_label)

    def set_info(self, file_name: str, step: int, description: str, details: str) -> None:
        self._step_label.setText(f"{step}/{NUMBER_OF_STEPS}")
        self._desc_label.setText(description)
        self._file_label.setText(file_name)
        self._details_label.setText(details)
        self._details_label.setVisible(bool(details))
