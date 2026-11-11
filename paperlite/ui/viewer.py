"""Continuous-scroll page viewer with hover highlights, area selection and in-page editing."""

from __future__ import annotations

from typing import Callable

import pymupdf
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QMenu, QScrollArea, QToolButton, QVBoxLayout, QWidget

from paperlite.ui import theme
from paperlite.ui.widgets import InlineEditor, tool_button

MARGIN = 10  # room around each page for its shadow

CLICK_TOOLS = {"view", "text", "tick", "cross", "date", "sign", "initials", "edit", "place"}
DRAG_TOOLS = {"area", "erase"}


class PageWidget(QWidget):
    def __init__(self, view: "PageView", index: int):
        super().__init__()
        self.view, self.index = view, index
        self._img: QImage | None = None
        self._key = None
        self.hover: pymupdf.Rect | None = None  # raw page coordinates
        self.drag_start: QPointF | None = None
        self.drag_rect: QRectF | None = None
        self.setMouseTracking(True)
        self.resize_to_zoom()

    # ---- geometry
    @property
    def page(self) -> pymupdf.Page:
        return self.view.doc[self.index]

    def resize_to_zoom(self):
        r = self.page.rect
        z = self.view.zoom
        self.setFixedSize(int(r.width * z) + 2 * MARGIN, int(r.height * z) + 2 * MARGIN)

    def to_raw(self, pos: QPointF) -> pymupdf.Point:
        z = self.view.zoom
        shown = pymupdf.Point((pos.x() - MARGIN) / z, (pos.y() - MARGIN) / z)
        return shown * self.page.derotation_matrix

    def to_widget(self, raw: pymupdf.Rect) -> QRectF:
        r = pymupdf.Rect(raw) * self.page.rotation_matrix
        z = self.view.zoom
        return QRectF(r.x0 * z + MARGIN, r.y0 * z + MARGIN, r.width * z, r.height * z)

    def raw_rect(self, wr: QRectF) -> pymupdf.Rect:
        a = self.to_raw(wr.topLeft())
        b = self.to_raw(wr.bottomRight())
        return pymupdf.Rect(min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y))

    def invalidate(self):
        self._img = None
        self.update()

    # ---- painting
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        page_r = QRectF(MARGIN, MARGIN, self.width() - 2 * MARGIN, self.height() - 2 * MARGIN)
        # soft shadow
        for i, a in enumerate((18, 12, 7, 4)):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 24, 31, a))
            p.drawRoundedRect(page_r.adjusted(-i - 1, -i, i + 1, i + 2), 2 + i, 2 + i)
        p.fillRect(page_r, Qt.white)

        dpr = self.devicePixelRatioF()
        key = (self.view.zoom, dpr, self.view.revision)
        if self._img is None or self._key != key:
            z = self.view.zoom * dpr
            pix = self.page.get_pixmap(matrix=pymupdf.Matrix(z, z), annots=True)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
            img.setDevicePixelRatio(dpr)
            self._img, self._key = img, key
        p.drawImage(QPointF(MARGIN, MARGIN), self._img)

        tool = self.view.tool
        if tool == "view":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(37, 99, 235, 28))
            for w in self.page.widgets() or []:
                p.drawRoundedRect(self.to_widget(w.rect), 2, 2)
        if self.hover is not None:
            r = self.to_widget(self.hover).adjusted(-2, -2, 2, 2)
            p.setPen(QPen(theme.color(theme.ACCENT), 1.5))
            p.setBrush(QColor(37, 99, 235, 22))
            p.drawRoundedRect(r, 3, 3)
        if self.drag_rect is not None:
            red = tool == "erase"
            col = QColor(217, 58, 43) if red else theme.color(theme.ACCENT)
            pen = QPen(col, 1.5, Qt.DashLine)
            p.setPen(pen)
            fill = QColor(col)
            fill.setAlpha(30)
            p.setBrush(fill)
            p.drawRect(self.drag_rect.normalized())
        if tool == "place" and self.view.place_size and self.underMouse():
            pos = self.mapFromGlobal(QCursor.pos())
            w, h = self.view.place_size
            z = self.view.zoom
            p.setPen(QPen(theme.color(theme.ACCENT), 1.5, Qt.DashLine))
            p.setBrush(QColor(37, 99, 235, 25))
            p.drawRect(QRectF(pos.x(), pos.y(), w * z, h * z))

    # ---- mouse
    def mouseMoveEvent(self, e):
        tool = self.view.tool
        if self.drag_start is not None:
            self.drag_rect = QRectF(self.drag_start, e.position()).normalized()
            self.update()
            return
        if tool in DRAG_TOOLS:
            self.setCursor(Qt.CrossCursor)
        elif tool in ("text", "tick", "cross", "date", "sign", "initials", "place"):
            self.setCursor(Qt.CrossCursor)
            if tool == "place":
                self.update()
        else:
            hover = self.view.hover_provider(self.index, self.to_raw(e.position())) if self.view.hover_provider else None
            if hover != self.hover:
                self.hover = hover
                self.update()
            self.setCursor(Qt.PointingHandCursor if hover is not None else (Qt.IBeamCursor if tool == "edit" else Qt.ArrowCursor))

    def leaveEvent(self, _):
        if self.hover is not None:
            self.hover = None
            self.update()
        if self.view.tool == "place":
            self.update()

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self.view.tool in DRAG_TOOLS:
            self.drag_start = e.position()
            self.drag_rect = QRectF(self.drag_start, self.drag_start)
        else:
            self.view.pageClicked.emit(self.index, self.to_raw(e.position()))

    def mouseReleaseEvent(self, e):
        if self.drag_start is None:
            return
        rect = QRectF(self.drag_start, e.position()).normalized()
        self.drag_start = None
        if rect.width() > 4 and rect.height() > 4:
            self.view.areaSelected.emit(self.index, self.raw_rect(rect), e.globalPosition().toPoint())
        self.drag_rect = None
        self.update()


