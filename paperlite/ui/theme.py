"""Visual design: colour tokens, typography, Qt stylesheet and icons."""

from __future__ import annotations

import os
import sys
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# ---------------------------------------------------------------- tokens

BRAND = "#D93A2B"          # logo / primary call to action
BRAND_HOVER = "#C23324"
BRAND_SOFT = "#FDECEA"
ACCENT = "#2563EB"         # selection, focus, active tool
ACCENT_SOFT = "#E8EFFD"
TEXT = "#1D2025"
TEXT_MUTED = "#61656E"
TEXT_FAINT = "#8E929A"
BORDER = "#E3E5E9"
BORDER_STRONG = "#CDD0D6"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F6F7F9"
CANVAS = "#E8E9ED"         # behind the pages
HOVER = "#F0F1F4"
SUCCESS = "#1E7F4F"

RADIUS = 8


def resource(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(base, *parts)


def ui_font_family() -> str:
    families = set(QFontDatabase.families())
    for f in ("Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Inter", "Helvetica Neue", "Cantarell", "DejaVu Sans"):
        if f in families:
            return f
    return QFont().defaultFamily()


def app_font() -> QFont:
    f = QFont(ui_font_family())
    f.setPointSizeF(9.5 if sys.platform == "win32" else 10)
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


# ---------------------------------------------------------------- icons


@lru_cache(maxsize=512)
def _svg(name: str) -> str:
    with open(resource("assets", "icons", f"{name}.svg"), encoding="utf-8") as f:
        return f.read()


@lru_cache(maxsize=1024)
def pixmap(name: str, color: str = TEXT, size: int = 20, stroke: float = 1.75) -> QPixmap:
    svg = _svg(name).replace("currentColor", color).replace('stroke-width="2"', f'stroke-width="{stroke}"')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    scale = 3  # crisp on high-DPI screens
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, size * scale, size * scale))
    p.end()
    pm.setDevicePixelRatio(scale)
    return pm


def icon(name: str, color: str = TEXT, active: str | None = None, disabled: str = "#B9BCC3", size: int = 20) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal, QIcon.Off)
    ic.addPixmap(pixmap(name, disabled, size), QIcon.Disabled, QIcon.Off)
    ic.addPixmap(pixmap(name, active or color, size), QIcon.Normal, QIcon.On)
    ic.addPixmap(pixmap(name, active or color, size), QIcon.Active, QIcon.On)
    return ic


