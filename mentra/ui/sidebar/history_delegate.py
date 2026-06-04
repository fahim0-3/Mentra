from PyQt5.QtWidgets import QStyledItemDelegate, QStyle
from PyQt5.QtCore import Qt, QRect, QSize
from PyQt5.QtGui import QColor, QFont, QPainter, QBrush
from datetime import datetime
from mentra.utils.styles import COLOR_TEXT_MAIN, COLOR_TEXT_SUB, COLOR_ACCENT


class ChatItemDelegate(QStyledItemDelegate):
    """Sidebar renderer (Model/View) with themed hover action buttons."""

    def __init__(self, icons, parent=None):
        super().__init__(parent)
        self.icons = icons  # pixmap dict
        self._hover_row = -1
        self._action_hover = None  # 'edit' | 'delete' | None

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 65)

    def _button_rects(self, option):
        """Edit/delete button rectangles — shared by paint() and editorEvent()."""
        bg = option.rect.adjusted(5, 5, -5, -5)
        edit_rect = QRect(bg.right() - 62, bg.top() + 9, 26, 26)
        del_rect = QRect(bg.right() - 31, bg.top() + 9, 26, 26)
        return edit_rect, del_rect

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        bg_rect = option.rect.adjusted(5, 5, -5, -5)
        hovered = bool(option.state & QStyle.State_MouseOver)

        # Row background
        if option.state & QStyle.State_Selected:
            painter.setBrush(QBrush(QColor("#27272a")))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bg_rect, 10, 10)
        elif hovered:
            painter.setBrush(QBrush(QColor("#18181b")))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bg_rect, 10, 10)

        chat = index.data(Qt.UserRole)
        if not chat:
            painter.restore()
            return

        # Title (leave room for the action buttons on hover)
        painter.setFont(QFont("Segoe UI", 11, QFont.Medium))
        painter.setPen(QColor(COLOR_TEXT_MAIN))
        avail_w = bg_rect.width() - 24
        if hovered:
            avail_w -= 70
        elided = painter.fontMetrics().elidedText(chat["title"], Qt.ElideRight, max(0, avail_w))
        painter.drawText(bg_rect.adjusted(12, 8, -10, -30), Qt.AlignLeft | Qt.AlignVCenter, elided)

        # Timestamp
        painter.setFont(QFont("Segoe UI", 9))
        painter.setPen(QColor(COLOR_TEXT_SUB))
        try:
            time_str = datetime.fromisoformat(chat["timestamp"]).strftime("%b %d, %H:%M")
        except Exception:
            time_str = chat.get("timestamp", "")
        painter.drawText(bg_rect.adjusted(12, 30, -10, -5), Qt.AlignLeft | Qt.AlignVCenter, time_str)

        # Themed hover action buttons
        if hovered:
            edit_rect, del_rect = self._button_rects(option)
            row = index.row()
            edit_hot = (self._hover_row == row and self._action_hover == "edit")
            del_hot = (self._hover_row == row and self._action_hover == "delete")

            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(COLOR_ACCENT) if edit_hot else QColor("#3f3f46")))
            painter.drawRoundedRect(edit_rect, 8, 8)
            painter.setBrush(QBrush(QColor("#dc2626") if del_hot else QColor("#3f3f46")))
            painter.drawRoundedRect(del_rect, 8, 8)

            pad = 6
            if "edit" in self.icons:
                painter.drawPixmap(edit_rect.adjusted(pad, pad, -pad, -pad), self.icons["edit"])
            if "delete" in self.icons:
                painter.drawPixmap(del_rect.adjusted(pad, pad, -pad, -pad), self.icons["delete"])

        painter.restore()

    def editorEvent(self, event, model, option, index):
        et = event.type()

        # Hover highlight for the individual buttons
        if et == event.MouseMove:
            edit_rect, del_rect = self._button_rects(option)
            p = event.pos()
            action = "edit" if edit_rect.contains(p) else ("delete" if del_rect.contains(p) else None)
            if action != self._action_hover or self._hover_row != index.row():
                self._action_hover = action
                self._hover_row = index.row()
                view = getattr(self.parent(), "lv", None)
                if view is not None:
                    view.viewport().update()
            return False

        if et == event.MouseButtonRelease:
            edit_rect, del_rect = self._button_rects(option)
            p = event.pos()
            if del_rect.contains(p):
                self.parent().delete_requested.emit(index.row())
                return True
            if edit_rect.contains(p):
                self.parent().rename_requested.emit(index.row())
                return True

        return super().editorEvent(event, model, option, index)
