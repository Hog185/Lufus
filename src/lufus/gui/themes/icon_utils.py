from pathlib import Path
from PyQt6.QtCore import Qt, QByteArray
from PyQt6.QtGui import QIcon, QPixmap, QPainter
from PyQt6.QtSvg import QSvgRenderer


def svg_icon(svg_path: Path | str, color: str, size: int = 24) -> QIcon:
    with open(svg_path, "r") as f:
        svg_data = f.read()

    svg_data = svg_data.replace("currentColor", color)

    renderer = QSvgRenderer(QByteArray(svg_data.encode()))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()

    return QIcon(pixmap)
