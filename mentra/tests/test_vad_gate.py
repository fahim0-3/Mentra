"""Tests for VadGateWorker using custom SileroVAD."""

import sys
import os
import time
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from mentra.workers.vad_gate import VadGateWorker, SileroVAD

def test_silero_vad_init():
    print("Testing SileroVAD initialization...")
    vad = SileroVAD()
    assert vad is not None
    print("SileroVAD initialized successfully.")

def test_silero_vad_process():
    print("Testing SileroVAD process on silence and noise...")
    vad = SileroVAD()
    
    # Process silence
    silence = np.zeros(512, dtype=np.float32)
    prob_silence = vad.process(silence)
    print(f"Probability on silence: {prob_silence:.4f}")
    assert prob_silence < 0.3
    
    # Process sine wave (synthetic sound)
    t = np.linspace(0, 512 / 16000, 512, endpoint=False)
    sine = 0.5 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
    prob_sine = vad.process(sine)
    print(f"Probability on sine wave: {prob_sine:.4f}")
    
    # Let's reset and verify
    vad.reset()
    prob_silence_2 = vad.process(silence)
    print(f"Probability on silence after reset: {prob_silence_2:.4f}")
    assert prob_silence_2 < 0.3

def test_vad_gate_worker():
    print("Testing VadGateWorker...")
    worker = VadGateWorker()
    
    utterances = []
    def on_utterance(wav_bytes):
        utterances.append(wav_bytes)
        
    worker.utterance_ready.connect(on_utterance)
    
    # We will feed it chunks of silence (no speech should be detected)
    silence_chunk = np.zeros(16000, dtype=np.float32)
    worker.process_chunk(silence_chunk)
    
    assert len(utterances) == 0
    print("VadGateWorker successfully discarded silence chunk.")
    
    # Stop the worker
    worker.stop()

def test_vad_gate_force_flush():
    print("Testing VadGateWorker force-flush segment splitting...")
    worker = VadGateWorker()
    worker.MAX_UTTERANCE_S = 0.5  # Tuned very low to force flush quickly
    
    # Mock VAD to always return high probability (speech detected)
    class MockVAD:
        def process(self, window):
            return 1.0
        def reset(self):
            pass
    worker._vad = MockVAD()
    
    utterances = []
    def on_utterance(wav_bytes):
        utterances.append(wav_bytes)
    worker.utterance_ready.connect(on_utterance)
    
    # Feed continuous speech chunks
    speech_chunk = 0.5 * np.sin(2 * np.pi * 440 * np.linspace(0, 1, 16000, endpoint=False)).astype(np.float32)
    worker._state = "SPEAKING"
    worker._utterance_chunks = [np.zeros(512, dtype=np.float32)]
    worker._utterance_start_time = time.time() - 0.6  # Already spoken for 0.6s
    
    # Process next chunk of speech
    worker.process_chunk(speech_chunk)
    
    # Verify that at least one utterance has been emitted (force-flushed)
    print(f"Emitted force-flush utterances: {len(utterances)}")
    assert len(utterances) >= 1
    # Verify state remains SPEAKING
    print(f"State after force-flush: {worker._state}")
    assert worker._state == "SPEAKING"
    
    worker.stop()
    print("VadGateWorker force-flush segment splitting verified successfully!")

if __name__ == "__main__":
    test_silero_vad_init()
    test_silero_vad_process()
    test_vad_gate_worker()
    test_vad_gate_force_flush()
    print("All VAD tests passed!")
