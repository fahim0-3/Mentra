import uuid
import threading
import ollama
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QScrollArea, QFrame, QStackedWidget,
    QSplitter, QApplication
)
from PyQt5.QtCore import (
    Qt, QTimer, QSize, QThread, QRect
)
from PyQt5.QtGui import QIcon, QPalette, QColor

from mentra.core.chat_manager import ChatManager
from mentra.core.hotkeys import HotkeyBridge
from mentra.workers.llm_worker import StreamWorker
from mentra.workers.screen_worker import ScreenReaderWorker
from mentra.workers.audio_capture_worker import AudioCaptureWorker
from mentra.workers.vad_gate import VadGateWorker
from mentra.workers.groq_provider import GroqProvider, LocalProvider, GroqSTTWorker
from mentra.workers.meeting_assistant_worker import MeetingAssistantWorker
from mentra.ui.components.resize_grip import ResizeGrip
from mentra.ui.components.meeting_panel import MeetingPanel
from mentra.ui.sidebar.history_panel import HistoryPanel
from mentra.ui.chat.message_bubble import MessageBubble
from mentra.utils.quota_guard import DailyQuotaGuard
from mentra.utils.styles import (
    WINDOW_WIDTH, WINDOW_HEIGHT, COLOR_BG, COLOR_INPUT_BG,
    COLOR_TEXT_MAIN, COLOR_TEXT_SUB, GRIP, HOTKEY,
    OLLAMA_MODEL, STYLE_SCROLLBAR, COLOR_MEETING_OFF,
    COLOR_MEETING_LISTENING, COLOR_MEETING_THINKING,
)
from mentra.utils.assets import (
    make_send_icon, make_copy_icon, make_stop_icon,
    make_edit_icon, make_delete_icon
)

