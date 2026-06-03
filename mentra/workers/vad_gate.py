"""VAD-gated utterance batcher for meeting mode.

Receives short 16kHz mono chunks from AudioCaptureWorker, runs Silero VAD to
detect speech boundaries, and emits complete utterances as WAV bytes.  Each
utterance is emitted exactly once.

Speech detection uses the genuine **Silero VAD ONNX model** via onnxruntime.
If the bundled model is missing or fails to load, it degrades transparently to
a pure-Python adaptive energy detector so meeting mode never crashes and never
requires the network at start.
"""

import io
import os
import struct
import time
import datetime
import threading
import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal as Signal, pyqtSlot as Slot

from mentra.utils.styles import (
    VAD_SILENCE_MS,
    VAD_MAX_UTTERANCE_MS,
    VAD_MIN_UTTERANCE_MS,
    VAD_FRAME_SAMPLES,
    VAD_SPEECH_THRESHOLD,
    VAD_NEAR_END_FRACTION,
    SILERO_VAD_MODEL_FILENAME,
)


class EnergyVAD:
    """Pure-Python, adaptive energy-based Voice Activity Detector (fallback).

    Guarantees 100% platform compatibility and zero DLL or model dependencies.
    Used automatically whenever the Silero ONNX model is unavailable.
    """

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.reset()

    def reset(self):
        self._noise_floor = 0.005  # Initial estimate of ambient noise RMS
        self._alpha_noise = 0.98   # Slow noise floor update coefficient
        self.min_noise = 0.001

    def process(self, window_f32: np.ndarray) -> float:
        # Calculate Root Mean Square (RMS) of the frame
        if len(window_f32) != VAD_FRAME_SAMPLES:
            return 0.0

        rms = float(np.sqrt(np.mean(window_f32 ** 2)))
        if rms < 1e-6:
            rms = 1e-6

        # Update noise floor estimate when input is quiet
        if rms < self._noise_floor * 1.5:
            self._noise_floor = self._alpha_noise * self._noise_floor + (1.0 - self._alpha_noise) * rms
        else:
            self._noise_floor = 0.999 * self._noise_floor + 0.001 * rms

        self._noise_floor = max(self._noise_floor, self.min_noise)

        ratio = rms / self._noise_floor

        # Map the SNR ratio to a 0..1 speech probability
        if ratio <= 1.5:
            prob = 0.0
        elif ratio >= 4.0:
            prob = 1.0
        else:
            prob = (ratio - 1.5) / 2.5

        return prob


class SileroVAD:
    """Genuine Silero VAD running on onnxruntime, with energy-VAD fallback.

    Construction never raises: if the ONNX model file is missing, or
    onnxruntime / the model fails to load, the instance transparently delegates
    to :class:`EnergyVAD`.  Inspect ``.backend`` ("onnx" or "energy") to know
    which path is active.

    Interface is a drop-in for the previous energy detector:
        ``process(window_f32) -> float`` and ``reset()``.
    """

    def __init__(self, sample_rate: int = 16000, model_path: str = None):
        self.sample_rate = int(sample_rate)
        self.backend = "energy"
        self._session = None
        self._input_names = None
        self._energy = EnergyVAD(self.sample_rate)
        self._load_onnx(model_path)
        self.reset()

    # ── model location & load ──

    @staticmethod
    def default_model_path() -> str:
        return os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "models", SILERO_VAD_MODEL_FILENAME
        )

    def _resolve_model_path(self, model_path: str) -> str:
        if model_path:
            return model_path
        env = os.environ.get("SILERO_VAD_MODEL_PATH")
        if env:
            return env
        return self.default_model_path()

    def _load_onnx(self, model_path: str):
        path = self._resolve_model_path(model_path)
        if not path or not os.path.isfile(path):
            # No bundled model → stay on energy backend.  Never fetch at start.
            return
        try:
            import onnxruntime as ort
            so = ort.SessionOptions()
            so.inter_op_num_threads = 1
            so.intra_op_num_threads = 1
            so.log_severity_level = 4  # suppress onnxruntime warnings
            self._session = ort.InferenceSession(
                path, sess_options=so, providers=["CPUExecutionProvider"]
            )
            self._input_names = [i.name for i in self._session.get_inputs()]
            self.backend = "onnx"
        except Exception:
            self._session = None
            self._input_names = None
            self.backend = "energy"

    # ── runtime ──

    def reset(self):
        self._energy.reset()
        if self.backend == "onnx":
            names = self._input_names or []
            if "state" in names:  # Silero v5 (unified state tensor)
                self._state = np.zeros((2, 1, 128), dtype=np.float32)
            else:                 # Silero v4 (separate h/c tensors)
                self._h = np.zeros((2, 1, 64), dtype=np.float32)
                self._c = np.zeros((2, 1, 64), dtype=np.float32)
            self._sr = np.array(self.sample_rate, dtype=np.int64)

    def process(self, window_f32: np.ndarray) -> float:
        if len(window_f32) != VAD_FRAME_SAMPLES:
            return 0.0
        if self.backend != "onnx" or self._session is None:
            return self._energy.process(window_f32)
        try:
            x = np.asarray(window_f32, dtype=np.float32).reshape(1, -1)
            names = self._input_names
            if "state" in names:  # v5
                out, self._state = self._session.run(
                    None, {"input": x, "state": self._state, "sr": self._sr}
                )
            else:                 # v4
                out, self._h, self._c = self._session.run(
                    None, {"input": x, "sr": self._sr, "h": self._h, "c": self._c}
                )
            return float(np.asarray(out).reshape(-1)[0])
        except Exception:
            # Any runtime failure → degrade to energy permanently for this run.
            self.backend = "energy"
            self._session = None
            return self._energy.process(window_f32)


