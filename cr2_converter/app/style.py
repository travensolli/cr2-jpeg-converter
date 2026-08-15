"""Folha de estilo da aplicação.

O estilo usa ``palette(...)`` em vez de cores fixas para acompanhar o tema do
sistema: assim a janela continua legível tanto no modo claro quanto no modo
escuro do Windows 11, sem precisar de dois temas mantidos em paralelo.
"""

from __future__ import annotations

__all__ = ["PRIMARY_BUTTON", "STYLESHEET"]

PRIMARY_BUTTON = "primaryButton"
"""``objectName`` do botão de ação principal (destaque com a cor do sistema)."""

STYLESHEET = """
QGroupBox {
    font-weight: 600;
    border: 1px solid palette(mid);
    border-radius: 6px;
    margin-top: 12px;
    padding: 10px 8px 8px 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
}

QPushButton {
    padding: 5px 14px;
    border: 1px solid palette(mid);
    border-radius: 4px;
    min-height: 20px;
}
QPushButton:hover:enabled {
    border-color: palette(highlight);
}
QPushButton:pressed:enabled {
    background: palette(midlight);
}

QPushButton#primaryButton {
    background: palette(highlight);
    color: palette(highlighted-text);
    border: 1px solid palette(highlight);
    font-weight: 600;
    padding: 6px 22px;
}
QPushButton#primaryButton:disabled {
    background: palette(midlight);
    color: palette(mid);
    border-color: palette(mid);
}

QTableView {
    border: 1px solid palette(mid);
    border-radius: 4px;
    selection-background-color: palette(highlight);
    selection-color: palette(highlighted-text);
}
QTableView::item {
    padding: 2px 4px;
}
QHeaderView::section {
    padding: 4px 6px;
    border: none;
    border-bottom: 1px solid palette(mid);
    background: palette(window);
    font-weight: 600;
}

QLabel#previewImage {
    border: 1px solid palette(mid);
    border-radius: 4px;
    background: palette(base);
    color: palette(mid);
}
QLabel#previewInfo {
    color: palette(text);
}
QLabel#hintLabel {
    color: palette(mid);
}

QProgressBar {
    border: 1px solid palette(mid);
    border-radius: 4px;
    text-align: center;
    min-height: 20px;
}
QProgressBar::chunk {
    background-color: palette(highlight);
    border-radius: 3px;
}

QScrollArea#settingsScroll {
    border: none;
}
"""