class FloatingBar(QWidget):
    """Dark pill at the bottom of the canvas: page number and zoom."""

    def __init__(self, view: "PageView"):
        super().__init__(view)
        self.view = view
        self.setObjectName("FloatingBar")
        self.setAttribute(Qt.WA_StyledBackground)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(4)
        self.prev = self._btn("chevron-left", "Previous page", lambda: view.go_to(view.current_page() - 1))
        self.page_edit = QLineEdit()
        self.page_edit.setFixedWidth(36)
        self.page_edit.setAlignment(Qt.AlignCenter)
        self.page_edit.returnPressed.connect(self._jump)
        self.total = QLabel()
        self.next = self._btn("chevron-right", "Next page", lambda: view.go_to(view.current_page() + 1))
        sep = QWidget()
        sep.setFixedSize(1, 18)
        sep.setStyleSheet("background:rgba(255,255,255,0.18)")
        self.zout = self._btn("zoom-out", "Zoom out (Ctrl -)", lambda: view.set_zoom(view.zoom / 1.2))
        self.zlabel = QToolButton()
        self.zlabel.setText("100%")
        self.zlabel.setFixedWidth(52)
        self.zlabel.setCursor(Qt.PointingHandCursor)
        self.zlabel.setToolTip("Zoom presets")
        self.zlabel.clicked.connect(self._zoom_menu)
        self.zin = self._btn("zoom-in", "Zoom in (Ctrl +)", lambda: view.set_zoom(view.zoom * 1.2))
        self.fit = self._btn("move-horizontal", "Fit width (Ctrl 0)", view.fit_width)
        for w in (self.prev, self.page_edit, self.total, self.next, sep, self.zout, self.zlabel, self.zin, self.fit):
            lay.addWidget(w)

    def _btn(self, name, tip, slot):
        b = QToolButton()
        b.setIcon(theme.icon(name, "#FFFFFF", size=18))
        b.setIconSize(QSize(18, 18))
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def _jump(self):
        try:
            self.view.go_to(int(self.page_edit.text()) - 1)
        except ValueError:
            pass
        self.page_edit.clearFocus()

    def _zoom_menu(self):
        m = QMenu(self)
        m.addAction("Fit width", self.view.fit_width)
        m.addAction("Fit page", self.view.fit_page)
        m.addSeparator()
        for z in (50, 75, 100, 125, 150, 200, 300):
            m.addAction(f"{z}%", lambda z=z: self.view.set_zoom(z / 100))
        m.exec(self.zlabel.mapToGlobal(QPoint(0, -m.sizeHint().height() - 4)))

    def refresh(self):
        doc = self.view.doc
        n = doc.page_count if doc else 0
        if not self.page_edit.hasFocus():
            self.page_edit.setText(str(self.view.current_page() + 1 if n else 0))
        self.total.setText(f"/ {n}")
        self.zlabel.setText(f"{round(self.view.zoom * 100)}%")
        self.adjustSize()


