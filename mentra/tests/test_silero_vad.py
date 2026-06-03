"""Tests for the real Silero VAD (ONNX) loader and its energy-VAD fallback."""

import os
import sys
import types
import tempfile
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from mentra.workers.vad_gate import SileroVAD, EnergyVAD, VadGateWorker
from mentra.utils.styles import VAD_FRAME_SAMPLES

FRAME = VAD_FRAME_SAMPLES


def _silence():
    return np.zeros(FRAME, dtype=np.float32)


def test_energy_vad_basic():
    v = EnergyVAD()
    assert v.process(_silence()) < 0.3
    v.reset()
    assert v.process(_silence()) < 0.3


def test_missing_model_falls_back_to_energy():
    """No bundled model → energy backend, no crash, no network."""
    os.environ["SILERO_VAD_MODEL_PATH"] = os.path.join(
        tempfile.gettempdir(), "definitely_missing_silero.onnx"
    )
    try:
        vad = SileroVAD()
        assert vad.backend == "energy"
        assert vad.process(_silence()) < 0.3
    finally:
        os.environ.pop("SILERO_VAD_MODEL_PATH", None)


class _FakeInput:
    def __init__(self, name):
        self.name = name


def _make_fake_ort(run_impl, raise_on_session=False):
    class FakeSO:
        pass

    class FakeSession:
        def __init__(self, *a, **k):
            if raise_on_session:
                raise RuntimeError("cannot load model")

        def get_inputs(self):
            return [_FakeInput("input"), _FakeInput("state"), _FakeInput("sr")]

        def run(self, outs, feeds):
            return run_impl(feeds)

    return types.SimpleNamespace(
        SessionOptions=lambda: FakeSO(),
        InferenceSession=lambda *a, **k: FakeSession(*a, **k),
    )


def _with_fake_ort(fake):
    saved = sys.modules.get("onnxruntime")
    sys.modules["onnxruntime"] = fake
    return saved


def _restore_ort(saved):
    if saved is not None:
        sys.modules["onnxruntime"] = saved
    else:
        sys.modules.pop("onnxruntime", None)


def test_onnx_backend_used_when_session_loads():
    tmp = tempfile.NamedTemporaryFile(suffix=".onnx", delete=False)
    tmp.write(b"dummy")
    tmp.close()

    def run_impl(feeds):
        return [np.array([[0.91]], dtype=np.float32), feeds["state"]]

    saved = _with_fake_ort(_make_fake_ort(run_impl))
    os.environ["SILERO_VAD_MODEL_PATH"] = tmp.name
    try:
        vad = SileroVAD()
        assert vad.backend == "onnx"
        prob = vad.process(_silence())
        assert abs(prob - 0.91) < 1e-5
    finally:
        os.environ.pop("SILERO_VAD_MODEL_PATH", None)
        _restore_ort(saved)
        os.unlink(tmp.name)


def test_onnx_load_failure_falls_back():
    tmp = tempfile.NamedTemporaryFile(suffix=".onnx", delete=False)
    tmp.write(b"dummy")
    tmp.close()

    saved = _with_fake_ort(_make_fake_ort(lambda feeds: None, raise_on_session=True))
    os.environ["SILERO_VAD_MODEL_PATH"] = tmp.name
    try:
        vad = SileroVAD()
        assert vad.backend == "energy"  # graceful fallback, no crash
        assert vad.process(_silence()) < 0.3
    finally:
        os.environ.pop("SILERO_VAD_MODEL_PATH", None)
        _restore_ort(saved)
        os.unlink(tmp.name)


def test_onnx_runtime_error_degrades_midstream():
    tmp = tempfile.NamedTemporaryFile(suffix=".onnx", delete=False)
    tmp.write(b"dummy")
    tmp.close()

    def run_impl(feeds):
        raise RuntimeError("runtime blow up")

    saved = _with_fake_ort(_make_fake_ort(run_impl))
    os.environ["SILERO_VAD_MODEL_PATH"] = tmp.name
    try:
        vad = SileroVAD()
        assert vad.backend == "onnx"
        prob = vad.process(_silence())   # raises internally → degrade to energy
        assert vad.backend == "energy"
        assert prob < 0.3
    finally:
        os.environ.pop("SILERO_VAD_MODEL_PATH", None)
        _restore_ort(saved)
        os.unlink(tmp.name)


def test_worker_constructs_silero_with_fallback():
    w = VadGateWorker()
    assert w._ensure_vad() is True
    assert w._vad is not None


if __name__ == "__main__":
    test_energy_vad_basic()
    test_missing_model_falls_back_to_energy()
    test_onnx_backend_used_when_session_loads()
    test_onnx_load_failure_falls_back()
    test_onnx_runtime_error_degrades_midstream()
    test_worker_constructs_silero_with_fallback()
    print("All Silero VAD load/fallback tests passed!")
