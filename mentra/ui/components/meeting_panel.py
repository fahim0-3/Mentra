from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QScrollArea, QSizePolicy,
)
from PyQt5.QtCore import (
    Qt, pyqtSignal as Signal, QTimer, QPropertyAnimation,
    QEasingCurve,
)
from PyQt5.QtGui import QColor, QPainter, QBrush

from mentra.utils.styles import (
    COLOR_TEXT_MAIN, COLOR_TEXT_SUB, COLOR_ACCENT, COLOR_MEETING_OFF,
    COLOR_MEETING_LISTENING, COLOR_MEETING_THINKING, STYLE_SCROLLBAR,
)


class PulsingDot(QWidget):
    """Animated status indicator dot."""

    def __init__(self, color="#71717a", size=10, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._base_color = QColor(color)
        self._size = size
        self._opacity = 1.0
        self._pulsing = False
        self.setFixedSize(size + 6, size + 6)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(50)
        self._pulse_timer.timeout.connect(self._pulse_tick)
        self._pulse_dir = -1
        self._pulse_min = 0.35

    def set_color(self, color: str):
        self._color = QColor(color)
        self._base_color = QColor(color)
        self.update()

    def set_pulsing(self, enabled: bool):
        self._pulsing = enabled
        if enabled:
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
            self._opacity = 1.0
            self.update()

    def _pulse_tick(self):
        self._opacity += self._pulse_dir * 0.04
        if self._opacity <= self._pulse_min:
            self._opacity = self._pulse_min
            self._pulse_dir = 1
        elif self._opacity >= 1.0:
            self._opacity = 1.0
            self._pulse_dir = -1
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(self._color)
        color.setAlphaF(self._opacity)
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.NoPen)
        x = (self.width() - self._size) // 2
        y = (self.height() - self._size) // 2
        painter.drawEllipse(x, y, self._size, self._size)
        painter.end()