class VadGateWorker(QObject):
    """Silero VAD utterance batcher.

    State machine:
        IDLE ──(speech)──> SPEAKING
        SPEAKING ──(silence >= VAD_SILENCE_MS)──> EMIT (natural endpoint)
        SPEAKING ──(duration >= VAD_MAX_UTTERANCE_MS)──> EMIT (force flush)
        EMIT ──> IDLE (natural) | SPEAKING (force flush)

    Emits ``near_end_of_speech(bool)`` so the assistant can speculatively start
    answering: True when the speaker pauses / a natural endpoint occurs, False
    when speech resumes or an utterance is force-flushed mid-sentence.
    """

    utterance_ready = Signal(bytes)    # Complete WAV bytes for one utterance
    transcript_updated = Signal(str)   # Rolling display text
    near_end_of_speech = Signal(bool)  # True = speaker pausing / natural end
    debug_log = Signal(str)

    # Tuning knobs (sourced from styles.py — no magic numbers)
    SPEECH_THRESHOLD = VAD_SPEECH_THRESHOLD
    TRAILING_SILENCE_MS = VAD_SILENCE_MS
    MIN_UTTERANCE_S = VAD_MIN_UTTERANCE_MS / 1000.0
    MAX_UTTERANCE_S = VAD_MAX_UTTERANCE_MS / 1000.0
    SAMPLE_RATE = 16000
    VAD_WINDOW = VAD_FRAME_SAMPLES

    def __init__(self):
        super().__init__()
        self._vad = None
        self._state = "IDLE"  # IDLE | SPEAKING
        self._utterance_chunks = []       # list of float32 arrays
        self._utterance_start_time = 0.0
        self._trailing_silence_samples = 0
        self._speech_samples = 0          # samples classified as speech in this utterance
        self._near_end_latched = False
        self._finalized_segments = []     # list of transcribed text strings
        self._lock = threading.Lock()
        self._stop = False

    def stop(self):
        self._stop = True

    def _log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        full = f"[VAD {ts}] {msg}"
        try:
            print(full, flush=True)
        except UnicodeEncodeError:
            print(full.encode("ascii", errors="replace").decode(), flush=True)
        try:
            self.debug_log.emit(full)
        except RuntimeError:
            pass

    def _ensure_vad(self):
        """Lazily initialise Silero VAD (ONNX) with energy fallback."""
        if self._vad is not None:
            return True
        try:
            self._vad = SileroVAD(self.SAMPLE_RATE)
            if getattr(self._vad, "backend", "energy") == "onnx":
                self._log("Silero VAD (ONNX) loaded successfully")
            else:
                self._log(
                    "WARNING: Silero ONNX model unavailable — "
                    "using adaptive energy VAD fallback"
                )
            return True
        except Exception as e:
            self._log(f"Failed to load Silero VAD: {e}; trying energy fallback")
            try:
                self._vad = EnergyVAD(self.SAMPLE_RATE)
                return True
            except Exception as e2:
                self._log(f"Energy VAD also failed: {e2}")
                return False

    def _set_near_end(self, value: bool):
        """Emit near_end_of_speech only on a state transition."""
        if value != self._near_end_latched:
            self._near_end_latched = value
            self.near_end_of_speech.emit(value)

    @Slot(object)
    def process_chunk(self, audio_chunk):
        """Receive a short 16kHz mono float32 chunk from AudioCaptureWorker."""
        if self._stop:
            return
        if not isinstance(audio_chunk, np.ndarray):
            return
        if not self._ensure_vad():
            return

        chunk = audio_chunk.astype(np.float32)
        window_size = self.VAD_WINDOW
        trailing_threshold = int(self.TRAILING_SILENCE_MS / 1000.0 * self.SAMPLE_RATE)
        near_end_threshold = int(trailing_threshold * VAD_NEAR_END_FRACTION)
        min_speech_samples = int(self.MIN_UTTERANCE_S * self.SAMPLE_RATE)

        # === TEMP VAD DEBUG (remove after diagnosis) ======================
        # Save the first ~12s of audio the VAD actually receives to a WAV so
        # the real waveform can be inspected, and track the per-chunk peak
        # Silero probability + active backend.
        if not getattr(self, "_dbg_done", False):
            buf = getattr(self, "_dbg_buf", None)
            if buf is None:
                buf = self._dbg_buf = []
                self._dbg_n = 0
            buf.append(chunk.copy())
            self._dbg_n += len(chunk)
            if self._dbg_n >= self.SAMPLE_RATE * 12:
                try:
                    audio_all = np.concatenate(buf)
                    path = os.path.join(os.getcwd(), "vad_debug_capture.wav")
                    with open(path, "wb") as f:
                        f.write(self._encode_wav(audio_all))
                    self._log(f"DEBUG: wrote {self._dbg_n} samples -> {path}")
                except Exception as e:
                    self._log(f"DEBUG: WAV dump failed: {e}")
                self._dbg_done = True
                self._dbg_buf = []
        _dbg_max = 0.0
        # === END TEMP VAD DEBUG ===========================================

        offset = 0
        while offset + window_size <= len(chunk):
            window = chunk[offset: offset + window_size]
            offset += window_size

            try:
                prob = self._vad.process(window)
            except Exception:
                prob = 0.0

            if prob > _dbg_max:      # TEMP VAD DEBUG
                _dbg_max = prob      # TEMP VAD DEBUG

            is_speech = prob >= self.SPEECH_THRESHOLD

            if self._state == "IDLE":
                if is_speech:
                    self._state = "SPEAKING"
                    self._utterance_chunks = [window]
                    self._utterance_start_time = time.time()
                    self._trailing_silence_samples = 0
                    self._speech_samples = window_size
                    self._near_end_latched = False
                    self._log("Speech start detected")
                # else: stay idle, discard silence

            elif self._state == "SPEAKING":
                self._utterance_chunks.append(window)

                if is_speech:
                    self._trailing_silence_samples = 0
                    self._speech_samples += window_size
                    # Speaker resumed before endpoint → cancel near-end indication
                    self._set_near_end(False)
                else:
                    self._trailing_silence_samples += window_size
                    # Pre-endpoint "near end of speech" indication for speculation
                    if self._trailing_silence_samples >= near_end_threshold:
                        self._set_near_end(True)

                # Force-flush (too long) — keep timing semantics compatible with tests
                duration = time.time() - self._utterance_start_time
                if duration >= self.MAX_UTTERANCE_S:
                    self._log(f"Force-flush: utterance exceeded {self.MAX_UTTERANCE_S}s")
                    self._emit_utterance(force_flush=True)

                # Natural endpoint via trailing silence
                elif self._trailing_silence_samples >= trailing_threshold:
                    # Noise gate: require enough real speech, else discard as noise.
                    # This stops sub-word / noise fragments from reaching STT, which
                    # is what makes Whisper hallucinate fillers like "you"/"bye".
                    if self._speech_samples >= min_speech_samples:
                        self._emit_utterance(force_flush=False)
                    else:
                        self._log(
                            f"Discarding noise segment "
                            f"({self._speech_samples / self.SAMPLE_RATE:.2f}s speech "
                            f"< {self.MIN_UTTERANCE_S:.2f}s)"
                        )
                        self._state = "IDLE"
                        self._utterance_chunks = []
                        self._trailing_silence_samples = 0
                        self._speech_samples = 0
                        self._set_near_end(False)

        # === TEMP VAD DEBUG (remove after diagnosis) ===
        self._log(
            f"DEBUG chunk peakprob={_dbg_max:.3f} "
            f"backend={getattr(self._vad, 'backend', '?')} gate={self._state}"
        )
        # === END TEMP VAD DEBUG ===

    def _emit_utterance(self, force_flush=False):
        """Concatenate accumulated audio, encode WAV, emit signal, reset."""
        if not self._utterance_chunks:
            self._state = "IDLE"
            return

        audio = np.concatenate(self._utterance_chunks)
        duration = len(audio) / self.SAMPLE_RATE

        # Skip blips (never on a force-flush, which must keep audio flowing)
        if not force_flush and duration < self.MIN_UTTERANCE_S:
            self._log(f"Skipping blip ({duration:.2f}s < {self.MIN_UTTERANCE_S}s)")
            self._state = "IDLE"
            self._utterance_chunks = []
            self._trailing_silence_samples = 0
            self._speech_samples = 0
            self._near_end_latched = False
            return

        # Peak normalize
        peak = np.max(np.abs(audio))
        if peak > 1e-4:
            audio = audio * (0.9 / peak)

        # Encode to 16-bit PCM WAV
        wav_bytes = self._encode_wav(audio)

        if force_flush:
            self._log(f"Force-flush segment — emitting utterance: {duration:.1f}s, {len(wav_bytes)} WAV bytes")
        else:
            self._log(f"Speech end — emitting utterance: {duration:.1f}s, {len(wav_bytes)} WAV bytes")

        # Reset state + signal near-end intent
        if force_flush:
            self._state = "SPEAKING"
            self._utterance_chunks = []
            self._trailing_silence_samples = 0
            self._speech_samples = 0
            self._utterance_start_time = time.time()
            # Mid-sentence flush → speaker is still going
            self._near_end_latched = True   # force a transition so _set_near_end emits False
            self._set_near_end(False)
        else:
            self._state = "IDLE"
            self._utterance_chunks = []
            self._trailing_silence_samples = 0
            self._speech_samples = 0
            # Natural endpoint → speaker reached a boundary
            self._near_end_latched = False  # force a transition so _set_near_end emits True
            self._set_near_end(True)

        # Emit the utterance
        self.utterance_ready.emit(wav_bytes)

        # Update display with listening indicator
        with self._lock:
            display = " ".join(self._finalized_segments).strip()
            if display:
                display += " <font color='#71717a'><i>Listening...</i></font>"
            else:
                display = "<font color='#71717a'><i>Listening...</i></font>"
        self.transcript_updated.emit(display)

    def add_finalized_text(self, text: str):
        """Called externally when STT returns text — update the rolling display."""
        if not text or not text.strip():
            return
        with self._lock:
            self._finalized_segments.append(text.strip())
            # Prune to ~300 words
            total = sum(len(s.split()) for s in self._finalized_segments)
            while total > 300 and len(self._finalized_segments) > 1:
                removed = self._finalized_segments.pop(0)
                total -= len(removed.split())
            display = " ".join(self._finalized_segments).strip()
        self.transcript_updated.emit(display)

    def get_current_transcript(self) -> str:
        """Thread-safe getter for the current transcript text."""
        with self._lock:
            return " ".join(self._finalized_segments).strip()

    def clear(self):
        """Reset all state."""
        with self._lock:
            self._finalized_segments.clear()
        self._utterance_chunks = []
        self._state = "IDLE"
        self._trailing_silence_samples = 0
        self._speech_samples = 0
        self._near_end_latched = False
        if self._vad is not None:
            self._vad.reset()

    @staticmethod
    def _encode_wav(audio_f32: np.ndarray) -> bytes:
        """Encode float32 audio to 16-bit PCM WAV bytes (16kHz mono)."""
        sr = 16000
        pcm = (audio_f32 * 32767).clip(-32768, 32767).astype(np.int16)
        raw = pcm.tobytes()

        buf = io.BytesIO()
        num_samples = len(pcm)
        data_size = num_samples * 2  # 16-bit = 2 bytes per sample

        # RIFF header
        buf.write(b"RIFF")
        buf.write(struct.pack("<I", 36 + data_size))
        buf.write(b"WAVE")

        # fmt chunk
        buf.write(b"fmt ")
        buf.write(struct.pack("<I", 16))       # chunk size
        buf.write(struct.pack("<H", 1))        # PCM
        buf.write(struct.pack("<H", 1))        # mono
        buf.write(struct.pack("<I", sr))       # sample rate
        buf.write(struct.pack("<I", sr * 2))   # byte rate
        buf.write(struct.pack("<H", 2))        # block align
        buf.write(struct.pack("<H", 16))       # bits per sample

        # data chunk
        buf.write(b"data")
        buf.write(struct.pack("<I", data_size))
        buf.write(raw)

        return buf.getvalue()
