"""Groq and Local provider backends for meeting-mode STT and LLM."""

import io
import json
import math
import os
import struct
import time
import datetime
import threading
import urllib.error
import urllib.request
import http.client
import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal as Signal, pyqtSlot as Slot

from mentra.utils.styles import (
    GROQ_STT_MODEL,
    GROQ_LLM_MODEL,
    OLLAMA_MODEL,
    STT_NO_SPEECH_PROB_MAX,
    STT_MIN_AVG_LOGPROB,
)


# ═══════════════════════════════════════════════════════════════════
#  Whisper hallucination filtering (shared by cloud + local paths)
# ═══════════════════════════════════════════════════════════════════

# Whisper emits these fillers on silence / sub-word audio. We drop them only
# when they are the *entire* low-context result, never inside a real sentence.
_HALLUCINATION_PHRASES = {
    "you", "bye", "bye.", "thank you", "thank you.", "thanks for watching",
    "thanks for watching!", "thank you for watching", "please subscribe",
    ".", "..", "...", "okay", "ok",
}


def _normalize_phrase(text: str) -> str:
    return "".join(c for c in text.lower() if c.isalnum() or c.isspace()).strip()


def segment_is_speech(no_speech_prob: float, avg_logprob: float) -> bool:
    """True if a Whisper segment looks like real speech, not a silence hallucination."""
    if no_speech_prob is not None and no_speech_prob > STT_NO_SPEECH_PROB_MAX:
        return False
    if avg_logprob is not None and avg_logprob < STT_MIN_AVG_LOGPROB:
        return False
    return True


def clean_groq_segments(data: dict) -> str:
    """Filter a Groq verbose_json transcription into trustworthy text."""
    segments = data.get("segments") if isinstance(data, dict) else None
    if not segments:
        text = (data.get("text", "") if isinstance(data, dict) else "").strip()
    else:
        kept = []
        for seg in segments:
            if segment_is_speech(
                seg.get("no_speech_prob"), seg.get("avg_logprob")
            ):
                t = (seg.get("text") or "").strip()
                if t:
                    kept.append(t)
        text = " ".join(kept).strip()

    # Backstop: drop a result that is *only* a known hallucination filler
    if _normalize_phrase(text) in _HALLUCINATION_PHRASES:
        return ""
    return text



# ═══════════════════════════════════════════════════════════════════
#  Provider Interface
# ═══════════════════════════════════════════════════════════════════