def logo_pixmap(size: int = 28) -> QPixmap:
    pm = QPixmap(resource("assets", "icon.png"))
    pm = pm.scaled(size * 3, size * 3, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    pm.setDevicePixelRatio(3)
    return pm


# ---------------------------------------------------------------- stylesheet


def stylesheet() -> str:
    return f"""
* {{ color: {TEXT}; outline: 0; }}
QMainWindow, QDialog {{ background: {SURFACE}; }}
QToolTip {{ background: #24272E; color: #F4F5F7; border: none; padding: 5px 8px; border-radius: 6px; }}

/* ---------- top app bar ---------- */
#AppBar {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
#AppTitle {{ font-weight: 600; font-size: 10.5pt; }}
#DocTitle {{ color: {TEXT}; font-weight: 600; }}
#DocMeta {{ color: {TEXT_FAINT}; }}
#Chip {{ background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: 10px; padding: 1px 8px; color: {TEXT_MUTED}; }}

QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 5px; }}
QToolButton:hover {{ background: {HOVER}; }}
QToolButton:pressed {{ background: #E6E8EC; }}
QToolButton:checked {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QToolButton:disabled {{ color: {TEXT_FAINT}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: 6px; padding: 6px 14px; font-weight: 500; }}
QPushButton:hover {{ background: {HOVER}; }}
QPushButton:pressed {{ background: #E6E8EC; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; border-color: {BORDER}; }}
QPushButton[kind="primary"] {{ background: {BRAND}; border: 1px solid {BRAND}; color: white; }}
QPushButton[kind="primary"]:hover {{ background: {BRAND_HOVER}; border-color: {BRAND_HOVER}; }}
QPushButton[kind="primary"]:disabled {{ background: #EBA59E; border-color: #EBA59E; color: white; }}
QPushButton[kind="accent"] {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: white; }}
QPushButton[kind="accent"]:hover {{ background: #1D4FD8; }}
QPushButton[kind="ghost"] {{ background: transparent; border: none; color: {ACCENT}; padding: 4px 6px; }}
QPushButton[kind="ghost"]:hover {{ background: {ACCENT_SOFT}; }}

/* ---------- left tool rail ---------- */
#ToolRail {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
#RailButton {{ border: none; border-radius: 8px; padding: 6px 2px 5px 2px; color: {TEXT_MUTED}; font-size: 8pt; }}
#RailButton:hover {{ background: {HOVER}; color: {TEXT}; }}
#RailButton:checked {{ background: {ACCENT_SOFT}; color: {ACCENT}; font-weight: 600; }}

/* ---------- side panels ---------- */
#SidePanel {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
#PanelTitle {{ font-size: 11pt; font-weight: 600; }}
#PanelHint {{ color: {TEXT_MUTED}; }}
#SectionLabel {{ color: {TEXT_FAINT}; font-size: 8pt; font-weight: 600; letter-spacing: 0.6px; }}
#ToolItem {{ text-align: left; border: 1px solid transparent; border-radius: 8px; padding: 8px 10px; background: transparent; font-weight: 500; }}
#ToolItem:hover {{ background: {HOVER}; }}
#ToolItem:checked {{ background: {ACCENT_SOFT}; border-color: #C9D8FB; color: {ACCENT}; }}
#SignatureCard {{ background: {SURFACE_ALT}; border: 1px dashed {BORDER_STRONG}; border-radius: 8px; }}
#Divider {{ background: {BORDER}; max-height: 1px; min-height: 1px; }}

/* ---------- canvas ---------- */
#Canvas {{ background: {CANVAS}; border: none; }}
#CanvasInner {{ background: {CANVAS}; }}
#FloatingBar {{ background: rgba(32, 35, 41, 235); border-radius: 10px; }}
#FloatingBar QToolButton {{ color: white; background: transparent; border: none; border-radius: 6px; padding: 4px; }}
#FloatingBar QToolButton:hover {{ background: rgba(255,255,255,0.12); }}
#FloatingBar QLabel {{ color: #E8E9EC; background: transparent; }}
#FloatingBar QLineEdit {{ background: rgba(255,255,255,0.1); color: white; border: none; border-radius: 4px; padding: 2px 4px; }}

/* ---------- thumbnails / organise ---------- */
#Thumbs, #OrganiseGrid {{ background: {SURFACE}; border: none; }}
#OrganiseGrid {{ background: {CANVAS}; }}
#Thumbs::item, #OrganiseGrid::item {{ border-radius: 6px; padding: 6px; color: {TEXT_MUTED}; }}
#Thumbs::item:hover, #OrganiseGrid::item:hover {{ background: {HOVER}; }}
#OrganiseGrid::item:hover {{ background: rgba(255,255,255,0.55); }}
#Thumbs::item:selected, #OrganiseGrid::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT}; border: 2px solid {ACCENT}; }}
#ContextBar {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}

/* ---------- welcome ---------- */
#Welcome {{ background: {SURFACE_ALT}; }}
#Hero {{ font-size: 20pt; font-weight: 650; }}
#HeroSub {{ color: {TEXT_MUTED}; font-size: 10.5pt; }}
#DropZone {{ background: {SURFACE}; border: 1.5px dashed {BORDER_STRONG}; border-radius: 14px; }}
#DropZone[hover="true"] {{ border-color: {ACCENT}; background: {ACCENT_SOFT}; }}
#ToolCard {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; text-align: left; padding: 14px; }}
#ToolCard:hover {{ border-color: {BORDER_STRONG}; background: #FCFCFD; }}
#CardTitle {{ font-weight: 600; font-size: 10.5pt; }}
#CardText {{ color: {TEXT_MUTED}; }}
#RecentList {{ background: transparent; border: none; }}
#RecentList::item {{ padding: 8px 10px; border-radius: 8px; }}
#RecentList::item:hover {{ background: {SURFACE}; }}

/* ---------- banners & toasts ---------- */
#UpdateBanner {{ background: {ACCENT_SOFT}; border-bottom: 1px solid #C9D8FB; }}
#Toast {{ background: #24272E; border-radius: 10px; }}
#Toast QLabel {{ color: #F4F5F7; }}

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QComboBox {{ background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: 6px; padding: 5px 8px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QListWidget {{ border: 1px solid {BORDER}; border-radius: 8px; background: {SURFACE}; }}
QListWidget::item {{ padding: 6px 8px; }}
QListWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QRadioButton, QCheckBox {{ spacing: 8px; }}
QProgressBar {{ background: {SURFACE_ALT}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; top: -1px; }}
QTabBar::tab {{ padding: 7px 16px; border: none; color: {TEXT_MUTED}; }}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; font-weight: 600; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {HOVER}; }}
QMenu::item:disabled {{ color: {TEXT_FAINT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
QMenu::icon {{ padding-left: 8px; }}
QMenuBar {{ background: {SURFACE}; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(0,0,0,0.22); border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(0,0,0,0.35); }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: rgba(0,0,0,0.22); border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: {BORDER}; }}
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; color: {TEXT_MUTED}; }}
"""


def color(hex_: str, alpha: int = 255) -> QColor:
    c = QColor(hex_)
    c.setAlpha(alpha)
    return c
