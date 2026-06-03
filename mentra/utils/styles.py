# Standard Layout Constants
WINDOW_WIDTH = 880
WINDOW_HEIGHT = 760
GRIP = 8
MAX_HISTORY_MESSAGES = 20

# Configuration
HOTKEY = "ctrl+shift+f"
OLLAMA_MODEL = "llama3:latest"
OLLAMA_VISION_MODEL = "llava"

# Color Palette (Zinc/Blue theme)
COLOR_BG = "#09090b"
COLOR_FRAME = "#18181b"
COLOR_INPUT_BG = "#27272a"
COLOR_ACCENT = "#3b82f6"
COLOR_TEXT_MAIN = "#fafafa"
COLOR_TEXT_SUB = "#a1a1aa"

# Common UI Styles
STYLE_ROOT = f"#root{{background:{COLOR_BG};border:1px solid #27272a;border-radius:20px;}}"
STYLE_SCROLLBAR = f"""
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: #3f3f46;
        border-radius: 5px;
        min-height: 40px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {COLOR_ACCENT};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
        background: none;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 0px;
    }}
    QScrollBar::handle:horizontal {{
        background: #3f3f46;
        border-radius: 5px;
        min-width: 40px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {COLOR_ACCENT};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
        background: none;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}
"""

STYLE_INPUT_BAR = f"""
    QFrame {{
        background: {COLOR_INPUT_BG};
        border: 1px solid #3f3f46;
        border-radius: 25px;
    }}
"""

STYLE_LINE_EDIT = f"""
    QLineEdit {{
        background: transparent;
        border: none;
        color: {COLOR_TEXT_MAIN};
        font-size: 16px;
        font-family: 'Segoe UI';
        padding: 5px;
    }}
"""

# Meeting Panel
COLOR_MEETING_OFF = "#71717a"        # Zinc-500
COLOR_MEETING_LISTENING = "#22c55e"  # Green-500
COLOR_MEETING_THINKING = "#f59e0b"   # Amber-500
WHISPER_MODEL = "small"

# Groq Cloud Models
GROQ_STT_MODEL = "whisper-large-v3-turbo"   # turbo STT — fastest accurate transcription on the free tier
GROQ_LLM_MODEL = "llama-3.1-8b-instant"     # fastest first-token answer model for live meetings

# ════════════════════════════════════════════════════════════════════
#  Meeting Mode — latency / endpointing configuration
#  (Every timing/threshold below is a named constant; no magic numbers.)
# ════════════════════════════════════════════════════════════════════

# Audio capture cadence (AudioCaptureWorker emit interval)
AUDIO_CHUNK_MS = 250                # Emit ~250ms chunks (was ~1000ms) for lower latency

# VAD endpointing (VadGateWorker state machine)
# NOTE: these balance latency against accuracy. Trailing silence must be long
# enough to span natural inter-word pauses, otherwise utterances are cut
# mid-phrase and STT receives sub-word fragments (which it hallucinates on).
VAD_SILENCE_MS = 500                # Trailing silence that ends an utterance (spans word pauses)
VAD_MAX_UTTERANCE_MS = 6000         # Force-flush safety cap for long continuous speech
VAD_MIN_UTTERANCE_MS = 300          # Minimum amount of *speech* to accept a segment (noise gate)
VAD_FRAME_SAMPLES = 512             # 32ms @16kHz — Silero VAD's native window
VAD_SPEECH_THRESHOLD = 0.5          # Silero speech-probability threshold
VAD_NEAR_END_FRACTION = 0.5         # Fraction of VAD_SILENCE_MS that signals "near end of speech"

# STT hallucination filtering (drops Whisper's silence-fillers like "you"/"Bye")
STT_NO_SPEECH_PROB_MAX = 0.6        # Drop a segment whose no_speech_prob exceeds this
STT_MIN_AVG_LOGPROB = -1.0          # Drop a segment whose avg_logprob is below this

# Silero VAD ONNX model (bundled locally so meeting start needs no network)
SILERO_VAD_MODEL_FILENAME = "silero_vad.onnx"
# Optional one-time prefetch source (NEVER fetched at meeting start; energy VAD covers the gap)
SILERO_VAD_MODEL_URL = (
    "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
)

# Question detection + answer gating (MeetingAssistantWorker)
QUESTION_COOLDOWN_S = 4             # Min seconds between distinct auto-answers (was 15)
QUESTION_SIMILARITY_THRESHOLD = 0.97   # Near-duplicate suppression (was 0.90); keeps legit follow-ups
SPECULATIVE_CONFIDENCE = 0.8        # Question-confidence to start a speculative answer early
SPECULATIVE_MATCH_THRESHOLD = 0.85  # If finalized vs speculative similarity < this → cancel & reissue

# Local offline STT (faster-whisper)
# WHISPER_MODEL (above) is the CPU default; this is used ONLY when an NVIDIA GPU is present.
WHISPER_GPU_MODEL = "distil-large-v3"   # near-cloud local latency on CUDA, zero cost