class Mentra(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mentra")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(0.95)
        
        try:
            import ctypes
            ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), 0x00000011)
        except Exception:
            pass
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

        # Icons (created once)
        self.icons = {
            'send': make_send_icon(),
            'copy': make_copy_icon(),
            'stop': make_stop_icon(),
            'edit': make_edit_icon(),
            'delete': make_delete_icon()
        }

        # Core Logic
        self.chat_manager = ChatManager()
        self.current_chat_id = str(uuid.uuid4())
        self.history_visible = False
        self.sessions = {}  # { chat_id: { "messages": [], "is_generating": False, ... } }

        self.SYSTEM_PROMPT = (
            "You are Mentra, an expert AI assistant. Follow these rules:\n"
            "1. Give direct, accurate answers. No filler or hedging.\n"
            "2. Keep all responses extremely concise and short.\n"
            "3. For code questions: provide working code with brief explanation.\n"
            "4. For factual questions: state facts clearly, cite reasoning.\n"
            "5. If unsure, say so — never fabricate information.\n"
            "6. Use markdown formatting when helpful.\n"
            "7. When assisting with screen/window content, solve the visible problem directly instead of describing it.\n"
            "8. Do NOT narrate the user's activity. Focus on the solution.\n"
        )
        
        # UI State
        self.is_visible = True
        self.chat_started = False
        self.is_assisting = False
        self.message_widgets = [] # Store MessageBubble instances
        self._drag_pos = None

        # Meeting Assistant state
        self.meeting_active = False
        self.meeting_state = "OFF"
        self._meeting_audio_thread = None
        self._meeting_audio_worker = None
        self._meeting_vad_thread = None
        self._meeting_vad_worker = None
        self._meeting_stt_thread = None
        self._meeting_stt_worker = None
        self._meeting_assistant_thread = None
        self._meeting_assistant_worker = None
        self._meeting_stop_event = None
        self._meeting_quota_guard = DailyQuotaGuard(limit=1900)
        self._meeting_provider = None
        self._meeting_connectivity_timer = None
        # Threads that did not stop in time are parked here (kept referenced) so
        # they are never destroyed while still running, then self-delete on exit.
        self._zombie_threads = []

        # Hotkey bridge
        self.bridge = HotkeyBridge()
        self.bridge.signal_toggle.connect(self.toggle_visibility)
        self.bridge.signal_assist.connect(self.handle_assist)
        self.bridge.signal_copy_last.connect(self.copy_last_response)
        self.bridge.signal_meeting_toggle.connect(self.toggle_meeting)
        self.bridge.signal_meeting_analyze.connect(self.manual_meeting_analyze)

        # ollama client
        self.client = ollama.Client()

        # Build UI
        self._build_ui()
        self._setup_resize_grips()
        self._center()
        self._setup_hotkeys()

        QTimer.singleShot(100, self.input_entry.setFocus)
        threading.Thread(target=self._warmup, daemon=True).start()

    def _setup_hotkeys(self):
        """Standardized hotkey setup."""
        import keyboard
        try:
            keyboard.add_hotkey(HOTKEY, self.bridge.signal_toggle.emit, suppress=True)
            keyboard.add_hotkey("ctrl+i", self.bridge.signal_assist.emit, suppress=True)
            keyboard.add_hotkey("ctrl+0", self.bridge.signal_copy_last.emit, suppress=True)
            keyboard.add_hotkey("ctrl+shift+m", self.bridge.signal_meeting_toggle.emit, suppress=True)
            keyboard.add_hotkey("ctrl+shift+a", self.bridge.signal_meeting_analyze.emit, suppress=True)
        except Exception as e:
            print(f"Hotkey registration failed: {e}. Run as Admin.")

    def closeEvent(self, ev):
        try:
            import keyboard
            keyboard.unhook_all()
        except:
            pass
        
        # Shutdown meeting assistant
        self._stop_meeting_workers()

        # Shutdown all background workers gracefully
        for session in self.sessions.values():
            if session.get("stop_event"):
                session["stop_event"].set()
            if session.get("thread") and session["thread"].isRunning():
                session["thread"].quit()
                session["thread"].wait(500)

        if hasattr(self, '_reader_thread') and self._reader_thread and self._reader_thread.isRunning():
            self._reader_thread.quit()
            self._reader_thread.wait(500)
            
        super().closeEvent(ev)

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        root.setStyleSheet(
            f"#root{{background:{COLOR_BG};border:1px solid #27272a;border-radius:20px;}}"
        )
        self.setCentralWidget(root)

        box = QVBoxLayout(root)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(1)
        self.main_splitter.setStyleSheet("QSplitter::handle{background:#27272a;}")
        box.addWidget(self.main_splitter)

        # Sidebar
        self.history_panel = HistoryPanel(self.chat_manager, self.icons, root)
        self.history_panel.load_chat.connect(self.load_chat)
        self.history_panel.new_chat.connect(self.clear_chat)
        self.history_panel.collapse_clicked.connect(self.toggle_history)
        self.history_panel.chat_deleted.connect(self._on_chat_deleted)
        self.history_panel.hide()
        self.main_splitter.addWidget(self.history_panel)

        # Content area
        self.content_container = QWidget()
        self.content_container.setStyleSheet("background:transparent;")
        self.content_vbox = QVBoxLayout(self.content_container)
        self.content_vbox.setContentsMargins(0, 0, 0, 0)
        self.content_vbox.setSpacing(0)
        self.main_splitter.addWidget(self.content_container)

        self._build_header(self.content_vbox)
        self._build_content(self.content_vbox)
        self._build_footer(self.content_vbox)

    def _build_header(self, parent):
        hdr = QWidget()
        hdr.setFixedHeight(50)
        hdr.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(hdr)
        lay.setContentsMargins(20, 12, 20, 0)
        lay.setSpacing(5)

        self.home_btn = self._make_btn("⌂", 30, 30, "#333", "#444")
        self.home_btn.clicked.connect(self.clear_chat)
        lay.addWidget(self.home_btn)

        self.tab_chat = self._make_btn("Chat", 60, 30, "#333", "#444", radius=15)
        self.tab_chat.clicked.connect(self.toggle_history)
        lay.addWidget(self.tab_chat)

        lay.addStretch()

        self.new_chat_btn = self._make_btn(
            "＋ New", 70, 30, "transparent", "#333",
            text_color=COLOR_TEXT_SUB, radius=15,
        )
        self.new_chat_btn.clicked.connect(self.clear_chat)
        lay.addWidget(self.new_chat_btn)

        self.close_btn = self._make_btn("✕", 30, 30, "transparent", "#cc0000")
        self.close_btn.clicked.connect(self.hide_window)
        lay.addWidget(self.close_btn)

        parent.addWidget(hdr)
        self._header = hdr

    def _build_content(self, parent):
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background:transparent;")

        # Dashboard
        dash = QWidget()
        dl = QVBoxLayout(dash)
        dl.setContentsMargins(20, 0, 20, 0)
        dl.addStretch()
        self.lbl_greeting = QLabel("What can I help with?")
        self.lbl_greeting.setAlignment(Qt.AlignCenter)
        self.lbl_greeting.setStyleSheet(
            f"color:{COLOR_TEXT_MAIN};font-size:29px;font-weight:bold;font-family:'Segoe UI';"
        )
        dl.addWidget(self.lbl_greeting)
        dl.addStretch()
        self.stack.addWidget(dash)

        # Chat
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_scroll.setStyleSheet(f"QScrollArea{{background:transparent;border:none;}} {STYLE_SCROLLBAR}")
        
        self._chat_inner = QWidget()
        self._chat_vbox = QVBoxLayout(self._chat_inner)
        self._chat_vbox.setContentsMargins(0, 0, 0, 0)
        self._chat_vbox.setSpacing(0)
        self._chat_vbox.addStretch()
        self.chat_scroll.setWidget(self._chat_inner)
        self.stack.addWidget(self.chat_scroll)

        parent.addWidget(self.stack, 1)

    def _build_footer(self, parent):
        foot = QWidget()
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(20, 0, 20, 15)
        fl.setSpacing(8)

        # Meeting panel (collapsible)
        self.meeting_panel = MeetingPanel()
        self.meeting_panel.toggle_requested.connect(self.toggle_meeting)
        fl.addWidget(self.meeting_panel)

        chips_lay = QHBoxLayout()
        for t in ["✨ Assist", "✎ What should I say?"]:
            c = QPushButton(t)
            c.setCursor(Qt.PointingHandCursor)
            c.setStyleSheet(
                "QPushButton{background:transparent;color:grey;border:none;font-size:14px;padding:4px 8px;}"
                "QPushButton:hover{background:#333;border-radius:8px;}"
            )
            chips_lay.addWidget(c)
        chips_lay.addStretch()
        fl.addLayout(chips_lay)

        self.assist_btn = chips_lay.itemAt(0).widget()
        self.assist_btn.clicked.connect(self.handle_assist)

        bar = QFrame()
        bar.setStyleSheet(f"QFrame{{background:{COLOR_INPUT_BG};border:1px solid #3f3f46;border-radius:25px;}}")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(15, 8, 10, 8)

        self.input_entry = QLineEdit()
        self.input_entry.setPlaceholderText("Ask anything")
        self.input_entry.setStyleSheet(f"QLineEdit{{background:transparent;border:none;color:{COLOR_TEXT_MAIN};font-size:16px;}}")
        pal = self.input_entry.palette()
        pal.setColor(QPalette.PlaceholderText, QColor("#a1a1aa"))
        self.input_entry.setPalette(pal)
        self.input_entry.returnPressed.connect(self.send_query)
        bl.addWidget(self.input_entry)

        self.btn_send = QPushButton()
        self.btn_send.setIcon(QIcon(self.icons['send']))
        self.btn_send.setIconSize(QSize(20, 20))
        self.btn_send.setFixedSize(36, 36)
        self.btn_send.setCursor(Qt.PointingHandCursor)
        self.btn_send.setStyleSheet("QPushButton{background:#2563eb;border:none;border-radius:18px;}QPushButton:hover{background:#1d4ed8;}")
        self.btn_send.clicked.connect(self.handle_send_btn)
        bl.addWidget(self.btn_send)

        fl.addWidget(bar)

        # Footer status label
        self._meeting_status_label = QLabel("Meeting: OFF")
        self._meeting_status_label.setAlignment(Qt.AlignCenter)
        self._meeting_status_label.setStyleSheet(
            f"color: {COLOR_MEETING_OFF}; font-size: 11px; font-family: 'Segoe UI'; background: transparent;"
        )
        fl.addWidget(self._meeting_status_label)

        parent.addWidget(foot)

    def handle_send_btn(self):
        session = self.get_session(self.current_chat_id)
        if session["is_generating"]:
            if session["stop_event"]:
                session["stop_event"].set()
                # Immediate UI feedback for stop
                self.btn_send.setIcon(QIcon(self.icons['send']))
        else:
            self.send_query()

    def _setup_resize_grips(self):
        self._grips = []
        for d in ("n", "s", "e", "w", "ne", "nw", "se", "sw"):
            g = ResizeGrip(self, d)
            self._grips.append((d, g))
        self._update_grips()

    def _update_grips(self):
        w, h = self.width(), self.height()
        t, c = GRIP, 16
        pos = {
            "n":  QRect(c, 0, w - 2 * c, t),
            "s":  QRect(c, h - t, w - 2 * c, t),
            "w":  QRect(0, c, t, h - 2 * c),
            "e":  QRect(w - t, c, t, h - 2 * c),
            "nw": QRect(0, 0, c, c),
            "ne": QRect(w - c, 0, c, c),
            "sw": QRect(0, h - c, c, c),
            "se": QRect(w - c, h - c, c, c),
        }
        for d, grip in self._grips:
            grip.setGeometry(pos[d])
            grip.raise_()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._update_grips()
        max_user = int(self.width() * 0.55)
        max_ai = int(self.width() * 0.70)
        for bubble in self.message_widgets:
            bubble.bubble.setMaximumWidth(max_user if bubble.is_user else max_ai)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            child = self.childAt(ev.pos())
            if child and self._is_header_area(child):
                self._drag_pos = ev.globalPos() - self.frameGeometry().topLeft()
                ev.accept()
                return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag_pos is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPos() - self._drag_pos)
            ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag_pos = None

    def _is_header_area(self, widget):
        if isinstance(widget, QPushButton): return False
        w = widget
        while w:
            if w is self._header: return True
            w = w.parentWidget()
        return False

    def get_session(self, chat_id):
        if chat_id not in self.sessions:
            chat = self.chat_manager.get_chat(chat_id)
            messages = chat["messages"] if chat else [{"role": "system", "content": self.SYSTEM_PROMPT}]
            self.sessions[chat_id] = {
                "messages": list(messages),
                "is_generating": False,
                "worker": None, "thread": None, "ai_bubble": None, "stop_event": None
            }
        return self.sessions[chat_id]

    def send_query(self):
        session = self.get_session(self.current_chat_id)
        if session["is_generating"]: return
        prompt = self.input_entry.text().strip()
        if not prompt: return

        if not self.chat_started:
            self.stack.setCurrentIndex(1)
            self.chat_started = True

        self.input_entry.clear()
        chat_id = self.current_chat_id
        session["messages"].append({"role": "user", "content": prompt})
        self.chat_manager.save_chat(chat_id, session["messages"])
        if self.history_visible: self.history_panel.refresh()

        user_idx = len(session["messages"]) - 1
        self._add_bubble_widget(prompt, is_user=True, history_index=user_idx)

        ai_bubble = self._add_bubble_widget("", is_user=False)
        session["ai_bubble"] = ai_bubble
        session["stop_event"] = threading.Event()
        
        worker = StreamWorker(self.client, OLLAMA_MODEL, chat_id, list(session["messages"]), session["stop_event"])
        thread = QThread()
        worker.moveToThread(thread)
        worker.text_updated.connect(self._on_stream_update)
        worker.finished.connect(self._on_stream_finished)
        worker.error.connect(self._on_stream_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        thread.started.connect(worker.run)
        session["worker"] = worker
        session["thread"] = thread
        thread.start()
        self._set_generating_state(chat_id, True)

    def _on_stream_update(self, chat_id, txt):
        if chat_id not in self.sessions: return
        session = self.sessions[chat_id]
        session["current_text"] = txt
        if chat_id != self.current_chat_id: return
        if session.get("ai_bubble"):
            session["ai_bubble"].setText(txt)
            self._scroll_bottom()

    def _on_stream_finished(self, chat_id, full):
        if chat_id not in self.sessions: return
        session = self.sessions[chat_id]
        if full.strip():
            session["messages"].append({"role": "assistant", "content": full})
            self.chat_manager.save_chat(chat_id, session["messages"])
            if self.history_visible: self.history_panel.refresh()

        session["current_text"] = ""
        self._set_generating_state(chat_id, False)

    def _on_stream_error(self, chat_id, msg):
        if chat_id not in self.sessions: return
        session = self.sessions[chat_id]
        if chat_id == self.current_chat_id:
            self._add_bubble_widget(f"⚠️ Error: {msg}", is_user=False)
        session["current_text"] = ""
        self._set_generating_state(chat_id, False)

    def _scroll_bottom(self):
        QTimer.singleShot(10, lambda: self.chat_scroll.verticalScrollBar().setValue(self.chat_scroll.verticalScrollBar().maximum()))

    def _rebuild_chat(self):
        while self._chat_vbox.count() > 1:
            item = self._chat_vbox.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.message_widgets.clear()
        session = self.get_session(self.current_chat_id)
        for i, msg in enumerate(session["messages"]):
            if msg["role"] == "system": continue
            self._add_bubble_widget(msg["content"], is_user=(msg["role"] == "user"), history_index=i)
        if session["is_generating"]:
            session["ai_bubble"] = self._add_bubble_widget(session.get("current_text", ""), is_user=False)
        self._scroll_bottom()

    def _add_bubble_widget(self, text, is_user, history_index=None):
        bubble = MessageBubble(text, is_user, history_index, self.icons)
        bubble.edit_submitted.connect(self._on_edit_submitted)
        max_w = int(self.width() * (0.55 if is_user else 0.70))
        bubble.bubble.setMaximumWidth(max_w)
        self._chat_vbox.insertWidget(self._chat_vbox.count() - 1, bubble)
        self.message_widgets.append(bubble)
        self._scroll_bottom()
        return bubble

    def _on_edit_submitted(self, index, text):
        session = self.get_session(self.current_chat_id)
        session["messages"] = session["messages"][:index]
        self._rebuild_chat()
        self.input_entry.setText(text)
        self.send_query()

    def _on_chat_deleted(self, chat_id):
        if chat_id == self.current_chat_id: self.clear_chat()

    def _warmup(self):
        try: self.client.chat(model=OLLAMA_MODEL, messages=[{"role": "user", "content": "hi"}], keep_alive="30m")
        except: pass

    def toggle_visibility(self):
        if self.is_visible: self.hide_window()
        else: self.show_window()

    def toggle_history(self):
        self.history_visible = not self.history_visible
        if self.history_visible:
            self.history_panel.show()
            self.history_panel.refresh()
            self.main_splitter.setSizes([260, self.width() - 260])
        else:
            self.history_panel.hide()

    def show_window(self):
        self.show(); self.raise_(); self.activateWindow()
        self.is_visible = True
        self.input_entry.setFocus(); self.input_entry.selectAll()

    def hide_window(self):
        self.hide(); self.is_visible = False

    def clear_chat(self):
        session = self.sessions.get(self.current_chat_id)

        if session and len(session["messages"]) > 1:
            self.chat_manager.save_chat(self.current_chat_id, session["messages"])
        self.current_chat_id = str(uuid.uuid4())
        if self.chat_started:
            while self._chat_vbox.count() > 1:
                item = self._chat_vbox.takeAt(0)
                if item.widget(): item.widget().deleteLater()
            self.message_widgets.clear()
            self.stack.setCurrentIndex(0)
            self.chat_started = False
        if self.history_visible: self.history_panel.refresh()
        self.input_entry.setFocus()

    def load_chat(self, chat_id):
        self.current_chat_id = chat_id
        session = self.get_session(chat_id)
        if not self.chat_started:
            self.stack.setCurrentIndex(1)
            self.chat_started = True
        self._rebuild_chat()
        self.input_entry.setFocus()
        
        # Consistent button state for loaded chat
        self._set_generating_state(chat_id, session["is_generating"])

    def handle_assist(self):
        session = self.get_session(self.current_chat_id)
        if session["is_generating"] or self.is_assisting: return
        self.is_assisting = True
        if not self.chat_started:
            self.stack.setCurrentIndex(1)
            self.chat_started = True
        self._add_bubble_widget("✨ Analyzing screen...", is_user=False)
        self.hide()
        
        # Delay start so the window fully hides and modifier keys (Ctrl+I) release
        QTimer.singleShot(400, self._start_screen_reader)

    def _start_screen_reader(self):
        """Start the screen reader worker on a background thread."""
        # Clean up any previous reader objects
        if hasattr(self, '_reader_worker'):
            self._reader_worker = None
        if hasattr(self, '_reader_thread') and self._reader_thread is not None:
            if self._reader_thread.isRunning():
                self._reader_thread.quit()
                self._reader_thread.wait(500)
            self._reader_thread = None

        self._reader_worker = ScreenReaderWorker()
        self._reader_thread = QThread()
        self._reader_worker.moveToThread(self._reader_thread)
        self._reader_worker.finished.connect(self._on_read_success)
        self._reader_worker.error.connect(self._on_read_error)
        
        # Thread lifecycle — prevent deleteLater from nuking Python refs
        self._reader_worker.finished.connect(self._reader_thread.quit)
        self._reader_worker.error.connect(self._reader_thread.quit)
        self._reader_thread.finished.connect(self._cleanup_reader)
        
        self._reader_thread.started.connect(self._reader_worker.run)
        self._reader_thread.start()

    def _cleanup_reader(self):
        """Safely clean up reader objects after thread finishes."""
        self._reader_worker = None
        self._reader_thread = None

    def _on_read_error(self, msg):
        self.show()
        self._add_bubble_widget(f"⚠️ {msg}", is_user=False)
        self.is_assisting = False

    def _on_read_success(self, prompt):
        self.show()
        chat_id = self.current_chat_id
        session = self.get_session(chat_id)
        session["messages"].append({"role": "user", "content": prompt})
        ai_bubble = self._add_bubble_widget("", is_user=False)
        session["ai_bubble"] = ai_bubble
        session["stop_event"] = threading.Event()
        worker = StreamWorker(self.client, OLLAMA_MODEL, chat_id, list(session["messages"]), session["stop_event"])
        thread = QThread()
        worker.moveToThread(thread)
        worker.text_updated.connect(self._on_stream_update)
        worker.finished.connect(self._on_stream_finished)
        worker.error.connect(self._on_stream_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        thread.started.connect(worker.run)
        session["worker"] = worker; session["thread"] = thread
        thread.start()
        self._set_generating_state(chat_id, True)
        self.is_assisting = False

    def copy_last_response(self):
        session = self.get_session(self.current_chat_id)
        for msg in reversed(session["messages"]):
            if msg.get("role") == "assistant" and msg.get("content"):
                import pyperclip
                pyperclip.copy(msg["content"])
                orig = self.input_entry.placeholderText()
                self.input_entry.setPlaceholderText("Copied to clipboard!")
                QTimer.singleShot(2000, lambda: self.input_entry.setPlaceholderText(orig))
                return

    def _center(self):
        desktop = QApplication.desktop()
        s = desktop.availableGeometry(self)
        self.move((s.width() - self.width()) // 2, (s.height() - self.height()) // 2)

    def _set_generating_state(self, chat_id, is_generating):
        session = self.get_session(chat_id)
        session["is_generating"] = is_generating
        if chat_id == self.current_chat_id:
            icon = self.icons['stop'] if is_generating else self.icons['send']
            self.btn_send.setIcon(QIcon(icon))

    def _make_btn(self, text, w, h, bg, hover, text_color=COLOR_TEXT_MAIN, radius=8):
        b = QPushButton(text)
        b.setFixedSize(w, h)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(f"QPushButton{{background:{bg};color:{text_color};border:none;border-radius:{radius}px;font-size:15px;}}QPushButton:hover{{background:{hover};}}")
        return b

    # ══════════════════════════════════════════════════════════════════
    #  Meeting Assistant
    # ══════════════════════════════════════════════════════════════════

    def toggle_meeting(self):
        """Start or stop the Meeting Assistant."""
        if self.meeting_active:
            self._stop_meeting()
        else:
            # Reveal the window if it is hidden so the meeting panel is visible.
            if not self.is_visible:
                self.show_window()
            self._start_meeting()

    def _start_meeting(self):
        """Spin up the audio → VAD → STT → analysis pipeline."""
        self._meeting_stop_event = threading.Event()

        # ── Select provider (Groq cloud or local fallback) ──
        groq = GroqProvider()
        if groq.is_available():
            self._meeting_provider = groq
            provider_name = "Groq Cloud"
        else:
            self._meeting_provider = LocalProvider()
            provider_name = "Local (offline fallback)"
        self.meeting_panel.add_debug_log(f"[Meeting] Provider: {provider_name}")

        # ── Audio capture worker ──
        self._meeting_audio_worker = AudioCaptureWorker(self._meeting_stop_event)
        self._meeting_audio_thread = QThread()
        self._meeting_audio_worker.moveToThread(self._meeting_audio_thread)

        # ── VAD gate worker ──
        self._meeting_vad_worker = VadGateWorker()
        self._meeting_vad_thread = QThread()
        self._meeting_vad_worker.moveToThread(self._meeting_vad_thread)

        # ── STT worker ──
        self._meeting_stt_worker = GroqSTTWorker(
            self._meeting_provider, self._meeting_quota_guard
        )
        self._meeting_stt_thread = QThread()
        self._meeting_stt_worker.moveToThread(self._meeting_stt_thread)

        # ── Meeting assistant worker ──
        self._meeting_assistant_worker = MeetingAssistantWorker(
            provider=self._meeting_provider,
            quota_guard=self._meeting_quota_guard,
        )
        self._meeting_assistant_thread = QThread()
        self._meeting_assistant_worker.moveToThread(self._meeting_assistant_thread)

        # ── Wire the pipeline ──
        # Audio → VAD
        self._meeting_audio_worker.audio_chunk_ready.connect(
            self._meeting_vad_worker.process_chunk
        )
        # VAD → STT
        self._meeting_vad_worker.utterance_ready.connect(
            self._meeting_stt_worker.transcribe_utterance
        )
        # VAD (rolling display) → UI Panel
        self._meeting_vad_worker.transcript_updated.connect(
            self._on_meeting_transcript_updated
        )
        # VAD (near end-of-speech) → Assistant (enables speculative answering)
        self._meeting_vad_worker.near_end_of_speech.connect(
            self._meeting_assistant_worker.set_near_end_of_speech
        )
        # STT text → VAD (update finalized segments) + Question Detector
        self._meeting_stt_worker.text_ready.connect(
            self._on_meeting_stt_text_ready
        )
        # Analysis → Panel
        self._meeting_assistant_worker.question_detected.connect(
            self._on_meeting_question_detected
        )
        self._meeting_assistant_worker.thinking.connect(
            self._on_meeting_thinking
        )
        self._meeting_assistant_worker.answer_chunk.connect(
            self._on_meeting_answer_chunk
        )
        self._meeting_assistant_worker.answer_ready.connect(
            self._on_meeting_answer_ready
        )

        # ── Error signals ──
        self._meeting_audio_worker.error.connect(self._on_meeting_error)
        self._meeting_stt_worker.error.connect(self._on_meeting_error)
        self._meeting_assistant_worker.error.connect(self._on_meeting_error)

        # ── Debug log signals ──
        self._meeting_audio_worker.debug_log.connect(
            self.meeting_panel.add_debug_log
        )
        self._meeting_vad_worker.debug_log.connect(
            self.meeting_panel.add_debug_log
        )
        self._meeting_stt_worker.debug_log.connect(
            self.meeting_panel.add_debug_log
        )
        self._meeting_assistant_worker.debug_log.connect(
            self.meeting_panel.add_debug_log
        )

        # ── Start threads ──
        self._meeting_audio_thread.started.connect(self._meeting_audio_worker.run)
        self._meeting_audio_thread.start()
        self._meeting_vad_thread.start()
        self._meeting_stt_thread.start()
        self._meeting_assistant_thread.start()

        # ── Periodic connectivity re-check (every 60s) ──
        self._meeting_connectivity_timer = QTimer(self)
        self._meeting_connectivity_timer.setInterval(60000)
        self._meeting_connectivity_timer.timeout.connect(self._recheck_provider)
        self._meeting_connectivity_timer.start()

        # ── Update state ──
        self.meeting_active = True
        self._set_meeting_state("LISTENING")
        self.meeting_panel.reset_display()
        # Auto-expand so the transcript, question and answer are visible at once.
        self.meeting_panel.expand()

    def _stop_meeting(self):
        """Cleanly shut down the meeting pipeline."""
        self._stop_meeting_workers()
        self.meeting_active = False
        self._set_meeting_state("OFF")
        self.meeting_panel.reset_display()
        # Collapse back to the compact header when meeting mode is off.
        self.meeting_panel.collapse()

    def _stop_meeting_workers(self):
        """Stop all meeting worker threads without ever destroying a live thread.

        Destroying a QThread that is still running aborts the whole process
        ("QThread: Destroyed while thread is still running"). So we silence the
        pipeline, ask every worker to stop, then quit/wait each thread; any
        thread that does not finish in time is parked and left to self-delete
        when it eventually exits, rather than being torn down underneath Qt.
        """
        # Stop connectivity timer
        if self._meeting_connectivity_timer:
            self._meeting_connectivity_timer.stop()
            self._meeting_connectivity_timer = None

        workers = [
            self._meeting_audio_worker,
            self._meeting_vad_worker,
            self._meeting_stt_worker,
            self._meeting_assistant_worker,
        ]
        threads = [
            self._meeting_audio_thread,
            self._meeting_vad_thread,
            self._meeting_stt_thread,
            self._meeting_assistant_thread,
        ]

        # Silence the pipeline so no queued cross-thread slot fires on a
        # half-torn-down worker during shutdown.
        for w in workers:
            if w is not None:
                try:
                    w.blockSignals(True)
                except RuntimeError:
                    pass

        # Signal workers to stop their loops
        if self._meeting_stop_event:
            self._meeting_stop_event.set()
        if self._meeting_vad_worker:
            self._meeting_vad_worker.stop()
        if self._meeting_stt_worker:
            self._meeting_stt_worker.stop()
        if self._meeting_assistant_worker:
            self._meeting_assistant_worker.stop()

        # Clean up local provider subprocess
        if isinstance(self._meeting_provider, LocalProvider):
            try:
                self._meeting_provider.stop()
            except Exception:
                pass

        # Quit + wait for each thread; defer cleanup of any that overrun.
        for thread, worker in zip(threads, workers):
            if thread is None:
                continue
            thread.quit()
            if not thread.wait(3000):
                # Do NOT destroy a running thread. Keep it referenced and let
                # it (and its worker) delete themselves once they finish.
                if worker is not None:
                    thread.finished.connect(worker.deleteLater)
                thread.finished.connect(thread.deleteLater)
                self._zombie_threads.append(thread)
                self.meeting_panel.add_debug_log(
                    "[Meeting] A worker is still finishing; it will clean up in the background."
                )

        # Release references (timed-out threads are safely held in _zombie_threads)
        self._meeting_audio_worker = None
        self._meeting_audio_thread = None
        self._meeting_vad_worker = None
        self._meeting_vad_thread = None
        self._meeting_stt_worker = None
        self._meeting_stt_thread = None
        self._meeting_assistant_worker = None
        self._meeting_assistant_thread = None
        self._meeting_stop_event = None
        self._meeting_provider = None

    def manual_meeting_analyze(self):
        """Ctrl+Shift+A — manually analyze the current transcript."""
        if not self.meeting_active:
            return
        if self._meeting_vad_worker and self._meeting_assistant_worker:
            transcript = self._meeting_vad_worker.get_current_transcript()
            self._meeting_assistant_worker.manual_analyze(transcript)

    def _recheck_provider(self):
        """Periodically re-check Groq connectivity and switch providers."""
        if not self.meeting_active:
            return
        groq = GroqProvider()
        currently_cloud = isinstance(self._meeting_provider, GroqProvider)
        if not currently_cloud and groq.is_available():
            self._meeting_provider = groq
            if self._meeting_stt_worker:
                self._meeting_stt_worker.set_provider(groq)
            if self._meeting_assistant_worker:
                self._meeting_assistant_worker.set_provider(groq)
            self.meeting_panel.add_debug_log("[Meeting] Switched to Groq Cloud provider")

    # ── Meeting signal handlers ──

    def _on_meeting_transcript_updated(self, transcript: str):
        """Called when the VAD worker emits rolling transcript display."""
        self.meeting_panel.set_transcript(transcript)

    def _on_meeting_stt_text_ready(self, text: str):
        """Called when GroqSTTWorker returns finalized text for an utterance."""
        # Update the VAD worker's finalized segments for display
        if self._meeting_vad_worker:
            self._meeting_vad_worker.add_finalized_text(text)
        # Feed to question detector
        if self._meeting_assistant_worker and self._meeting_vad_worker:
            full_transcript = self._meeting_vad_worker.get_current_transcript()
            self._meeting_assistant_worker.analyze(full_transcript)

    def _on_meeting_question_detected(self, question: str):
        self.meeting_panel.set_question(question)

    def _on_meeting_thinking(self):
        self._set_meeting_state("THINKING")

    def _on_meeting_answer_chunk(self, partial_answer: str):
        """Called for each streamed answer delta — word-by-word UI update."""
        self.meeting_panel.set_answer(partial_answer)

    def _on_meeting_answer_ready(self, answer: str):
        self.meeting_panel.set_answer(answer)
        self._set_meeting_state("LISTENING")

    def _on_meeting_error(self, msg: str):
        self.meeting_panel.set_error(msg)
        # If we were thinking, drop back to listening
        if self.meeting_state == "THINKING":
            self._set_meeting_state("LISTENING")

    def _set_meeting_state(self, state: str):
        """Update meeting state across panel + footer."""
        self.meeting_state = state
        self.meeting_panel.set_state(state)

        color_map = {
            "OFF": COLOR_MEETING_OFF,
            "LISTENING": COLOR_MEETING_LISTENING,
            "THINKING": COLOR_MEETING_THINKING,
        }
        color = color_map.get(state, COLOR_MEETING_OFF)
        self._meeting_status_label.setText(f"Meeting: {state}")
        self._meeting_status_label.setStyleSheet(
            f"color: {color}; font-size: 11px; font-family: 'Segoe UI'; background: transparent;"
        )
