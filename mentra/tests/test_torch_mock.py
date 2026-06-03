import sys
# Mock torch to prevent c10.dll loading / crash
sys.modules['torch'] = None

print("Mocked torch in sys.modules")

try:
    from PyQt5.QtCore import QObject
    print("PyQt5 imported OK")
except Exception as e:
    print(f"PyQt5 import failed: {e}")

try:
    from faster_whisper import WhisperModel
    print("faster_whisper imported OK")
    model = WhisperModel("base", device="cpu", compute_type="int8")
    print("WhisperModel loaded OK!")
except Exception as e:
    import traceback
    traceback.print_exc()
