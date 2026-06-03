import sys
sys.modules['torch'] = None
print("Mocked torch")
from faster_whisper import WhisperModel
print("Successfully imported WhisperModel!")
