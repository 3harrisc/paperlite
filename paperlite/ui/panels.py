"""Welcome screen, tool side-panels, and the Organise Pages view."""

from __future__ import annotations

import os

import pymupdf
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from paperlite.ui import theme
from paperlite.ui.widgets import PageGrid, ToolItem, button, divider, label

# ======================================================================= welcome


class ToolCard(QPushButton):
    def __init__(self, icon_name: str, title: str, text: str, tint: str):
        super().__init__()
        self.setObjectName("ToolCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(134)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 14)
        lay.setSpacing(6)
        badge = QLabel()
        badge.setFixedSize(36, 36)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f"background:{tint};border-radius:9px;")
        badge.setPixmap(theme.pixmap(icon_name, "#FFFFFF", 20))
        lay.addWidget(badge)
        lay.addSpacing(4)
        t = label(title, "CardTitle")
        t.setAttribute(Qt.WA_TransparentForMouseEvents)
        d = label(text, "CardText", wrap=True)
        d.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(t)
        lay.addWidget(d)
        lay.addStretch()


class DropZone(QFrame):
    openClicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("DropZone")
        self.setMinimumHeight(170)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(theme.pixmap("file-text", theme.TEXT_FAINT, 34, 1.5))
        ic.setAlignment(Qt.AlignCenter)
        lay.addWidget(ic)
        t = label("Drop a PDF here to open it", "CardTitle")
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)
        b = button("Choose a file", "primary", "folder-open")
        b.setFixedWidth(160)
        b.clicked.connect(self.openClicked)
        lay.addWidget(b, alignment=Qt.AlignCenter)

    def set_hover(self, on: bool):
        self.setProperty("hover", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class WelcomePage(QScrollArea):
    openClicked = Signal()
    toolChosen = Signal(str)
    recentChosen = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("Welcome")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName("Welcome")
        outer = QHBoxLayout(body)
        outer.setAlignment(Qt.AlignHCenter)
        col = QWidget()
        col.setMaximumWidth(860)
        col.setMinimumWidth(560)
        lay = QVBoxLayout(col)
        lay.setContentsMargins(24, 48, 24, 40)
        lay.setSpacing(0)
        lay.addWidget(label("Welcome to PaperLite", "Hero"))
        lay.addSpacing(6)
        lay.addWidget(label("Open, shrink, sign and tidy up your PDFs.", "HeroSub"))
        lay.addSpacing(26)
        self.drop = DropZone()
        self.drop.openClicked.connect(self.openClicked)
        lay.addWidget(self.drop)
        lay.addSpacing(28)
        lay.addWidget(label("TOOLS", "SectionLabel"))
        lay.addSpacing(10)
        grid = QGridLayout()
        grid.setSpacing(12)
        cards = [
            ("compress", "minimize-2", "Compress PDF", "Make big scans small enough to email.", "#D93A2B"),
            ("fill", "signature", "Fill & Sign", "Fill in forms, add text, sign and initial.", "#7C3AED"),
            ("edit", "scan-text", "Edit PDF", "Change text, even on scanned and handwritten pages.", "#2563EB"),
            ("organise", "layout-grid", "Organise Pages", "Reorder, rotate, delete, extract or split pages.", "#0E9F6E"),
            ("combine", "combine", "Combine Files", "Join several PDFs or images into one PDF.", "#D97706"),
        ]
        for n, (key, ic, title, text, tint) in enumerate(cards):
            c = ToolCard(ic, title, text, tint)
            c.clicked.connect(lambda _=False, k=key: self.toolChosen.emit(k))
            grid.addWidget(c, n // 3, n % 3)
        lay.addLayout(grid)
        lay.addSpacing(28)
        self.recent_title = label("RECENT", "SectionLabel")
        lay.addWidget(self.recent_title)
        lay.addSpacing(6)
        self.recent = QListWidget()
        self.recent.setObjectName("RecentList")
        self.recent.setIconSize(QSize(18, 18))
        self.recent.setCursor(Qt.PointingHandCursor)
        self.recent.itemClicked.connect(lambda it: self.recentChosen.emit(it.data(Qt.UserRole)))
        lay.addWidget(self.recent)
        lay.addStretch()
        outer.addWidget(col)
        self.setWidget(body)

    def set_recent(self, paths: list[str]):
        self.recent.clear()
        ic = theme.icon("file-text", theme.TEXT_MUTED, size=18)
        for p in paths:
            folder = os.path.basename(os.path.dirname(p)) or os.path.dirname(p)
            it = QListWidgetItem(ic, f"{os.path.basename(p)}   ·   {folder}")
            it.setData(Qt.UserRole, p)
            it.setToolTip(p)
            self.recent.addItem(it)
        self.recent.setFixedHeight(min(8, len(paths)) * 38 + 6)
        self.recent_title.setVisible(bool(paths))
        self.recent.setVisible(bool(paths))


# ======================================================================= side panels


class SidePanel(QWidget):
    def __init__(self, title: str, hint: str = ""):
        super().__init__()
        self.setObjectName("SidePanel")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFixedWidth(272)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 18, 16, 16)
        self.lay.setSpacing(4)
        self.lay.addWidget(label(title, "PanelTitle"))
        if hint:
            self.hint = label(hint, "PanelHint", wrap=True)
            self.lay.addSpacing(2)
            self.lay.addWidget(self.hint)
        self.lay.addSpacing(12)

    def section(self, text: str):
        self.lay.addSpacing(10)
        self.lay.addWidget(label(text.upper(), "SectionLabel"))
        self.lay.addSpacing(4)


class ToolPanel(SidePanel):
    """A panel of mutually exclusive tools."""

    toolChosen = Signal(str)

    def __init__(self, title: str, hint: str):
        super().__init__(title, hint)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.items: dict[str, ToolItem] = {}
        self.tip = label("", "PanelHint", wrap=True)

    def add_tool(self, key: str, icon_name: str, text: str, tip: str):
        it = ToolItem(icon_name, text, tip)
        it.clicked.connect(lambda: self._chosen(key))
        self.group.addButton(it)
        self.items[key] = it
        self.lay.addWidget(it)

    def _chosen(self, key):
        self.toolChosen.emit(key)

    def select(self, key: str | None):
        for k, it in self.items.items():
            it.setChecked(k == key)


class SignaturePreview(QFrame):
    changeClicked = Signal()

    def __init__(self, title):
        super().__init__()
        self.setObjectName("SignatureCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        top = QHBoxLayout()
        top.addWidget(label(title, "PanelHint"))
        top.addStretch()
        self.change = button("Change", "ghost")
        self.change.clicked.connect(self.changeClicked)
        top.addWidget(self.change)
        lay.addLayout(top)
        self.img = QLabel("Not created yet")
        self.img.setObjectName("PanelHint")
        self.img.setAlignment(Qt.AlignCenter)
        self.img.setMinimumHeight(46)
        lay.addWidget(self.img)

    def set_png(self, png: bytes | None):
        if png:
            pm = QPixmap()
            pm.loadFromData(png)
            self.img.setPixmap(pm.scaled(200, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.change.setText("Change")
        else:
            self.img.setText("Not created yet")
            self.change.setText("Create")


class FillSignPanel(ToolPanel):
    def __init__(self):
        super().__init__("Fill & Sign", "Pick a tool, then click on the page. Form fields can be clicked in any tool.")
        self.add_tool("view", "mouse-pointer-2", "Fill form fields", "Click blue fields to type in them")
        self.add_tool("text", "type", "Add text", "Click anywhere to type")
        self.add_tool("tick", "check", "Tick", "Click to place a ✓")
        self.add_tool("cross", "x", "Cross", "Click to place an ✗")
        self.add_tool("date", "clock", "Today's date", "Click to place today's date")
        self.section("Signature")
        self.add_tool("sign", "signature", "Sign", "Click where your signature goes")
        self.sig = SignaturePreview("Your signature")
        self.lay.addWidget(self.sig)
        self.lay.addSpacing(6)
        self.add_tool("initials", "pen-line", "Initials", "Click where your initials go")
        self.ini = SignaturePreview("Your initials")
        self.lay.addWidget(self.ini)
        self.lay.addSpacing(10)
        self.lay.addWidget(self.tip)
        self.lay.addStretch()


class EditPanel(ToolPanel):
    def __init__(self):
        super().__init__("Edit PDF", "Works on normal PDFs and on scans — including handwriting.")
        self.add_tool("edit", "text-cursor-input", "Edit text", "Click a word or line to change it. Scanned pages are read automatically.")
        self.add_tool("text", "type", "Add text", "Click anywhere to type new text")
        self.add_tool("area", "square-dashed-mouse-pointer", "Select area", "Drag a box around anything — handwriting, stamps, pictures — then replace, erase, move or copy it")
        self.add_tool("erase", "eraser", "Erase", "Drag over anything to remove it; it's filled with the paper colour")
        self.section("Text style")
        self.font = QComboBox()
        self.font.addItem("Match original", "auto")
        self.font.addItem("Sans serif (Helvetica)", "helv")
        self.font.addItem("Serif (Times)", "tiro")
        self.font.addItem("Monospace (Courier)", "cour")
        self.lay.addWidget(self.font)
        self.lay.addSpacing(14)
        self.status = label("", "PanelHint", wrap=True)
        self.lay.addWidget(self.status)
        self.lay.addWidget(self.tip)
        self.lay.addStretch()


class ThumbsPanel(SidePanel):
    def __init__(self):
        super().__init__("Pages")
        self.lay.setContentsMargins(8, 18, 8, 8)
        self.layout().itemAt(0).widget().setContentsMargins(8, 0, 0, 0)
        self.setFixedWidth(196)
        self.grid = PageGrid(vertical=True)
        self.grid.setObjectName("Thumbs")
        self.grid.setIconSize(QSize(150, 170))
        self.lay.addWidget(self.grid)


# ======================================================================= organise


def thumb_card(page: pymupdf.Page, number: int, box_w: int, box_h: int) -> QPixmap:
    """Page thumbnail with a shadow and its page number, as one picture."""
    scale = 2
    W, H = box_w * scale, (box_h + 22) * scale
    z = min((box_w - 12) / page.rect.width, (box_h - 12) / page.rect.height) * scale
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z))
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
    out = QPixmap(W, H)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    x = (W - img.width()) // 2
    y = (box_h * scale - img.height()) // 2
    p.setPen(Qt.NoPen)
    for i, a in enumerate((26, 14, 7)):
        p.setBrush(QColor(20, 24, 31, a))
        p.drawRoundedRect(x - i - 1, y - i, img.width() + 2 * i + 2, img.height() + 2 * i + 3, 3 + i, 3 + i)
    p.drawImage(x, y, img)
    f = QFont(theme.ui_font_family())
    f.setPixelSize(12 * scale)
    p.setFont(f)
    p.setPen(QColor(theme.TEXT_MUTED))
    p.drawText(0, box_h * scale, W, 22 * scale, Qt.AlignCenter, str(number))
    p.end()
    out.setDevicePixelRatio(scale)
    return out


class OrganiseView(QWidget):
    """Big page grid with a context bar of page tools."""

    action = Signal(str)  # rotate_left, rotate_right, delete, insert_file, insert_blank, extract, export_images, split, done

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("ContextBar")
        bar.setAttribute(Qt.WA_StyledBackground)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 8, 14, 8)
        bl.setSpacing(6)
        title = label("Organise pages", "PanelTitle")
        bl.addWidget(title)
        bl.addSpacing(14)
        self.count = label("", "PanelHint")
        bl.addWidget(self.count)
        bl.addStretch()

        def tb(icon_name, text, key, tip):
            b = QToolButton()
            b.setIcon(theme.icon(icon_name, theme.TEXT, size=18))
            b.setIconSize(QSize(18, 18))
            b.setText(text)
            b.setToolTip(tip)
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setCursor(Qt.PointingHandCursor)
            if key:
                b.clicked.connect(lambda: self.action.emit(key))
            bl.addWidget(b)
            return b

        tb("rotate-ccw", "", "rotate_left", "Rotate left")
        tb("rotate-cw", "", "rotate_right", "Rotate right")
        tb("trash-2", "", "delete", "Delete selected pages (Del)")
        ins = tb("file-plus", "Insert", None, "Insert pages")
        m = QMenu(ins)
        m.addAction(theme.icon("file-plus", theme.TEXT, size=16), "Pages from a file…", lambda: self.action.emit("insert_file"))
        m.addAction(theme.icon("file-plus-2", theme.TEXT, size=16), "Blank page", lambda: self.action.emit("insert_blank"))
        ins.setMenu(m)
        ins.setPopupMode(QToolButton.InstantPopup)
        tb("file-output", "Extract", "extract", "Save the selected pages as a new PDF")
        tb("image-down", "Export images", "export_images", "Save pages as PNG or JPG")
        tb("scissors", "Split", "split", "Split into several PDFs")
        bl.addSpacing(10)
        done = button("Done", "accent")
        done.clicked.connect(lambda: self.action.emit("done"))
        bl.addWidget(done)
        lay.addWidget(bar)

        self.grid = PageGrid(vertical=False)
        self.grid.setObjectName("OrganiseGrid")
        self.grid.setIconSize(QSize(170, 242))
        self.grid.setGridSize(QSize(196, 270))
        self.grid.itemSelectionChanged.connect(self._sel)
        lay.addWidget(self.grid)

    def _sel(self):
        n = len(self.grid.selectedItems())
        total = self.grid.count()
        self.count.setText(f"{n} of {total} pages selected" if n else f"{total} pages · drag to reorder, Ctrl-click to select several")

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.action.emit("delete")
        else:
            super().keyPressEvent(e)
