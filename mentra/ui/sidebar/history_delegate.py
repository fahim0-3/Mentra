from PyQt5.QtWidgets import QStyledItemDelegate, QStyle
from PyQt5.QtCore import Qt, QRect, QSize
from PyQt5.QtGui import QColor, QFont, QPainter, QBrush
from datetime import datetime
from mentra.utils.styles import COLOR_TEXT_MAIN, COLOR_TEXT_SUB

class ChatItemDelegate(QStyledItemDelegate):
    """Refactored sidebar renderer (Model/View) for high performance."""
    def __init__(self, icons, parent=None):
        super().__init__(parent)
        self.icons = icons # pixmap dict
        self._hover_index = -1
        self._action_hover = None # 'edit' | 'delete'

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 65)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Background
        bg_rect = option.rect.adjusted(5, 5, -5, -5)
        if option.state & QStyle.State_Selected:
            painter.setBrush(QBrush(QColor("#27272a")))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bg_rect, 10, 10)
        elif option.state & QStyle.State_MouseOver:
            painter.setBrush(QBrush(QColor("#18181b")))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bg_rect, 10, 10)

        chat = index.data(Qt.UserRole)
        if not chat: return

        # Title
        title_font = QFont("Segoe UI", 11, QFont.Medium)
        painter.setFont(title_font)
        painter.setPen(QColor(COLOR_TEXT_MAIN))
        
        # Title Rect - Adjusted for potential buttons on hover
        avail_w = bg_rect.width() - 20
        if option.state & QStyle.State_MouseOver:
            avail_w -= 60 # space for buttons
        
        elided_title = painter.fontMetrics().elidedText(chat["title"], Qt.ElideRight, avail_w)
        painter.drawText(bg_rect.adjusted(10, 8, -10, -30), Qt.AlignLeft | Qt.AlignVCenter, elided_title)

        # Timestamp
        time_font = QFont("Segoe UI", 9)
        painter.setFont(time_font)
        painter.setPen(QColor(COLOR_TEXT_SUB))
        try:
            dt = datetime.fromisoformat(chat["timestamp"])
            time_str = dt.strftime("%b %d, %H:%M")
        except:
            time_str = chat["timestamp"]
        painter.drawText(bg_rect.adjusted(10, 30, -10, -5), Qt.AlignLeft | Qt.AlignVCenter, time_str)

        # Draw Buttons if hovered
        if option.state & QStyle.State_MouseOver:
            # Edit Button
            edit_rect = QRect(bg_rect.right() - 55, bg_rect.top() + 10, 24, 24)
            # Delete Button
            del_rect = QRect(bg_rect.right() - 25, bg_rect.top() + 10, 24, 24)
            
            painter.drawPixmap(edit_rect, self.icons['edit'])
            painter.drawPixmap(del_rect, self.icons['delete'])

        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == event.MouseButtonRelease:
            bg_rect = option.rect.adjusted(5, 5, -5, -5)
            edit_rect = QRect(bg_rect.right() - 55, bg_rect.top() + 10, 24, 24)
            del_rect = QRect(bg_rect.right() - 25, bg_rect.top() + 10, 24, 24)
            
            p = event.pos()
            if del_rect.contains(p):
                # Trigger delete logic (maybe via signal or directly on model)
                # For this implementation, we delegate to the parent
                self.parent().delete_requested.emit(index.row())
                return True
            if edit_rect.contains(p):
                self.parent().rename_requested.emit(index.row())
                return True
        return super().editorEvent(event, model, option, index)
