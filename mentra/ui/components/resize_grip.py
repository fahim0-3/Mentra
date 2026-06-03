from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QRect

class ResizeGrip(QWidget):
    """Invisible widget placed at a window edge / corner for resize."""

    def __init__(self, parent, direction):
        super().__init__(parent)
        self._dir = direction
        self._start_pos = None
        self._start_geo = None
        self.setStyleSheet("background:transparent;")
        cur = {
            "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
            "w": Qt.SizeHorCursor, "e": Qt.SizeHorCursor,
            "nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
            "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor,
        }
        self.setCursor(cur.get(direction, Qt.ArrowCursor))

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._start_pos = ev.globalPos()
            self._start_geo = self.window().geometry()
            ev.accept()

    def mouseMoveEvent(self, ev):
        if self._start_pos is None:
            return
        delta = ev.globalPos() - self._start_pos
        g = QRect(self._start_geo)
        d = self._dir
        if "e" in d:
            g.setRight(g.right() + delta.x())
        if "w" in d:
            g.setLeft(g.left() + delta.x())
        if "s" in d:
            g.setBottom(g.bottom() + delta.y())
        if "n" in d:
            g.setTop(g.top() + delta.y())
        
        # Enforce minimum size
        if g.width() < 400:
            if "w" in d:
                g.setLeft(g.right() - 400)
            else:
                g.setRight(g.left() + 400)
        if g.height() < 300:
            if "n" in d:
                g.setTop(g.bottom() - 300)
            else:
                g.setBottom(g.top() + 300)
                
        self.window().setGeometry(g)
        ev.accept()

    def mouseReleaseEvent(self, ev):
        self._start_pos = None
