# IMPORTANT: import onnxruntime FIRST, before any PyQt5 import.
# Importing the `mentra` package always runs this module before any submodule
# (e.g. mentra.workers.vad_gate, mentra.ui.*) that pulls in PyQt5. On Windows,
# Qt5 loads a runtime that breaks onnxruntime's native DLL initialization if Qt
# initializes first, raising:
#   ImportError: DLL load failed while importing onnxruntime_pybind11_state
# Pre-loading it here guarantees the correct order for the app, the test suite,
# and any future entry point. onnxruntime is used by faster-whisper and the VAD.
import onnxruntime  # noqa: F401
