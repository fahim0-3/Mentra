import sys
import signal

# IMPORTANT: import onnxruntime BEFORE PyQt5 (imported directly below and
# transitively via mentra.ui.main_window). On Windows, Qt5 loads a runtime that
# breaks onnxruntime's native DLL initialization if Qt initializes first:
#   ImportError: DLL load failed while importing onnxruntime_pybind11_state
# onnxruntime is used downstream by faster-whisper and the VAD gate.
import onnxruntime  # noqa: F401  (do not reorder below PyQt5/mentra.ui)

from mentra.ui.main_window import Mentra
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer, Qt

def main():
    # Set High DPI scaling BEFORE creating QApplication (required for some systems)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    
    app = QApplication(sys.argv)
    
    # Custom handler for Ctrl+C to stop app gracefully
    def sigint_handler(*args):
        QApplication.quit()
    
    signal.signal(signal.SIGINT, sigint_handler)
    
    window = Mentra()
    window.show()
    
    # Heartbeat timer parented to 'app' for thread-safe cleanup
    timer = QTimer(app)
    timer.start(500)
    timer.timeout.connect(lambda: None) 
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()