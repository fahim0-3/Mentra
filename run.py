import sys

# IMPORTANT: import onnxruntime BEFORE PyQt5 (see the detailed note in main.py).
# Qt5 must not initialize before onnxruntime, or its native DLL fails to load on
# Windows, breaking faster-whisper and the VAD gate at runtime.
import onnxruntime  # noqa: F401  (do not reorder below PyQt5/mentra.ui)

from PyQt5.QtWidgets import QApplication
from mentra.ui.main_window import Mentra

def main():
    app = QApplication(sys.argv)
    # Set high DPI scaling if needed
    app.setAttribute(0x0a) # Qt.AA_EnableHighDpiScaling
    
    window = Mentra()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
