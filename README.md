# Mentra

**An invisible, always-on-top AI desktop assistant for Windows.** Mentra overlays a frameless, screenshot-resistant window that lets you chat with a local language model, get instant help on whatever is on your screen, and receive concise, real-time answers during meetings — all driven by global keyboard shortcuts so it stays out of your way.

> Windows-only. It relies on WASAPI loopback audio, Windows UI Automation, and global hotkeys.

---

## Overview

Mentra is built around three ideas:

- **Low latency** — answers stream token-by-token, and meeting transcription is optimized for fast first responses.
- **Resilience** — a *cloud-with-local-fallback* design: it uses fast cloud inference when online and switches to fully local models when offline, so it keeps working without internet.
- **Discretion** — the window is translucent, always-on-top, and excluded from screen capture by most recorders; the app is operated entirely by keyboard shortcuts.

All heavy work (audio, transcription, model inference) runs on background threads, so the interface never freezes.

## Features

- **Conversational chat** — streams responses from a local large language model served by [Ollama](https://ollama.com) (`llama3.2:3b`). Conversations are saved to a local SQLite database, with a searchable history sidebar that supports inline rename and delete-with-undo.

- **Screen assistance** — on a keyboard shortcut, Mentra reads the content of the foreground window (problem statements, code, documents, messages) and responds directly. For programming tasks it returns complete, ready-to-use code that matches the on-screen signature; for everything else it gives a concise plain-language answer or summary. Your clipboard is preserved.

- **Real-time meeting assistant** — toggled by a shortcut, it captures system audio, detects speech, transcribes it, identifies questions, and streams short, meeting-ready answers live. Transcription and answers use **Groq Cloud** when online for minimal latency, and a **local faster-whisper + Ollama** pipeline when offline. Includes near-duplicate question suppression, a manual re-analyze action, and a daily request quota guard.

## Controls

Mentra is operated through a small set of **global keyboard shortcuts** (toggle visibility, screen assist, copy last answer, start/stop the meeting assistant, and re-analyze).

> The terminal must be run **as Administrator** for the global shortcuts to register.

## How it works

```
System audio ─▶ Audio capture (WASAPI loopback / sounddevice)
                      │
                      ▼
                Voice Activity Detection (adaptive energy VAD by default)
                      │  complete utterance
                      ▼
                Speech-to-text  ──(online)──▶ Groq Whisper (large-v3-turbo)
                      │           ──(offline)─▶ local faster-whisper
                      ▼
                Question detection ─▶ Answer generation ─▶ live UI panel
                                         (Groq Llama online / Ollama offline)
```

A periodic connectivity check switches the provider back to cloud automatically once the network returns.

## Tech stack

Python 3.12 · PyQt5 · Ollama · Groq API · faster-whisper (CTranslate2) · PyAudioWPatch (WASAPI loopback) · sounddevice · numpy / scipy · Windows UI Automation (`uiautomation`, `pywin32`) · SQLite.

## Prerequisites

- **Windows 10/11**
- **Python 3.12** (newer versions may lack prebuilt wheels for some dependencies)
- **[Ollama](https://ollama.com)** installed and running
- *(Optional)* a free **[Groq API key](https://console.groq.com)** for fast cloud meeting transcription and answers
- *(Optional)* an NVIDIA GPU for faster local inference

## Installation

```powershell
git clone https://github.com/fahim0-3/Mentra.git
cd Mentra

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

# Pull the local chat model
ollama pull llama3.2:3b
```

## Run

```powershell
python main.py
```

Run the terminal **as Administrator** so the global keyboard shortcuts can register.

## Configuration

Mentra reads a few **environment variables** (documented in [`.env.example`](.env.example)). Set them in your shell:

```powershell
# Enables fast cloud meeting transcription + answers (optional)
[Environment]::SetEnvironmentVariable("GROQ_API_KEY", "your_key", "User")

# Optional: use the Silero ONNX VAD instead of the default energy VAD
[Environment]::SetEnvironmentVariable("MENTRA_USE_SILERO", "1", "User")
```

Without `GROQ_API_KEY`, the meeting assistant runs **fully offline** — local faster-whisper for transcription and the local Ollama model for answers.

## Project structure

```
Mentra/
├─ main.py                 # Entry point
├─ requirements.txt
├─ pytest.ini
└─ mentra/
   ├─ core/                # chat manager, SQLite database, hotkey bridge
   ├─ workers/             # audio capture, VAD, STT, meeting assistant, screen reader, LLM
   ├─ ui/                  # main window, chat bubbles, history sidebar, components
   ├─ utils/               # styles/config, generated icons, quota guard
   └─ tests/               # pytest suite
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## License

[MIT](LICENSE) © 2026 fahim0-3
