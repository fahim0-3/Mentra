import sys
# Try loading WhisperModel without PyQt5 imported
from faster_whisper import WhisperModel
print("Imported WhisperModel")
model = WhisperModel("base", device="cpu", compute_type="int8")
print("Successfully loaded WhisperModel on CPU!")