class PageView(QScrollArea):
    pageChanged = Signal(int)
    pageClicked = Signal(int, object)  # page index, pymupdf.Point (raw page coords)
    areaSelected = Signal(int, object, QPoint)  # page index, pymupdf.Rect (raw), global pos
    zoomChanged = Signal(float)

    def __init__(self):
        super().__init__()
        self.setObjectName("Canvas")
        self.doc: pymupdf.Document | None = None
        self.zoom = 1.0
        self.tool = "view"
        self.revision = 0
        self.pages: list[PageWidget] = []
        self.hover_provider: Callable | None = None
        self.place_size: tuple[float, float] | None = None
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignHCenter)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.bar = FloatingBar(self)
        self.bar.hide()

    def set_document(self, doc, keep_page: int | None = None):
        self.doc = doc
        self.revision += 1
        container = QWidget()
        container.setObjectName("CanvasInner")
        lay = QVBoxLayout(container)
        lay.setSpacing(6)
        lay.setContentsMargins(24, 18, 24, 80)
        lay.setAlignment(Qt.AlignHCenter)
        self.pages = []
        if doc:
            for i in range(doc.page_count):
                w = PageWidget(self, i)
                self.pages.append(w)
                lay.addWidget(w, alignment=Qt.AlignHCenter)
        self.setWidget(container)
        self.bar.setVisible(bool(doc))
        self._place_bar()
        if keep_page is not None:
            QTimer.singleShot(0, lambda: self.go_to(keep_page))

    def set_tool(self, tool: str):
        self.tool = tool
        for w in self.pages:
            w.hover = None
            w.update()

    def refresh(self, index: int | None = None):
        self.revision += 1
        for w in self.pages if index is None else [self.pages[index]]:
            w.resize_to_zoom()
            w.invalidate()

    def set_zoom(self, z: float):
        if not self.doc:
            return
        for ed in self.findChildren(InlineEditor):
            ed.clearFocus()
        cur = self.current_page()
        self.zoom = max(0.2, min(6.0, z))
        for w in self.pages:
            w.resize_to_zoom()
        self.bar.refresh()
        self.zoomChanged.emit(self.zoom)
        QTimer.singleShot(0, lambda: self.go_to(cur))

    def fit_width(self):
        if self.doc and self.doc.page_count:
            r = self.doc[self.current_page()].rect
            self.set_zoom((self.viewport().width() - 48 - 2 * MARGIN - 14) / r.width)

    def fit_page(self):
        if self.doc and self.doc.page_count:
            r = self.doc[self.current_page()].rect
            self.set_zoom(min((self.viewport().width() - 80) / r.width, (self.viewport().height() - 40) / r.height))

    def current_page(self) -> int:
        y = self.verticalScrollBar().value() + self.viewport().height() // 3
        for w in self.pages:
            if w.y() + w.height() >= y:
                return w.index
        return max(0, len(self.pages) - 1)

    def go_to(self, i: int):
        if 0 <= i < len(self.pages):
            self.verticalScrollBar().setValue(self.pages[i].y() - 8)
            self.bar.refresh()

    def _scrolled(self):
        if self.pages:
            self.bar.refresh()
            self.pageChanged.emit(self.current_page())

    def _place_bar(self):
        self.bar.refresh()
        vp = self.viewport().geometry()
        self.bar.move(vp.x() + (vp.width() - self.bar.width()) // 2, vp.bottom() - self.bar.height() - 18)
        self.bar.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_bar()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.set_zoom(self.zoom * (1.1 if e.angleDelta().y() > 0 else 1 / 1.1))
        else:
            super().wheelEvent(e)

    # ---- in-page text editing
    def open_editor(self, index: int, raw_rect: pymupdf.Rect, text: str, font_pt: float,
                    on_commit: Callable[[str], None], family: str = "Arial", ink: str = "#111111"):
        w = self.pages[index]
        r = w.to_widget(raw_rect)
        font_px = font_pt * self.zoom
        ed = InlineEditor(w, text, font_px, family, ink)
        h = max(r.height(), font_px * 1.45) + 4
        ed.setGeometry(QRect(int(r.x()) - 4, int(r.center().y() - h / 2), max(int(r.width()) + 40, 140), int(h)))
        ed.committed.connect(on_commit)
        ed.show()
        ed.setFocus()
        ed._grow()
        return ed
