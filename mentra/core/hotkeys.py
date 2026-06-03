from PyQt5.QtCore import QObject, pyqtSignal as Signal

class HotkeyBridge(QObject):
    """Bridge to safely pass hotkey events from the keyboard thread to the UI thread."""
    signal_toggle = Signal()
    signal_assist = Signal()
    signal_copy_last = Signal()
    signal_meeting_toggle = Signal()
    signal_meeting_analyze = Signal()