class MeetingPanel(QFrame):
    """Collapsible panel displaying meeting assistant state."""

    toggle_requested = Signal()

    COLLAPSED_HEIGHT = 42
    EXPANDED_HEIGHT = 560

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("meetingPanel")
        self._expanded = False
        self._state = "OFF"  # OFF, LISTENING, THINKING

        self.setStyleSheet(
            f"#meetingPanel {{"
            f"  background: #111113;"
            f"  border: 1px solid #27272a;"
            f"  border-radius: 12px;"
            f"}}"
        )
        self.setMaximumHeight(self.COLLAPSED_HEIGHT)

        self._build_ui()

    def _build_ui(self):
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        # ── Header bar ──
        self._header = QWidget()
        self._header.setFixedHeight(self.COLLAPSED_HEIGHT)
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.setStyleSheet("background: transparent;")
        self._header.mousePressEvent = lambda e: self._toggle_expand()

        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(14, 0, 14, 0)
        hl.setSpacing(8)

        # Status dot
        self._dot = PulsingDot(COLOR_MEETING_OFF, 8)
        hl.addWidget(self._dot)

        # Title
        self._title_label = QLabel("Meeting Assistant")
        self._title_label.setStyleSheet(
            f"color: {COLOR_TEXT_MAIN}; font-size: 13px; font-weight: 600; "
            f"font-family: 'Segoe UI'; background: transparent;"
        )
        hl.addWidget(self._title_label)

        # Status text
        self._status_label = QLabel("OFF")
        self._status_label.setStyleSheet(
            f"color: {COLOR_MEETING_OFF}; font-size: 11px; font-weight: 500; "
            f"font-family: 'Segoe UI'; background: transparent;"
        )
        hl.addWidget(self._status_label)

        hl.addStretch()

        # Toggle button
        self._toggle_btn = QPushButton("Start")
        self._toggle_btn.setFixedSize(64, 26)
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLOR_ACCENT}; color: white; border: none;"
            f"  border-radius: 13px; font-size: 12px; font-weight: 600;"
            f"  font-family: 'Segoe UI';"
            f"}}"
            f"QPushButton:hover {{ background: #2563eb; }}"
        )
        self._toggle_btn.clicked.connect(self.toggle_requested.emit)
        hl.addWidget(self._toggle_btn)

        # Expand arrow
        self._arrow_label = QLabel("▸")
        self._arrow_label.setStyleSheet(
            f"color: {COLOR_TEXT_SUB}; font-size: 14px; background: transparent;"
        )
        hl.addWidget(self._arrow_label)

        self._main_layout.addWidget(self._header)

        # ── Body (collapsible) ──
        self._body = QWidget()
        self._body.setStyleSheet("background: transparent;")
        self._body.setVisible(False)

        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(14, 4, 14, 10)
        body_layout.setSpacing(6)

        # Transcript section
        transcript_header = QLabel("LIVE TRANSCRIPT")
        transcript_header.setStyleSheet(
            f"color: {COLOR_TEXT_SUB}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px; font-family: 'Segoe UI'; background: transparent;"
        )
        body_layout.addWidget(transcript_header)

        self._transcript_scroll = QScrollArea()
        self._transcript_scroll.setWidgetResizable(True)
        self._transcript_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._transcript_scroll.setMinimumHeight(70)
        self._transcript_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._transcript_scroll.setStyleSheet(
            f"QScrollArea {{ background: #18181b; border: 1px solid #27272a; "
            f"border-radius: 8px; }} {STYLE_SCROLLBAR}"
        )

        self._transcript_label = QLabel("Waiting for audio...")
        self._transcript_label.setWordWrap(True)
        self._transcript_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._transcript_label.setStyleSheet(
            f"color: {COLOR_TEXT_SUB}; font-size: 12px; font-family: 'Segoe UI'; "
            f"background: transparent; padding: 8px;"
        )
        self._transcript_scroll.setWidget(self._transcript_label)
        body_layout.addWidget(self._transcript_scroll, 2)

        # Detected question section
        question_header = QLabel("DETECTED QUESTION")
        question_header.setStyleSheet(
            f"color: {COLOR_TEXT_SUB}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px; font-family: 'Segoe UI'; background: transparent;"
        )
        body_layout.addWidget(question_header)

        self._question_label = QLabel("—")
        self._question_label.setWordWrap(True)
        self._question_label.setStyleSheet(
            f"color: #fbbf24; font-size: 13px; font-weight: 500; "
            f"font-family: 'Segoe UI'; background: #1c1917; "
            f"border: 1px solid #292524; border-radius: 8px; padding: 8px;"
        )
        body_layout.addWidget(self._question_label)

        # Generated answer section
        answer_header = QLabel("SUGGESTED ANSWER")
        answer_header.setStyleSheet(
            f"color: {COLOR_TEXT_SUB}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px; font-family: 'Segoe UI'; background: transparent;"
        )
        body_layout.addWidget(answer_header)

        self._answer_scroll = QScrollArea()
        self._answer_scroll.setWidgetResizable(True)
        self._answer_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._answer_scroll.setMinimumHeight(110)
        self._answer_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._answer_scroll.setStyleSheet(
            f"QScrollArea {{ background: #0c1a0c; border: 1px solid #14532d; "
            f"border-radius: 8px; }} {STYLE_SCROLLBAR}"
        )

        self._answer_label = QLabel("—")
        self._answer_label.setWordWrap(True)
        self._answer_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._answer_label.setStyleSheet(
            f"color: #4ade80; font-size: 13px; font-family: 'Segoe UI'; "
            f"background: transparent; padding: 8px;"
        )
        self._answer_scroll.setWidget(self._answer_label)
        body_layout.addWidget(self._answer_scroll, 3)

        # Debug log section
        debug_header = QLabel("DEBUG LOG")
        debug_header.setStyleSheet(
            f"color: {COLOR_TEXT_SUB}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px; font-family: 'Segoe UI'; background: transparent;"
        )
        body_layout.addWidget(debug_header)

        self._debug_scroll = QScrollArea()
        self._debug_scroll.setWidgetResizable(True)
        self._debug_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._debug_scroll.setMaximumHeight(70)
        self._debug_scroll.setStyleSheet(
            f"QScrollArea {{ background: #0f0f12; border: 1px solid #27272a; "
            f"border-radius: 8px; }} {STYLE_SCROLLBAR}"
        )

        self._debug_label = QLabel("")
        self._debug_label.setWordWrap(True)
        self._debug_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._debug_label.setStyleSheet(
            f"color: #6b7280; font-size: 11px; font-family: 'Consolas', 'Courier New', monospace; "
            f"background: transparent; padding: 6px;"
        )
        self._debug_scroll.setWidget(self._debug_label)
        body_layout.addWidget(self._debug_scroll)

        self._debug_lines = []
        self._max_debug_lines = 50

        self._main_layout.addWidget(self._body, 1)

    # ── Public API ──

    def set_state(self, state: str):
        """Set the meeting state: OFF, LISTENING, THINKING."""
        self._state = state

        if state == "OFF":
            self._dot.set_color(COLOR_MEETING_OFF)
            self._dot.set_pulsing(False)
            self._status_label.setText("OFF")
            self._status_label.setStyleSheet(
                f"color: {COLOR_MEETING_OFF}; font-size: 11px; font-weight: 500; "
                f"font-family: 'Segoe UI'; background: transparent;"
            )
            self._toggle_btn.setText("Start")
            self._toggle_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLOR_ACCENT}; color: white; border: none;"
                f"  border-radius: 13px; font-size: 12px; font-weight: 600;"
                f"  font-family: 'Segoe UI';"
                f"}}"
                f"QPushButton:hover {{ background: #2563eb; }}"
            )
        elif state == "LISTENING":
            self._dot.set_color(COLOR_MEETING_LISTENING)
            self._dot.set_pulsing(True)
            self._status_label.setText("LISTENING")
            self._status_label.setStyleSheet(
                f"color: {COLOR_MEETING_LISTENING}; font-size: 11px; font-weight: 500; "
                f"font-family: 'Segoe UI'; background: transparent;"
            )
            self._toggle_btn.setText("Stop")
            self._toggle_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: #dc2626; color: white; border: none;"
                f"  border-radius: 13px; font-size: 12px; font-weight: 600;"
                f"  font-family: 'Segoe UI';"
                f"}}"
                f"QPushButton:hover {{ background: #b91c1c; }}"
            )
        elif state == "THINKING":
            self._dot.set_color(COLOR_MEETING_THINKING)
            self._dot.set_pulsing(True)
            self._status_label.setText("THINKING")
            self._status_label.setStyleSheet(
                f"color: {COLOR_MEETING_THINKING}; font-size: 11px; font-weight: 500; "
                f"font-family: 'Segoe UI'; background: transparent;"
            )
            # Keep stop button visible while thinking
            self._toggle_btn.setText("Stop")
            self._toggle_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: #dc2626; color: white; border: none;"
                f"  border-radius: 13px; font-size: 12px; font-weight: 600;"
                f"  font-family: 'Segoe UI';"
                f"}}"
                f"QPushButton:hover {{ background: #b91c1c; }}"
            )

    def set_transcript(self, text: str):
        """Update the live transcript display."""
        self._transcript_label.setText(text)
        # Auto-scroll
        QTimer.singleShot(10, lambda: self._transcript_scroll.verticalScrollBar().setValue(
            self._transcript_scroll.verticalScrollBar().maximum()
        ))

    def set_question(self, text: str):
        """Update the detected question display."""
        self._question_label.setText(text)

    def set_answer(self, text: str):
        """Update the generated answer display."""
        self._answer_label.setText(text)
        QTimer.singleShot(10, lambda: self._answer_scroll.verticalScrollBar().setValue(
            self._answer_scroll.verticalScrollBar().maximum()
        ))

    def set_error(self, text: str):
        """Show an error in the answer area."""
        self._answer_label.setText(f"⚠️ {text}")
        self._answer_label.setStyleSheet(
            f"color: #ef4444; font-size: 13px; font-family: 'Segoe UI'; "
            f"background: transparent; padding: 8px;"
        )

    def reset_display(self):
        """Reset all display fields to defaults."""
        self._transcript_label.setText("Waiting for audio...")
        self._question_label.setText("—")
        self._answer_label.setText("—")
        self._answer_label.setStyleSheet(
            f"color: #4ade80; font-size: 13px; font-family: 'Segoe UI'; "
            f"background: transparent; padding: 8px;"
        )
        self._debug_lines.clear()
        self._debug_label.setText("")

    def add_debug_log(self, msg: str):
        """Append a debug log message."""
        self._debug_lines.append(msg)
        if len(self._debug_lines) > self._max_debug_lines:
            self._debug_lines = self._debug_lines[-self._max_debug_lines:]
        self._debug_label.setText("\n".join(self._debug_lines))
        # Auto-scroll
        QTimer.singleShot(10, lambda: self._debug_scroll.verticalScrollBar().setValue(
            self._debug_scroll.verticalScrollBar().maximum()
        ))

    # ── Expand / Collapse ──

    def _expanded_target(self):
        """Height the panel opens to: fill most of the app window (not the screen)."""
        win = self.window()
        if win is not None and win.height() > 0:
            return max(self.EXPANDED_HEIGHT, win.height() - 190)
        return self.EXPANDED_HEIGHT

    def _toggle_expand(self):
        self._expanded = not self._expanded
        if self._expanded:
            self._body.setVisible(True)
            self._arrow_label.setText("▾")
            self._animate_height(self.COLLAPSED_HEIGHT, self._expanded_target())
        else:
            self._arrow_label.setText("▸")
            self._animate_height(self.maximumHeight(), self.COLLAPSED_HEIGHT)

    def _animate_height(self, from_h, to_h):
        anim = QPropertyAnimation(self, b"maximumHeight")
        anim.setDuration(250)
        anim.setStartValue(from_h)
        anim.setEndValue(to_h)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        if to_h == self.COLLAPSED_HEIGHT:
            anim.finished.connect(lambda: self._body.setVisible(False))
        self._anim = anim  # prevent GC
        anim.start()

    def expand(self):
        """Open the panel programmatically (e.g. when meeting mode starts)."""
        if not self._expanded:
            self._toggle_expand()

    def collapse(self):
        """Close the panel programmatically (e.g. when meeting mode stops)."""
        if self._expanded:
            self._toggle_expand()