class GroqProvider:
    """Cloud provider — calls Groq's OpenAI-compatible REST API using persistent HTTPS connection reuse."""

    BASE = "https://api.groq.com/openai/v1"
    MAX_RETRIES = 2

    def __init__(self):
        self._key = os.environ.get("GROQ_API_KEY", "")
        self._conn = None
        self._lock = threading.Lock()

    def _get_connection(self) -> http.client.HTTPSConnection:
        """Get or initialize the persistent HTTPS Connection."""
        with self._lock:
            if self._conn is None:
                self._conn = http.client.HTTPSConnection("api.groq.com", timeout=30)
            return self._conn

    def _close_connection(self):
        """Close and reset the persistent connection."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    # ── availability ──

    def is_available(self) -> bool:
        """Quick check: key present and endpoint reachable."""
        if not self._key:
            return False
        try:
            conn = self._get_connection()
            conn.request("GET", "/openai/v1/models", headers={"Authorization": f"Bearer {self._key}"})
            resp = conn.getresponse()
            resp.read()  # read and discard
            return resp.status == 200
        except Exception:
            self._close_connection()
            return False

    # ── STT ──

    def transcribe(self, wav_bytes: bytes) -> str:
        """Send WAV bytes to Groq Whisper. Returns filtered plain text.

        Uses verbose_json so per-segment no_speech_prob / avg_logprob are
        available, then drops silence-hallucination segments before returning.
        """
        boundary = "----GroqBoundary" + str(int(time.time() * 1000))
        body = bytearray()

        # model field
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="model"\r\n\r\n'
        body += GROQ_STT_MODEL.encode() + b"\r\n"

        # response_format field — verbose_json exposes confidence metadata
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="response_format"\r\n\r\n'
        body += b"verbose_json\r\n"

        # language field
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="language"\r\n\r\n'
        body += b"en\r\n"

        # file field
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="file"; filename="utterance.wav"\r\n'
        body += b"Content-Type: audio/wav\r\n\r\n"
        body += wav_bytes + b"\r\n"

        body += f"--{boundary}--\r\n".encode()

        path = "/openai/v1/audio/transcriptions"
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }

        resp_bytes = self._request_with_retry("POST", path, bytes(body), headers)
        raw = resp_bytes.decode("utf-8", errors="replace").strip()
        try:
            return clean_groq_segments(json.loads(raw))
        except (json.JSONDecodeError, ValueError):
            # If the API ever returns plain text, fall back to the raw string
            return raw

    # ── LLM ──

    def answer_stream(self, messages: list):
        """Yield text deltas from Groq Llama 3.3 70B (streamed)."""
        payload = json.dumps({
            "model": GROQ_LLM_MODEL,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 512,
            "stream": True,
        }).encode()

        path = "/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                conn = self._get_connection()
                conn.request("POST", path, payload, headers)
                resp = conn.getresponse()

                if resp.status == 429:
                    retry_after = int(resp.getheader("Retry-After", 2))
                    retry_after = min(retry_after, 10)
                    resp.read()
                    if attempt < self.MAX_RETRIES:
                        time.sleep(retry_after)
                        continue
                    raise urllib.error.HTTPError(
                        f"https://api.groq.com{path}", 429, "Too Many Requests", resp.headers, None
                    )

                if resp.status != 200:
                    err_msg = resp.read().decode("utf-8", errors="replace")
                    raise urllib.error.HTTPError(
                        f"https://api.groq.com{path}", resp.status, err_msg, resp.headers, None
                    )

                try:
                    while True:
                        line_bytes = resp.readline()
                        if not line_bytes:
                            break
                        line = line_bytes.decode("utf-8", errors="replace").strip()
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if delta:
                                yield delta
                        except json.JSONDecodeError:
                            continue
                finally:
                    resp.read()

                return

            except (http.client.HTTPException, IOError, OSError):
                self._close_connection()
                if attempt == self.MAX_RETRIES:
                    raise
                time.sleep(0.5)

    # ── request retry helper ──

    def _request_with_retry(self, method: str, path: str, body: bytes, headers: dict) -> bytes:
        """Execute request on the persistent connection, retrying on 429 or network errors."""
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                conn = self._get_connection()
                conn.request(method, path, body, headers)
                resp = conn.getresponse()

                if resp.status == 429:
                    retry_after = int(resp.getheader("Retry-After", 2))
                    retry_after = min(retry_after, 10)
                    resp.read()
                    if attempt < self.MAX_RETRIES:
                        time.sleep(retry_after)
                        continue
                    raise urllib.error.HTTPError(
                        f"https://api.groq.com{path}", 429, "Too Many Requests", resp.headers, None
                    )

                if resp.status != 200:
                    err_msg = resp.read().decode("utf-8", errors="replace")
                    raise urllib.error.HTTPError(
                        f"https://api.groq.com{path}", resp.status, err_msg, resp.headers, None
                    )

                return resp.read()

            except (http.client.HTTPException, IOError, OSError):
                self._close_connection()
                if attempt == self.MAX_RETRIES:
                    raise
                time.sleep(0.5)



class LocalProvider:
    """Offline fallback — uses local faster-whisper subprocess + Ollama."""

    def __init__(self):
        self._whisper_proc = None
        self._whisper_lock = threading.Lock()

    def is_available(self) -> bool:
        return True

    def transcribe(self, wav_bytes: bytes) -> str:
        """Transcribe WAV bytes using the local faster-whisper subprocess."""
        import subprocess, sys

        # Decode WAV to raw float32
        audio = self._wav_to_float32(wav_bytes)
        if audio is None or len(audio) < 1600:
            return ""

        with self._whisper_lock:
            if self._whisper_proc is None or self._whisper_proc.poll() is not None:
                service_script = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "whisper_service.py"
                )
                from mentra.utils.styles import WHISPER_MODEL, WHISPER_GPU_MODEL
                # argv[2] (GPU model) is used by the service ONLY when CUDA is
                # present; otherwise it stays on the CPU model. No GPU required.
                self._whisper_proc = subprocess.Popen(
                    [sys.executable, "-u", service_script, WHISPER_MODEL, WHISPER_GPU_MODEL],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=False,
                )
                # Wait for model loaded
                while True:
                    line = self._whisper_proc.stdout.readline()
                    if not line:
                        break
                    data = json.loads(line.decode("utf-8"))
                    if data.get("status") == "loaded":
                        break
                    if data.get("status") == "error":
                        return ""

            # Send audio
            try:
                self._whisper_proc.stdin.write(np.uint32(len(audio)).tobytes())
                self._whisper_proc.stdin.write(audio.tobytes())
                self._whisper_proc.stdin.flush()
            except Exception:
                return ""

            # Read result
            while True:
                line = self._whisper_proc.stdout.readline()
                if not line:
                    return ""
                data = json.loads(line.decode("utf-8"))
                if data.get("status") == "result":
                    segments = data.get("segments", [])
                    kept = []
                    for s in segments:
                        # whisper_service reports confidence = exp(avg_logprob)
                        conf = s.get("confidence")
                        avg_logprob = math.log(conf) if conf and conf > 0 else None
                        if segment_is_speech(s.get("no_speech_prob"), avg_logprob):
                            t = (s.get("text") or "").strip()
                            if t:
                                kept.append(t)
                    text = " ".join(kept).strip()
                    return "" if _normalize_phrase(text) in _HALLUCINATION_PHRASES else text
                if data.get("status") == "error":
                    return ""

    def answer_stream(self, messages: list):
        """Yield text deltas from local Ollama."""
        import ollama
        client = ollama.Client()
        for chunk in client.chat(
            model=OLLAMA_MODEL,
            messages=messages,
            stream=True,
            options={"temperature": 0.3},
            keep_alive="15m",
        ):
            delta = chunk.get("message", {}).get("content", "")
            if delta:
                yield delta

    def stop(self):
        """Clean up the local whisper subprocess."""
        with self._whisper_lock:
            if self._whisper_proc and self._whisper_proc.poll() is None:
                try:
                    self._whisper_proc.terminate()
                    self._whisper_proc.wait(timeout=2)
                except Exception:
                    try:
                        self._whisper_proc.kill()
                    except Exception:
                        pass
                self._whisper_proc = None

    @staticmethod
    def _wav_to_float32(wav_bytes: bytes):
        """Parse a 16-bit PCM WAV from bytes into float32 numpy array."""
        try:
            buf = io.BytesIO(wav_bytes)
            # Skip RIFF header (44 bytes for standard WAV)
            buf.read(4)  # "RIFF"
            buf.read(4)  # file size
            buf.read(4)  # "WAVE"
            # Find "data" chunk
            while True:
                chunk_id = buf.read(4)
                if len(chunk_id) < 4:
                    return None
                chunk_size = struct.unpack("<I", buf.read(4))[0]
                if chunk_id == b"data":
                    raw = buf.read(chunk_size)
                    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                    return samples
                else:
                    buf.read(chunk_size)  # skip non-data chunks
        except Exception:
            return None


# ═══════════════════════════════════════════════════════════════════
#  GroqSTTWorker — receives WAV utterances, returns text
# ═══════════════════════════════════════════════════════════════════

class GroqSTTWorker(QObject):
    """Transcribes complete WAV utterances via the active provider."""

    text_ready = Signal(str)           # Finalized transcription text
    debug_log = Signal(str)            # Debug messages
    error = Signal(str)                # Error messages
    quota_exhausted = Signal()         # Daily limit reached

    def __init__(self, provider, quota_guard):
        super().__init__()
        self._provider = provider
        self._guard = quota_guard
        self._stop = False

    def set_provider(self, provider):
        """Hot-swap the provider (e.g. when connectivity changes)."""
        self._provider = provider

    def stop(self):
        self._stop = True

    def _log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        full = f"[STT {ts}] {msg}"
        try:
            print(full, flush=True)
        except UnicodeEncodeError:
            print(full.encode("ascii", errors="replace").decode(), flush=True)
        try:
            self.debug_log.emit(full)
        except RuntimeError:
            pass

    @Slot(bytes)
    def transcribe_utterance(self, wav_bytes):
        """Slot: receives WAV bytes for one utterance, emits text_ready."""
        if self._stop:
            return
        if not wav_bytes or len(wav_bytes) < 100:
            return

        # Quota check
        if not self._guard.allow():
            self._log(f"QUOTA EXHAUSTED — {self._guard.count}/{self._guard.limit} requests today")
            self.quota_exhausted.emit()
            self.error.emit(f"Daily quota reached ({self._guard.limit} requests). Resets tomorrow.")
            return

        self._log(f"Utterance flushed to Groq Cloud | Size: {len(wav_bytes)} bytes | Request #{self._guard.count}/{self._guard.limit}")

        # Warn if near limit (within 200 requests)
        if self._guard.remaining <= 200:
            self.error.emit(f"Warning: Daily Groq quota is almost exhausted ({self._guard.remaining} requests left today).")

        try:
            t0 = time.time()
            text = self._provider.transcribe(wav_bytes)
            elapsed_ms = int((time.time() - t0) * 1000)
            text = text.strip() if text else ""

            if text:
                self._log(f"STT response received in {elapsed_ms}ms | result: \"{text[:100]}\"")
                self.text_ready.emit(text)
            else:
                self._log(f"STT response received in {elapsed_ms}ms | no speech detected")

        except Exception as e:
            self._log(f"STT error: {e}")
            self.error.emit(f"STT error: {e}")

