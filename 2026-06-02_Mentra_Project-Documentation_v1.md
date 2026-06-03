# Mentra — Complete Project Documentation

**Document version:** v1
**Date:** 2026-06-02
**Classification:** CUI (Controlled Unclassified Information)
**Scope:** Full technical reference covering what each component is, how it works, why it exists, and what technologies it uses.

---

## 1. Executive Summary

Mentra is a Windows desktop "invisible AI assistant" built in **Python 3** with the **PyQt5** GUI framework. It overlays a frameless, always-on-top, screenshot-resistant window that provides three core capabilities:

1. **Conversational chat** with a local large language model (LLM) served by **Ollama** (`llama3:latest`), including persistent history.
2. **Screen assistance** — reads the content of whatever foreground window the user is viewing (via Windows UI Automation and clipboard) and answers or solves the visible task on a hotkey.
3. **Real-time meeting assistant** — captures system audio (WASAPI loopback), detects speech with a Voice Activity Detector (VAD), transcribes it (Groq cloud Whisper or local faster-whisper), detects questions, and streams concise answers live.

The design priority is **low latency, resilience (cloud-with-local-fallback), and stealth** (the window resists screen capture). All heavy work runs on background `QThread` workers so the UI thread never blocks.

---

## 2. Technology Stack — What Is Used and Why

| Technology | Role in the project | Why it was chosen |
|---|---|---|
| **Python 3** | Primary language | Rapid development; rich audio/ML ecosystem. |
| **PyQt5** | GUI, threading (`QThread`), signals/slots | Mature desktop toolkit; frameless/translucent/always-on-top windows; thread-safe signal marshalling. |
| **Ollama** (`ollama` client) | Local LLM inference for chat and offline meeting answers | Runs models on-device; no API cost; privacy. |
| **Groq API** (OpenAI-compatible REST) | Cloud STT (`whisper-large-v3-turbo`) and LLM (`llama-3.3-70b-versatile`) | Very low-latency inference for live meetings. |
| **faster-whisper** (CTranslate2) | Local speech-to-text fallback | Offline transcription when cloud is unavailable. |
| **PyAudioWPatch** | WASAPI loopback capture of system audio | Captures what the speakers play (the other party in a call), not just the microphone. |
| **sounddevice** | Audio capture fallback (Stereo Mix / mic) | Works where WASAPI loopback is unavailable. |
| **scipy** | Resampling (`resample_poly`), Wiener noise reduction | Convert device sample rate to 16 kHz; clean audio. |
| **numpy** | Audio buffer math (RMS, normalization, concatenation) | Fast numeric arrays. |
| **onnxruntime** | Declared dependency; gates Whisper VAD filter | Enables VAD inside faster-whisper when DLL-safe. |
| **uiautomation** + **pywin32** (`pythoncom`) | Read foreground window text via Windows UI Automation / COM | Extract on-screen content for the "Assist" feature. |
| **pyautogui** + **pyperclip** | Clipboard-based text extraction (Ctrl+A/Ctrl+C) | Read editors/browsers where UI Automation is insufficient. |
| **keyboard** | Global hotkey registration | Trigger features from any application. |
| **pillow (PIL)** | Generate UI icons in memory as `QPixmap` | No icon files shipped; icons drawn programmatically. |
| **opencv-python** | Declared dependency (vision support) | Present in requirements for image handling. |
| **sqlite3** (standard library) | Persistent chat history database | Zero-config embedded storage. |

The full dependency list lives in [requirements.txt](requirements.txt):
`PyQt5, keyboard, ollama, pillow, pyautogui, opencv-python, numpy, pywin32, uiautomation, pyperclip, faster-whisper, sounddevice, scipy, PyAudioWPatch, onnxruntime`.

---

## 3. Project Structure — What Each File Is

