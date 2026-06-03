"""Endpoint-timing tests for VadGateWorker.

Uses a scripted VAD so speech/silence boundaries are deterministic and
independent of audio content or wall-clock (except the force-flush cap, which
is intentionally time-based to remain compatible with the existing suite).
"""

import os
import sys
import time
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from mentra.workers.vad_gate import VadGateWorker
from mentra.utils.styles import (
    VAD_FRAME_SAMPLES,
    VAD_SILENCE_MS,
)

FRAME = VAD_FRAME_SAMPLES
SR = VadGateWorker.SAMPLE_RATE
# Number of silent frames required to cross the trailing-silence endpoint
SILENCE_FRAMES_TO_END = int(VAD_SILENCE_MS / 1000.0 * SR / FRAME) + 2


class ScriptedVAD:
    """Returns a pre-scripted speech probability per frame (ignores content)."""

    def __init__(self, probs):
        self.probs = list(probs)
        self.i = 0

    def process(self, window):
        v = self.probs[self.i] if self.i < len(self.probs) else self.probs[-1]
        self.i += 1
        return v

    def reset(self):
        self.i = 0


def _blank_chunk(num_frames):
    return np.zeros(num_frames * FRAME, dtype=np.float32)


def test_endpoint_after_trailing_silence():
    w = VadGateWorker()
    w._vad = ScriptedVAD([1.0] * 12 + [0.0] * 40)  # speak then go quiet
    outs = []
    w.utterance_ready.connect(outs.append)
    near = []
    w.near_end_of_speech.connect(near.append)

    w.process_chunk(_blank_chunk(12 + 40))

    assert len(outs) == 1, f"expected one endpointed utterance, got {len(outs)}"
    assert w._state == "IDLE"
    assert near and near[-1] is True  # natural endpoint signals near-end-of-speech


def test_no_endpoint_before_silence_threshold():
    w = VadGateWorker()
    # Only a few silent frames after speech — below the endpoint threshold
    w._vad = ScriptedVAD([1.0] * 12 + [0.0] * (SILENCE_FRAMES_TO_END - 4))
    outs = []
    w.utterance_ready.connect(outs.append)

    w.process_chunk(_blank_chunk(12 + (SILENCE_FRAMES_TO_END - 4)))

    assert len(outs) == 0
    assert w._state == "SPEAKING"


def test_min_utterance_blip_discarded():
    w = VadGateWorker()
    outs = []
    w.utterance_ready.connect(outs.append)
    # Hand-build a sub-MIN utterance (2 frames ≈ 64ms) and force a natural endpoint
    w._state = "SPEAKING"
    w._utterance_chunks = [np.zeros(FRAME, dtype=np.float32), np.zeros(FRAME, dtype=np.float32)]
    w._utterance_start_time = time.time()

    w._emit_utterance(force_flush=False)

    assert len(outs) == 0          # blip below VAD_MIN_UTTERANCE_MS is dropped
    assert w._state == "IDLE"


def test_force_flush_keeps_speaking():
    w = VadGateWorker()
    w.MAX_UTTERANCE_S = 0.5
    w._vad = ScriptedVAD([1.0] * 200)
    outs = []
    w.utterance_ready.connect(outs.append)

    w._state = "SPEAKING"
    w._utterance_chunks = [np.zeros(FRAME, dtype=np.float32)]
    w._utterance_start_time = time.time() - 0.6  # already over the cap

    w.process_chunk(_blank_chunk(20))

    assert len(outs) >= 1
    assert w._state == "SPEAKING"   # force-flush keeps the stream open


if __name__ == "__main__":
    test_endpoint_after_trailing_silence()
    test_no_endpoint_before_silence_threshold()
    test_min_utterance_blip_discarded()
    test_force_flush_keeps_speaking()
    print("All endpoint-timing tests passed!")
