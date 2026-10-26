from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from mangosteen.ui import screenfit


def window_with(width, height):
    window = QWidget()
    layout = QVBoxLayout(window)
    content = QLabel("content")
    content.setMinimumSize(width, height)
    layout.addWidget(content)
    window.adjustSize()
    return window, content


def test_a_window_that_fits_is_left_alone(qapp):
    window, content = window_with(200, 150)
    size = window.size()
    assert not screenfit.fit(window)
    assert window.size() == size and content.parent() is window


def test_a_window_too_big_for_the_screen_scrolls(qapp):
    area = screenfit.available_area()
    window, content = window_with(area.width() + 400, area.height() + 300)
    assert screenfit.fit(window)
    assert window.width() <= area.width() and window.height() <= area.height()
    assert isinstance(content.parent().parent().parent(), screenfit.FitScrollArea)
    assert not screenfit.fit(window)  # wrapped once only


def test_a_tool_window_keeps_its_buttons_outside_the_scroll(qapp):
    from mangosteen.ui.tools.base import ToolWindow

    area = screenfit.available_area()
    window = ToolWindow("Tool", [], "Run", None)
    body = QLabel("body")
    body.setMinimumSize(area.width() + 300, area.height() + 300)
    window.set_body(body)
    window.adjustSize()
    assert screenfit.fit(window, wrap=ToolWindow._scroll_body)
    assert window.height() <= area.height()
    scroll = body.parent().parent().parent()
    assert isinstance(scroll, screenfit.FitScrollArea)
    assert not scroll.isAncestorOf(window._action)