```
D:\Mentra\
├─ main.py                      Primary entry point (High-DPI, SIGINT handling, heartbeat timer)
├─ run.py                       Minimal alternate entry point
├─ requirements.txt             Python dependency manifest
├─ mentra_history.db            SQLite database of chat history (runtime data)
├─ mentra/
│  ├─ core/
│  │  ├─ chat_manager.py        High-level chat CRUD + one-time JSON→SQLite migration
│  │  ├─ database.py            SQLite schema and data-access layer
│  │  └─ hotkeys.py             QObject signal bridge (keyboard thread → UI thread)
│  ├─ workers/
│  │  ├─ audio_capture_worker.py    System-audio capture (WASAPI loopback / sounddevice)
│  │  ├─ vad_gate.py                Energy-based VAD utterance batcher → WAV
│  │  ├─ groq_provider.py           Groq + Local provider backends; STT worker
│  │  ├─ meeting_assistant_worker.py Question detection + answer streaming
│  │  ├─ transcription_worker.py    Local rolling-transcript worker (subprocess Whisper)
│  │  ├─ whisper_service.py         Standalone faster-whisper subprocess (DLL isolation)
│  │  ├─ screen_worker.py           Foreground-window text extraction
│  │  └─ llm_worker.py              Streaming chat worker for Ollama
│  ├─ ui/
│  │  ├─ main_window.py             Central window; wires all workers, hotkeys, layout
│  │  ├─ chat/message_bubble.py     One chat message widget (edit/copy)
│  │  ├─ components/meeting_panel.py Collapsible live meeting display + PulsingDot
│  │  ├─ components/resize_grip.py  8-direction frameless-window resize handles
│  │  ├─ components/snackbar.py     Toast with 5-second undo
│  │  └─ sidebar/                   History list (model/view/delegate/panel/item)
│  ├─ utils/
│  │  ├─ styles.py                  Colors, dimensions, model names, QSS fragments
│  │  ├─ assets.py                  PIL-drawn icons → QPixmap
│  │  └─ quota_guard.py             Thread-safe daily Groq request limiter
│  └─ tests/                        Pytest suite (imports, DLL fix, VAD, quota, service…)
```

---

## 4. Application Lifecycle — How It Starts and Runs

### 4.1 Entry point ([main.py](main.py))
1. Enables High-DPI scaling **before** `QApplication` is created (required on some displays).
2. Creates the `QApplication`.
3. Installs a `SIGINT` handler so Ctrl+C quits gracefully.
4. Instantiates `Mentra` (the main window) and shows it.
5. Starts a 500 ms heartbeat `QTimer` parented to the app, which keeps the Python interpreter responsive to OS signals during the Qt event loop.
6. Enters `app.exec_()`.

[run.py](run.py) is a stripped-down alternative entry point used for quick launches.

### 4.2 Window creation ([mentra/ui/main_window.py](mentra/ui/main_window.py))
- **Window flags:** frameless, always-on-top, tool window.
- **Appearance:** 95% opacity, translucent background, rounded dark theme.
- **Stealth:** on Windows, `SetWindowDisplayAffinity(..., 0x11)` excludes the window from screen capture by many recorders.
- **Workers:** instantiated on demand, moved onto dedicated `QThread`s, and connected via signals/slots.
- **Icons:** generated once at startup by [assets.py](mentra/utils/assets.py).
- **LLM warm-up:** the Ollama client is pre-warmed in a background thread to reduce first-response latency.

---

## 5. Subsystem Detail

### 5.1 Chat and Persistence

**System prompt (verbatim, defined in `main_window.py`):**
```
You are Mentra, an expert AI assistant. Follow these rules:
1. Give direct, accurate answers. No filler or hedging.
2. Keep all responses extremely concise and short.
3. For code questions: provide working code with brief explanation.
4. For factual questions: state facts clearly, cite reasoning.
5. If unsure, say so — never fabricate information.
6. Use markdown formatting when helpful.
7. When assisting with screen/window content, solve the visible problem directly instead of describing it.
8. Do NOT narrate the user's activity. Focus on the solution.
```

**Flow:** the user submits text → it is appended to the session message list → persisted → a `StreamWorker` ([llm_worker.py](mentra/workers/llm_worker.py)) streams the Ollama reply (`temperature=0.3`, `keep_alive="15m"`), emitting `text_updated` every ~150 ms for smooth rendering and a sanitized `finished` payload at the end. Connection errors are translated into friendly messages (for example, "Ollama is not running").

**Persistence layers:**
- [chat_manager.py](mentra/core/chat_manager.py) — derives chat titles from the first user message, performs a one-time migration of any legacy `chat_history.json` into SQLite (backing the JSON up afterward), and exposes save/get/delete/rename.
- [database.py](mentra/core/database.py) — defines two tables, `chats` and `messages` (with a foreign key and `idx_messages_chat_id` index), uses upsert on chat save, and offers `clear_all`. **Note:** `save_chat` deletes and re-inserts all messages for a chat (acceptable for this prototype; would be append-only at scale).

**Sidebar** ([mentra/ui/sidebar/](mentra/ui/sidebar/)): a Model/View/Delegate trio — `ChatHistoryModel` (`QAbstractListModel` bridging the database), `ChatItemDelegate` (custom painting, no per-row widget), and `HistoryPanel` (the container) — with inline rename, hover actions, and a 5-second undo on delete via the `Snackbar`.

### 5.2 Screen Assistance (Ctrl+I)

