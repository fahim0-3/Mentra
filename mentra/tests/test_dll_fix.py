"""Test: can WhisperModel load after fixing DLL paths (simulating PyQt5 environment)?"""
import os
import sys

# Simulate the DLL path fix
torch_lib = os.path.join(sys.prefix, "Lib", "site-packages", "torch", "lib")
if os.path.isdir(torch_lib):
    os.add_dll_directory(torch_lib)
    print(f"Added torch DLL dir: {torch_lib}")
else:
    print(f"No torch lib dir found at: {torch_lib}")

# Now import PyQt5 first (like the app does)
from PyQt5.QtCore import QObject
print("PyQt5 imported OK")

# Now try faster_whisper
from faster_whisper import WhisperModel
print("faster_whisper imported OK")

model = WhisperModel("base", device="cpu", compute_type="int8")
print("WhisperModel loaded OK!")

# Test torch
try:
    import torch
    print(f"torch loaded OK (version {torch.__version__})")
except Exception as e:
    print(f"torch failed: {e}")
    print("VAD filter will be disabled")
