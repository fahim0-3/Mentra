import numpy as np
import threading
import time
import datetime
from PyQt5.QtCore import QObject, pyqtSignal as Signal

from mentra.utils.styles import AUDIO_CHUNK_MS


class AudioCaptureWorker(QObject):
    """Captures system audio via WASAPI loopback and emits chunks for transcription."""

    audio_chunk_ready = Signal(object)  # numpy.ndarray (float32, 16kHz mono)
    error = Signal(str)
    started = Signal()
    stopped = Signal()
    debug_log = Signal(str)  # Debug messages for the UI panel

    TARGET_SR = 16000      # Whisper expects 16kHz
    BUFFER_SECONDS = 60    # Rolling buffer length
    # Seconds between emits — short chunks (default 250ms) for low-latency endpointing
    EMIT_INTERVAL = AUDIO_CHUNK_MS / 1000.0

    def __init__(self, stop_event: threading.Event):
        super().__init__()
        self.stop_event = stop_event

    def _log(self, msg: str):
        """Emit a timestamped debug log message."""
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        full = f"[Audio {ts}] {msg}"
        try:
            print(full, flush=True)
        except UnicodeEncodeError:
            print(full.encode("ascii", errors="replace").decode(), flush=True)
        try:
            self.debug_log.emit(full)
        except RuntimeError:
            pass  # Object may have been deleted

    def run(self):
        """Main capture loop — runs on a QThread."""
        self._log("Audio capture worker starting...")

        # Try PyAudioWPatch (WASAPI loopback) first, fall back to sounddevice
        try:
            import pyaudiowpatch
            self._log("PyAudioWPatch available — trying WASAPI loopback")
            self._capture_with_pyaudiowpatch()
        except ImportError:
            self._log("PyAudioWPatch not installed — falling back to sounddevice")
            self._capture_with_sounddevice()
        except Exception as e:
            self._log(f"PyAudioWPatch capture failed: {e}")
            self._log("Falling back to sounddevice...")
            try:
                self._capture_with_sounddevice()
            except Exception as e2:
                self.error.emit(f"Audio capture failed: {e2}")
                self._log(f"All capture methods failed: {e2}")

    # ══════════════════════════════════════════════════════════════════
    #  Method 1: PyAudioWPatch — Native WASAPI Loopback
    # ══════════════════════════════════════════════════════════════════

    def _capture_with_pyaudiowpatch(self):
        """Capture system audio using PyAudioWPatch WASAPI loopback."""
        import pyaudiowpatch as pyaudio
        from scipy.signal import resample_poly
        from math import gcd

        p = pyaudio.PyAudio()
        stream = None

        try:
            # Find the WASAPI loopback device
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            self._log(f"WASAPI API found (index {wasapi_info['index']})")

            # Find the loopback device for the default output
            default_output_idx = wasapi_info["defaultOutputDevice"]
            default_output = p.get_device_info_by_index(default_output_idx)
            self._log(f"Default output: {default_output['name']}")

            loopback_device = None
            for i in range(p.get_device_count()):
                dev = p.get_device_info_by_index(i)
                if dev.get("isLoopbackDevice", False):
                    loopback_device = dev
                    self._log(
                        f"Loopback device found: [{i}] {dev['name']} "
                        f"(channels={dev['maxInputChannels']}, "
                        f"sr={dev['defaultSampleRate']})"
                    )
                    break

            if loopback_device is None:
                raise RuntimeError("No WASAPI loopback device found")

            device_sr = int(loopback_device["defaultSampleRate"])
            channels = int(loopback_device["maxInputChannels"])
            device_index = int(loopback_device["index"])

            self._log(f"Using device: {loopback_device['name']}")
            self._log(f"  Sample rate: {device_sr} Hz")
            self._log(f"  Channels: {channels}")
            self._log(f"  Loopback: True")

            # Pre-compute resampling ratio
            if device_sr != self.TARGET_SR:
                g = gcd(self.TARGET_SR, device_sr)
                up = self.TARGET_SR // g
                down = device_sr // g
                needs_resample = True
                self._log(f"  Resampling: {device_sr} -> {self.TARGET_SR} Hz (up={up}, down={down})")
            else:
                up, down = 1, 1
                needs_resample = False

            # List to accumulate non-overlapping chunks in target sample rate
            current_chunks = []
            current_chunks_lock = threading.Lock()
            chunk_count = 0

            # Open the WASAPI loopback stream
            frames_per_buffer = int(device_sr * 0.1)  # 100ms blocks for ultra-low latency
            stream = p.open(
                format=pyaudio.paFloat32,
                channels=channels,
                rate=device_sr,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=frames_per_buffer,
            )
            self._log(f"WASAPI loopback stream opened (block={frames_per_buffer} frames)")
            self.started.emit()

            # Read loop
            last_emit = time.time()
            last_level_log = time.time()

            while not self.stop_event.is_set():
                try:
                    # Read raw audio data
                    raw_data = stream.read(frames_per_buffer, exception_on_overflow=False)
                    if not raw_data:
                        time.sleep(0.01)
                        continue
                    audio = np.frombuffer(raw_data, dtype=np.float32)

                    # Convert to mono by averaging channels
                    if channels > 1:
                        audio = np.mean(audio.reshape(-1, channels), axis=1).astype(np.float32)

                    # Resample to 16kHz
                    if needs_resample:
                        audio = resample_poly(audio, up, down).astype(np.float32)

                    n = len(audio)
                    if n > 0:
                        chunk_count += 1
                        with current_chunks_lock:
                            current_chunks.append(audio)

                        # Log audio levels periodically (every 5 seconds)
                        now = time.time()
                        if now - last_level_log >= 5.0:
                            rms = float(np.sqrt(np.mean(audio ** 2)))
                            peak = float(np.max(np.abs(audio)))
                            self._log(
                                f"Capture Chunk #{chunk_count}: {n} samples, "
                                f"RMS={rms:.6f}, Peak={peak:.6f}"
                            )
                            last_level_log = now

                    # Emit audio chunk at interval
                    now = time.time()
                    if now - last_emit >= self.EMIT_INTERVAL:
                        with current_chunks_lock:
                            if current_chunks:
                                chunk = np.concatenate(current_chunks)
                                current_chunks = []
                            else:
                                chunk = None

                        if chunk is not None and len(chunk) > self.TARGET_SR * 0.2:
                            chunk_rms = float(np.sqrt(np.mean(chunk ** 2)))
                            self._log(
                                f"Emitting chunk: {len(chunk)} samples "
                                f"({len(chunk)/self.TARGET_SR:.1f}s), RMS={chunk_rms:.6f}"
                            )
                            self.audio_chunk_ready.emit(chunk)
                        last_emit = now

                except IOError as e:
                    self._log(f"Stream read error (recoverable): {e}")
                    time.sleep(0.05)

        except Exception as e:
            self.error.emit(f"Audio capture error: {e}")
            self._log(f"WASAPI loopback error: {e}")
            raise  # Re-raise so the caller can try the fallback
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            p.terminate()
            self._log("WASAPI loopback stream closed")
            self.stopped.emit()

    # ══════════════════════════════════════════════════════════════════
    #  Method 2: Sounddevice Fallback (Stereo Mix / Default Input)
    # ══════════════════════════════════════════════════════════════════

    def _capture_with_sounddevice(self):
        """Fallback: capture audio using sounddevice (Stereo Mix or mic)."""
        try:
            import sounddevice as sd
            from scipy.signal import resample_poly
            from math import gcd
        except ImportError as e:
            self.error.emit(f"Missing dependency: {e}. Install 'sounddevice' and 'scipy'.")
            return

        stream = None
        try:
            # Find a suitable input device
            device_info = self._find_system_audio_device(sd)
            if device_info is None:
                self.error.emit(
                    "No audio capture device found. "
                    "Enable 'Stereo Mix' in Windows Sound settings or install PyAudioWPatch."
                )
                self._log("ERROR: No audio device found for capture")
                return

            device_index = device_info["index"]
            device_sr = int(device_info["default_samplerate"])
            channels = min(int(device_info["max_input_channels"]), 2)

            self._log(f"Sounddevice fallback — using: {device_info['name']}")
            self._log(f"  Index: {device_index}, SR: {device_sr}, Channels: {channels}")

            if channels < 1:
                self.error.emit("Audio device has no input channels.")
                return

            # Pre-compute resampling ratio
            if device_sr != self.TARGET_SR:
                g = gcd(self.TARGET_SR, device_sr)
                up = self.TARGET_SR // g
                down = device_sr // g
                needs_resample = True
                self._log(f"  Resampling: {device_sr} -> {self.TARGET_SR} Hz")
            else:
                up, down = 1, 1
                needs_resample = False

            # List to accumulate non-overlapping chunks in target sample rate
            current_chunks = []
            current_chunks_lock = threading.Lock()
            chunk_count = 0
            last_level_log = time.time()

            def audio_callback(indata, frames, time_info, status):
                nonlocal chunk_count, last_level_log
                if status:
                    pass  # Minor xruns are normal

                if channels > 1:
                    audio = np.mean(indata, axis=1).astype(np.float32)
                else:
                    audio = indata.flatten().astype(np.float32)

                if needs_resample:
                    audio = resample_poly(audio, up, down).astype(np.float32)

                n = len(audio)
                if n > 0:
                    chunk_count += 1
                    with current_chunks_lock:
                        current_chunks.append(audio)

                    # Log periodically
                    now = time.time()
                    if now - last_level_log >= 5.0:
                        rms = float(np.sqrt(np.mean(audio ** 2)))
                        self._log(f"SD Chunk #{chunk_count}: {n} samples, RMS={rms:.6f}")
                        last_level_log = now

            # Open the stream
            stream = sd.InputStream(
                device=device_index,
                samplerate=device_sr,
                channels=channels,
                dtype="float32",
                blocksize=int(device_sr * 0.1),  # 100ms blocks for ultra-low latency
                callback=audio_callback,
            )
            stream.start()
            self._log("Sounddevice stream started")
            self.started.emit()

            # Emit loop
            last_emit = time.time()
            while not self.stop_event.is_set():
                time.sleep(0.05)
                now = time.time()
                if now - last_emit >= self.EMIT_INTERVAL:
                    with current_chunks_lock:
                        if current_chunks:
                            chunk = np.concatenate(current_chunks)
                            current_chunks = []
                        else:
                            chunk = None
                    if chunk is not None and len(chunk) > self.TARGET_SR * 0.2:
                        chunk_rms = float(np.sqrt(np.mean(chunk ** 2)))
                        self._log(
                            f"Emitting chunk: {len(chunk)} samples "
                            f"({len(chunk)/self.TARGET_SR:.1f}s), RMS={chunk_rms:.6f}"
                        )
                        self.audio_chunk_ready.emit(chunk)
                    last_emit = now

        except Exception as e:
            self.error.emit(f"Audio capture error: {e}")
            self._log(f"Sounddevice error: {e}")
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
            self._log("Sounddevice stream closed")
            self.stopped.emit()

    @staticmethod
    def _find_system_audio_device(sd):
        """Find the best system audio capture device (Stereo Mix preferred)."""
        try:
            devices = sd.query_devices()
            host_apis = sd.query_hostapis()

            # Priority 1: Stereo Mix (any host API)
            for i, dev in enumerate(devices):
                name_lower = dev["name"].lower()
                if "stereo mix" in name_lower and dev["max_input_channels"] > 0:
                    return {**dev, "index": i}

            # Priority 2: Anything with "loopback" in name
            for i, dev in enumerate(devices):
                name_lower = dev["name"].lower()
                if "loopback" in name_lower and dev["max_input_channels"] > 0:
                    return {**dev, "index": i}

            # Priority 3: WASAPI input that looks like output device
            wasapi_index = None
            for idx, api in enumerate(host_apis):
                if "wasapi" in api["name"].lower():
                    wasapi_index = idx
                    break

            if wasapi_index is not None:
                for i, dev in enumerate(devices):
                    if dev["hostapi"] == wasapi_index and dev["max_input_channels"] > 0:
                        name_lower = dev["name"].lower()
                        if any(k in name_lower for k in ["speakers", "headphone", "output"]):
                            return {**dev, "index": i}

            # Priority 4: Default input device (microphone — last resort)
            default = sd.query_devices(kind="input")
            if default and default["max_input_channels"] > 0:
                default_idx = sd.default.device[0]
                return {**default, "index": default_idx}

        except Exception:
            pass

        return None