[screen_worker.py](mentra/workers/screen_worker.py) runs on a worker thread and:
1. Initializes COM (`pythoncom.CoInitialize`) — required for `uiautomation` on a non-main thread.
2. Waits for modifier keys to release (so the Ctrl+I hotkey does not corrupt the clipboard copy).
3. Identifies the foreground control. For browsers/editors it issues Ctrl+A → Ctrl+C and reads the clipboard, **preserving and restoring the user's previous clipboard contents**.
4. Falls back to UI Automation patterns (`ValuePattern`, `TextPattern`, edit/document controls) when the clipboard yields nothing.
5. Builds a solve-the-task prompt (truncated to 40,000 characters) and emits it. The main window then feeds it to the LLM exactly like a normal chat turn.

This embodies system-prompt rules 7 and 8: solve the visible problem, do not narrate it.

### 5.3 Real-Time Meeting Assistant (Ctrl+Shift+M)

This is the most sophisticated pipeline. Signal chain:

```
AudioCaptureWorker ──audio_chunk_ready──▶ VadGateWorker ──utterance_ready (WAV)──▶ GroqSTTWorker
        │                                                                              │
        │                                                                       text_ready
        ▼                                                                              ▼
   (system audio)                                            VadGateWorker.add_finalized_text + MeetingAssistantWorker.analyze
                                                                                       │
                                       question_detected / thinking / answer_chunk / answer_ready
                                                                                       ▼
                                                                                 MeetingPanel (UI)
```

**a) Audio capture** — [audio_capture_worker.py](mentra/workers/audio_capture_worker.py)
- Primary path: **PyAudioWPatch WASAPI loopback** to record system output (the remote speaker).
- Fallback: **sounddevice** preferring "Stereo Mix", then loopback-named devices, then a WASAPI output, then the default mic.
- Converts to mono, resamples to **16 kHz** (Whisper's expected rate) with `resample_poly`, accumulates 100 ms blocks, and emits ~1-second chunks. Logs RMS/peak levels periodically.

**b) Voice Activity Detection** — [vad_gate.py](mentra/workers/vad_gate.py)
- `SileroVAD` is a **pure-Python, adaptive energy-based** detector deliberately substituted for the ONNX Silero model to guarantee zero DLL/compilation issues. It tracks an adaptive noise floor and maps the signal-to-noise ratio to a speech probability.
- `VadGateWorker` runs a state machine (`IDLE → SPEAKING → EMIT`): a 600 ms trailing silence ends an utterance, and a 7-second cap force-flushes long speech. Utterances shorter than 0.5 s are discarded. Output is peak-normalized 16-bit PCM **WAV bytes**, emitted exactly once each.

**c) Transcription + LLM providers** — [groq_provider.py](mentra/workers/groq_provider.py)
- `GroqProvider`: cloud backend using a **persistent HTTPS connection** with retry/back-off on 429s; transcribes via multipart upload and streams chat completions.
- `LocalProvider`: offline backend — spawns the faster-whisper subprocess and streams from Ollama.
- `GroqSTTWorker`: receives WAV utterances, checks the quota guard, transcribes, and emits `text_ready` (or `quota_exhausted`). Providers are **hot-swappable** at runtime.

**d) Question detection + answers** — [meeting_assistant_worker.py](mentra/workers/meeting_assistant_worker.py)
- Detects questions via a question-mark heuristic plus a list of regex patterns (what/why/how/explain/describe/etc.), scanning most-recent sentences first.
- Suppresses noise: normalizes text, ignores exact duplicates, ignores ≥90% similar questions (`difflib`), and enforces a 15-second cooldown. A manual mode (Ctrl+Shift+A) bypasses these.
- Streams an answer constrained to **≤6 sentences, no markdown, no bullets**, suitable for interviews/meetings.

**e) Local STT service** — [whisper_service.py](mentra/workers/whisper_service.py) and [transcription_worker.py](mentra/workers/transcription_worker.py)
- `whisper_service.py` is a standalone subprocess that **mocks `torch`** to avoid `c10.dll` load failures/slow startup, attempts CUDA then falls back to CPU `int8`, and communicates over stdin/stdout using a length-prefixed binary protocol (uint32 sample count + float32 samples → JSON results).
- `transcription_worker.py` is the in-app local-transcription path: it applies Wiener noise reduction, maintains a rolling 15-second active buffer, finalizes phrases on punctuation+silence or sustained silence, prunes to ~300 words, and renders stable vs. in-progress text with HTML styling.

**f) Quota protection** — [quota_guard.py](mentra/utils/quota_guard.py)
- `DailyQuotaGuard(limit=1900)` is a thread-safe counter that auto-resets at midnight; every STT and LLM call must pass `allow()` first, and the UI warns when fewer than 200 requests remain.

**g) Resilience loop** — a 60-second timer in the main window re-checks Groq availability and switches providers back to cloud when connectivity is restored.

### 5.4 Hotkeys and Thread Safety

