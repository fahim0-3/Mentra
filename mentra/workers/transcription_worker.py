import numpy as np
import time
import datetime
import threading
import subprocess
import sys
import os
import json
from PyQt5.QtCore import QObject, pyqtSignal as Signal, pyqtSlot as Slot

class TranscriptionWorker(QObject):
    """Transcribes audio chunks using a standalone Whisper service to avoid DLL conflicts."""

    transcript_updated = Signal(str)  # Full rolling transcript text (styled with HTML)
    final_transcript_ready = Signal(str)  # Stable finalized text for question detection
    model_loading = Signal()
    model_ready = Signal()
    error = Signal(str)
    debug_log = Signal(str)  # Debug messages for the UI panel

    MAX_TRANSCRIPT_WORDS = 300  # ~60 seconds of speech
    SILENCE_THRESHOLD = 0.01   # RMS below this → skip transcription

    def __init__(self, model_size: str = "base"):
        super().__init__()
        self.model_size = model_size
        self._proc = None
        self._model_loaded = False
        self._loading = False
        self._load_failed = False
        
        # Stateful Rolling Buffer & Transcript Stabilization
        self._active_audio_buffer = []  # List of float32 numpy arrays (chunks) of current active speech
        self._final_transcript_segments = []  # List of finalized segment text strings
        self._partial_text = ""  # In-progress unstable text from transcribing the active buffer
        self._consecutive_silence_chunks = 0
        self._last_stable_text = ""
        
        self._lock = threading.Lock()
        self._chunks_received = 0
        self._chunks_transcribed = 0
        self._chunks_silent = 0

    def _log(self, msg: str):
        """Emit a timestamped debug log message."""
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        full = f"[Whisper {ts}] {msg}"
        try:
            print(full, flush=True)
        except UnicodeEncodeError:
            print(full.encode("ascii", errors="replace").decode(), flush=True)
        try:
            self.debug_log.emit(full)
        except RuntimeError:
            pass

    def _ensure_model(self):
        """Lazily load the Whisper model on first use by starting the subprocess service."""
        if self._model_loaded:
            return True
        if self._loading or self._load_failed:
            return False

        self._loading = True
        self.model_loading.emit()
        self._log("Starting Whisper background service subprocess...")

        try:
            # Find whisper_service.py relative to this file
            service_script = os.path.join(
                os.path.dirname(__file__), "whisper_service.py"
            )
            
            # Start the service subprocess
            self._proc = subprocess.Popen(
                [sys.executable, "-u", service_script, self.model_size],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False
            )
            
            # Start reader threads
            self._stdout_thread = threading.Thread(
                target=self._read_service_stdout,
                daemon=True
            )
            self._stdout_thread.start()
            
            self._stderr_thread = threading.Thread(
                target=self._read_service_stderr,
                daemon=True
            )
            self._stderr_thread.start()
            
            return False  # Still loading, will emit model_ready when JSON loaded arrives

        except Exception as e:
            self.error.emit(f"Failed to start Whisper service: {e}")
            self._loading = False
            self._load_failed = True
            self._log(f"PERMANENT FAILURE starting service: {e}")
            return False

    def _finalize_current_phrase(self):
        """Finalize the current active transcription, clearing active buffer."""
        finalized_text = ""
        full_final = ""
        with self._lock:
            if self._partial_text.strip():
                finalized_text = self._partial_text.strip()
                self._final_transcript_segments.append(finalized_text)
                self._prune_final_segments()
                self._active_audio_buffer.clear()
                self._partial_text = ""
                self._last_stable_text = ""
                self._consecutive_silence_chunks = 0
                full_final = " ".join(self._final_transcript_segments).strip()
                
        if finalized_text:
            self._log(f"FINALIZED: \"{finalized_text}\"")
            self.final_transcript_ready.emit(full_final)
            self.transcript_updated.emit(full_final)

    def _read_service_stdout(self):
        """Read output from the Whisper service."""
        try:
            while self._proc:
                line = self._proc.stdout.readline()
                if not line:
                    break
                
                try:
                    data = json.loads(line.decode('utf-8'))
                except Exception as parse_err:
                    self._log(f"[Service Output Parse Error] {line}: {parse_err}")
                    continue
                
                status = data.get("status")
                if status == "loaded":
                    self._model_loaded = True
                    self._loading = False
                    self.model_ready.emit()
                    self._log("Whisper model loaded successfully on background service.")
                
                elif status == "log":
                    self._log(f"Service: {data.get('message')}")
                    
                elif status == "result":
                    segments = data.get("segments", [])
                    elapsed = data.get("elapsed", 0.0)
                    self._chunks_transcribed += 1
                    
                    new_texts = []
                    confidences = []
                    for seg in segments:
                        text = seg.get("text", "").strip()
                        conf = seg.get("confidence", 0.0)
                        if text:
                            new_texts.append(text)
                            confidences.append(conf)
                            
                    new_partial_text = " ".join(new_texts).strip()
                    avg_conf = np.mean(confidences) if confidences else 0.0
                    
                    if new_partial_text:
                        self._log(f"Whisper output ({elapsed:.1f}s, conf={avg_conf:.2f}): \"{new_partial_text[:80]}{'...' if len(new_partial_text) > 80 else ''}\"")
                    else:
                        self._log(f"No speech detected ({elapsed:.1f}s processing)")
                    
                    can_finalize = False
                    with self._lock:
                        if avg_conf < 0.65 and new_partial_text:
                            self._log(f"Confidence low ({avg_conf:.2f} < 0.65). Delaying finalization & waiting for context.")
                        
                        # Update partial text
                        self._partial_text = new_partial_text
                        
                        # End-of-sentence finalization check (requires high confidence + short pause)
                        ends_with_punctuation = any(self._partial_text.endswith(p) for p in ('.', '?', '!'))
                        if ends_with_punctuation and self._consecutive_silence_chunks >= 1 and avg_conf >= 0.65:
                            can_finalize = True
                            
                    if can_finalize:
                        self._finalize_current_phrase()
                    else:
                        # Check if we should finalize due to silence even if no punctuation
                        finalize_empty = False
                        with self._lock:
                            if self._partial_text.strip() and self._consecutive_silence_chunks >= 2:
                                finalize_empty = True
                        if finalize_empty:
                            self._finalize_current_phrase()
                        else:
                            with self._lock:
                                final_str = " ".join(self._final_transcript_segments).strip()
                                if self._partial_text:
                                    if final_str:
                                        display_text = f"{final_str} <font color='#71717a'><i>{self._partial_text}...</i></font>"
                                    else:
                                        display_text = f"<font color='#71717a'><i>{self._partial_text}...</i></font>"
                                else:
                                    display_text = final_str
                            self.transcript_updated.emit(display_text)
                            
                elif status == "error":
                    msg = data.get("message", "Unknown error")
                    self.error.emit(f"Whisper Service Error: {msg}")
                    self._loading = False
                    self._load_failed = True
                    self._log(f"PERMANENT SERVICE FAILURE: {msg}")
                    break
                    
        except Exception as e:
            self._log(f"Stdout reader thread crash: {e}")

    def _read_service_stderr(self):
        """Read standard error from the Whisper service to prevent pipe blocking and capture debugging info."""
        try:
            while self._proc:
                line = self._proc.stderr.readline()
                if not line:
                    break
                decoded = line.decode('utf-8', errors='replace').strip()
                if decoded:
                    self._log(f"[Service Debug] {decoded}")
        except Exception:
            pass

    @Slot(object)
    def transcribe(self, audio_chunk):
        """Receive an audio chunk (numpy float32 array at 16kHz), filter, accumulate, and send to service."""
        try:
            if not isinstance(audio_chunk, np.ndarray):
                self._log(f"Received non-array chunk: {type(audio_chunk)}")
                return

            self._chunks_received += 1

            # 1. Apply basic Wiener noise reduction
            try:
                from scipy.signal import wiener
                audio_chunk = wiener(audio_chunk).astype(np.float32)
            except Exception:
                pass  # Fallback to unfiltered if scipy.signal.wiener fails
                
            rms = float(np.sqrt(np.mean(audio_chunk ** 2)))
            
            # 2. Track silence
            is_silent = rms < self.SILENCE_THRESHOLD
            if is_silent:
                self._consecutive_silence_chunks += 1
            else:
                self._consecutive_silence_chunks = 0
                
            # 3. Handle silence pause finalization
            if is_silent:
                self._chunks_silent += 1
                finalize_on_pause = False
                with self._lock:
                    if self._partial_text.strip() and self._consecutive_silence_chunks >= 2:
                        finalize_on_pause = True
                if finalize_on_pause:
                    self._finalize_current_phrase()
                return

            # 4. Speech detected: Append to rolling active audio buffer
            with self._lock:
                self._active_audio_buffer.append(audio_chunk)
                
                # Cap the active buffer to 15 seconds to keep latency and memory bounded
                max_samples = 16000 * 15
                total_samples = sum(len(x) for x in self._active_audio_buffer)
                while total_samples > max_samples and self._active_audio_buffer:
                    removed = self._active_audio_buffer.pop(0)
                    total_samples -= len(removed)

            # Ensure model is loaded/started
            if not self._ensure_model():
                self._log("Model not ready -- skipping chunk")
                return

            # 5. Peak Volume Normalization on concatenated active buffer
            with self._lock:
                active_audio = np.concatenate(self._active_audio_buffer)
                
            max_val = np.max(np.abs(active_audio))
            if max_val > 1e-4:
                normalized_audio = active_audio * (0.9 / max_val)
            else:
                normalized_audio = active_audio

            # 6. Write to the service process
            self._log(
                f"Transcribing active buffer #{self._chunks_received}: "
                f"{len(normalized_audio)} samples ({len(normalized_audio)/16000:.1f}s), RMS={rms:.6f}"
            )
            
            try:
                self._proc.stdin.write(np.uint32(len(normalized_audio)).tobytes())
                self._proc.stdin.write(normalized_audio.tobytes())
                self._proc.stdin.flush()
            except Exception as write_err:
                self._log(f"Failed to write audio to service process: {write_err}")
                self.error.emit(f"Service write error: {write_err}")

        except Exception as e:
            self.error.emit(f"Transcription wrapper error: {e}")

    def _prune_final_segments(self):
        """Remove oldest segments to stay within MAX_TRANSCRIPT_WORDS."""
        total_words = sum(len(text.split()) for text in self._final_transcript_segments)
        while total_words > self.MAX_TRANSCRIPT_WORDS and len(self._final_transcript_segments) > 1:
            removed = self._final_transcript_segments.pop(0)
            total_words -= len(removed.split())

    def get_current_transcript(self) -> str:
        """Thread-safe getter for the current plain text transcript."""
        with self._lock:
            final_str = " ".join(self._final_transcript_segments).strip()
            if self._partial_text:
                return (final_str + " " + self._partial_text).strip()
            return final_str

    def clear(self):
        """Clear all active buffers and segments."""
        with self._lock:
            self._active_audio_buffer.clear()
            self._final_transcript_segments.clear()
            self._partial_text = ""
            self._consecutive_silence_chunks = 0
            self._last_stable_text = ""

    def stop_service(self):
        """Stop the background service cleanly."""
        if self._proc:
            self._log("Stopping Whisper background service...")
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
            self._model_loaded = False
            self._loading = False

    def __del__(self):
        self.stop_service()
