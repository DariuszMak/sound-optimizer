from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtWidgets import QWidget

from src.frontend.widgets.worker_info_widget import WorkerInfoWidget
from src.main import NUMBER_OF_STEPS

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


@pytest.fixture
def widget(qtbot: QtBot) -> WorkerInfoWidget:
    w = WorkerInfoWidget(worker_id=1)
    qtbot.addWidget(w)
    return w


def test_widget_creates_with_defaults(qtbot: QtBot) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)

    w = WorkerInfoWidget(worker_id=3, parent=parent)
    qtbot.addWidget(w)

    assert w.parentWidget() is parent
    assert w.isVisible() is False
    assert w._id_label.text() == "W03"
    assert w._step_label.text() == ""
    assert w._desc_label.text() == ""
    assert w._file_label.text() == ""
    assert w._details_label.text() == ""
    assert w._details_label.isHidden() is False


def test_set_info_with_details_shows_details_label(qtbot: QtBot, widget: WorkerInfoWidget) -> None:
    widget.show()
    qtbot.waitExposed(widget)

    widget.set_info(
        file_name="example.txt",
        step=2,
        description="Parsing file",
        details="Line 42: unexpected token",
    )

    assert widget._step_label.text() == f"2/{NUMBER_OF_STEPS}"
    assert widget._desc_label.text() == "Parsing file"
    assert widget._file_label.text() == "example.txt"
    assert widget._details_label.text() == "Line 42: unexpected token"
    assert widget._details_label.isVisible() is True


def test_set_info_without_details_hides_details_label(qtbot: QtBot, widget: WorkerInfoWidget) -> None:
    widget.show()
    qtbot.waitExposed(widget)

    # First show details so we verify toggling back to empty hides it
    widget.set_info(
        file_name="first.txt",
        step=1,
        description="Step one",
        details="Some detail",
    )
    assert widget._details_label.isVisible() is True

    widget.set_info(
        file_name="second.txt",
        step=3,
        description="Step three",
        details="",
    )

    assert widget._step_label.text() == f"3/{NUMBER_OF_STEPS}"
    assert widget._desc_label.text() == "Step three"
    assert widget._file_label.text() == "second.txt"
    assert widget._details_label.text() == ""
    assert widget._details_label.isVisible() is False