The `keyboard` library fires callbacks on its own thread. Touching Qt widgets from a non-Qt thread is unsafe, so [hotkeys.py](mentra/core/hotkeys.py) defines `HotkeyBridge`, a `QObject` exposing signals (`signal_toggle`, `signal_assist`, `signal_copy_last`, `signal_meeting_toggle`, `signal_meeting_analyze`). Hotkey callbacks merely emit these signals; Qt marshals them safely onto the UI thread.

| Hotkey | Action |
|---|---|
| `Ctrl+Shift+F` | Toggle window visibility |
| `Ctrl+I` | Read the current screen and answer/solve it |
| `Ctrl+0` | Copy the last AI response to the clipboard |
| `Ctrl+Shift+M` | Start/stop the meeting assistant |
| `Ctrl+Shift+A` | Manually re-analyze the current transcript |

### 5.5 UI Components and Theming
- [main_window.py](mentra/ui/main_window.py) builds the widget tree: a horizontal splitter (history sidebar + content), a stacked dashboard/chat view, and a footer (meeting panel, action chips, input bar).
- [message_bubble.py](mentra/ui/chat/message_bubble.py): role-styled bubbles (user 55% width/accent; AI 70% width/transparent) with copy and edit-and-rerun.
- [meeting_panel.py](mentra/ui/components/meeting_panel.py): collapsible panel with animated `PulsingDot`; three states OFF/LISTENING/THINKING drive color and label.
- [resize_grip.py](mentra/ui/components/resize_grip.py): eight invisible edge/corner grips enabling frameless resize with a 400×300 minimum.
- [styles.py](mentra/utils/styles.py): single source of truth for the Zinc/Blue palette, dimensions (`WINDOW_WIDTH=800`, `WINDOW_HEIGHT=600`), model names, and reusable QSS.

---

## 6. Key Configuration Constants

| Constant | Value | Location |
|---|---|---|
| `OLLAMA_MODEL` | `llama3:latest` | styles.py |
| `OLLAMA_VISION_MODEL` | `llava` | styles.py |
| `GROQ_STT_MODEL` | `whisper-large-v3-turbo` | styles.py |
| `GROQ_LLM_MODEL` | `llama-3.3-70b-versatile` | styles.py |
| `WHISPER_MODEL` (local) | `small` | styles.py |
| Target sample rate | 16,000 Hz | audio_capture_worker.py |
| Trailing silence to end utterance | 600 ms | vad_gate.py |
| Max utterance before force-flush | 7.0 s | vad_gate.py |
| Question cooldown | 15 s | meeting_assistant_worker.py |
| Daily Groq quota | 1900 requests | quota_guard.py |
| `GROQ_API_KEY` | Read from environment | groq_provider.py |

---

## 7. How to Run

1. Install dependencies: `pip install -r requirements.txt`.
2. Install and start **Ollama**, then pull the model: `ollama pull llama3:latest`.
3. (Optional, for low-latency meetings) set the `GROQ_API_KEY` environment variable.
4. Launch: `python main.py`.
5. Use the hotkeys in Section 5.4. The window is intentionally frameless and resists screen capture.

---

## 8. Identified Risks and Recommendations (Challenge)

This documentation reflects the current code. Before treating it as final, three assumptions deserve scrutiny:

- **"Screenshot-proof" is partial, not absolute.** `SetWindowDisplayAffinity` blocks many recorders but not all capture methods (hardware capture cards, some GPU-level grabbers, or photographs). Marketing or compliance claims of true invisibility would be inaccurate.
- **Two entry points exist** ([main.py](main.py) and [run.py](run.py)) with divergent High-DPI handling. This is a maintenance hazard. Recommendation: consolidate to one entry point and delete or clearly demote the other.
- **The database rewrites all messages on every save.** For long chats this is O(n) write amplification and a latency/integrity risk. Recommendation: move to append-only message inserts before scaling.

Two clarifying questions to direct any follow-up work:
1. Is the intended primary transcription path **Groq cloud** (latency-optimized) or **local faster-whisper** (privacy-optimized)? The fallback logic supports both, but the default posture should be an explicit product decision.
2. Should chat history be **encrypted at rest**? `mentra_history.db` currently stores plaintext conversations, which may conflict with CUI handling expectations.

---

## Tone Check

Scored against the "Warm but Authoritative" brand guideline:
- **Authoritative:** Strong. Claims are grounded in the actual source files, with verbatim constants and explicit file references.
- **Warm:** Moderate. The tone is professional and direct; risk callouts are framed as constructive recommendations rather than criticism.
- **Overall:** The document leads with a clear executive summary, uses consistent structure, and challenges three assumptions rather than merely validating the codebase, meeting the requirement to act as a challenger rather than a validator.
