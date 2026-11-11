"""Small reusable widgets."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from paperlite.ui import theme


def label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def divider() -> QFrame:
    f = QFrame()
    f.setObjectName("Divider")
    return f


def button(text: str, kind: str | None = None, icon: str | None = None, icon_color: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if icon:
        col = icon_color or ("#FFFFFF" if kind in ("primary", "accent") else theme.TEXT)
        b.setIcon(theme.icon(icon, col, size=16))
        b.setIconSize(QSize(16, 16))
    b.setCursor(Qt.PointingHandCursor)
    return b


def tool_button(icon_name: str, tip: str, checkable: bool = False, size: int = 20) -> QToolButton:
    b = QToolButton()
    b.setIcon(theme.icon(icon_name, theme.TEXT, theme.ACCENT, size=size))
    b.setIconSize(QSize(size, size))
    b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setAutoRaise(True)
    b.setCursor(Qt.PointingHandCursor)
    return b


class RailButton(QToolButton):
    """Icon-over-label button in the left tool rail."""

    def __init__(self, icon_name: str, text: str, tip: str):
        super().__init__()
        self.setObjectName("RailButton")
        self.setIcon(theme.icon(icon_name, theme.TEXT_MUTED, theme.ACCENT, size=22))
        self.setIconSize(QSize(22, 22))
        self.setText(text)
        self.setToolTip(tip)
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setCheckable(True)
        self.setFixedSize(68, 60)
        self.setCursor(Qt.PointingHandCursor)


class ToolItem(QPushButton):
    """A full-width tool row in a side panel (icon, title)."""

    def __init__(self, icon_name: str, text: str, tip: str = ""):
        super().__init__(f"  {text}")
        self.setObjectName("ToolItem")
        self.setIcon(theme.icon(icon_name, theme.TEXT, theme.ACCENT, size=18))
        self.setIconSize(QSize(18, 18))
        self.setCheckable(True)
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


class Toast(QFrame):
    """Short message that fades out at the bottom of the window."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Toast")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 16, 10)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.text = QLabel()
        lay.addWidget(self.icon)
        lay.addWidget(self.text)
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        self.anim = QPropertyAnimation(self.effect, b"opacity", self)
        self.anim.setDuration(220)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.timer = QTimer(self, singleShot=True)
        self.timer.timeout.connect(self._fade_out)
        self.hide()

    def show_message(self, text: str, kind: str = "info", ms: int = 3200):
        icon_name = {"success": "circle-check", "info": "info", "busy": "clock"}.get(kind, "info")
        col = {"success": "#5BD69B", "busy": "#9CB8FF"}.get(kind, "#C9CCD3")
        self.icon.setPixmap(theme.pixmap(icon_name, col, 18))
        self.text.setText(text)
        self.adjustSize()
        self._place()
        self.raise_()
        self.show()
        self.anim.stop()
        self.anim.setStartValue(self.effect.opacity() if self.isVisible() else 0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()
        if ms:
            self.timer.start(ms)

    def _place(self):
        p = self.parentWidget()
        self.move((p.width() - self.width()) // 2, p.height() - self.height() - 72)

    def _fade_out(self):
        self.anim.stop()
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.finished.connect(self._hide_once)
        self.anim.start()

    def _hide_once(self):
        self.anim.finished.disconnect(self._hide_once)
        if self.effect.opacity() == 0.0:
            self.hide()


class InlineEditor(QLineEdit):
    """Text box placed right on the page. Enter commits, Esc cancels."""

    committed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent: QWidget, text: str, font_px: float, family: str = "Arial", ink: str = "#111111"):
        super().__init__(text, parent)
        f = QFont(family)
        f.setPixelSize(max(9, int(round(font_px))))
        self.setFont(f)
        self.setFrame(False)
        self.setStyleSheet(
            f"QLineEdit{{background:rgba(255,255,255,0.96);color:{ink};border:1.5px solid {theme.ACCENT};"
            f"border-radius:3px;padding:0 3px;selection-background-color:{theme.ACCENT};}}"
        )
        self._done = False
        self.returnPressed.connect(self._commit)
        self.textChanged.connect(self._grow)
        self.selectAll()

    def _grow(self):
        fm = QFontMetrics(self.font())
        need = fm.horizontalAdvance(self.text() + "MM") + 10
        if need > self.width():
            self.resize(need, self.height())

    def _commit(self):
        if not self._done:
            self._done = True
            self.committed.emit(self.text())
            self.deleteLater()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._done = True
            self.cancelled.emit()
            self.deleteLater()
            return
        super().keyPressEvent(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self._commit()


class PageGrid(QListWidget):
    """Thumbnail list whose items can be dragged into a new order."""

    orderChanged = Signal(list)  # new order as list of original page indexes

    def __init__(self, vertical: bool):
        super().__init__()
        self.setViewMode(QListWidget.ListMode)
        self.setFlow(QListWidget.TopToBottom if vertical else QListWidget.LeftToRight)
        self.setWrapping(not vertical)
        self.setResizeMode(QListWidget.Adjust)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setDragDropMode(QListWidget.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSpacing(4 if vertical else 10)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff if vertical else Qt.ScrollBarAsNeeded)

    def dropEvent(self, e):
        before = self.order()
        super().dropEvent(e)
        after = self.order()
        if after != before and sorted(after) == sorted(before):
            self.orderChanged.emit(after)

    def order(self) -> list[int]:
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]

    def selected_rows(self) -> list[int]:
        return sorted(self.row(i) for i in self.selectedItems())


class Spinner(QWidget):
    """Small busy indicator."""

    def __init__(self, parent=None, size=18):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.angle = 0
        self.timer = QTimer(self, interval=30)
        self.timer.timeout.connect(self._tick)

    def start(self):
        self.timer.start()
        self.show()

    def stop(self):
        self.timer.stop()
        self.hide()

    def _tick(self):
        self.angle = (self.angle + 12) % 360
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        from PySide6.QtGui import QPen

        pen = QPen(theme.color(theme.ACCENT), 2.2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        r = self.rect().adjusted(2, 2, -2, -2)
        p.drawArc(r, -self.angle * 16, 270 * 16)
