import re
import time
import difflib
import threading
import datetime
from PyQt5.QtCore import QObject, pyqtSignal as Signal, pyqtSlot as Slot

from mentra.utils.styles import (
    QUESTION_COOLDOWN_S,
    QUESTION_SIMILARITY_THRESHOLD,
    SPECULATIVE_CONFIDENCE,
    SPECULATIVE_MATCH_THRESHOLD,
)


class MeetingAssistantWorker(QObject):
    """Analyzes the rolling transcript for questions and generates answers.

    Latency design:
      * Detection runs on **every finalized segment** (called per STT result),
        accumulating into the rolling transcript supplied by the caller.
      * Answer generation runs on a **background thread** so the calling thread
        (and therefore the UI thread) never blocks during streaming.
      * A monotonically increasing generation id lets a new generation cancel an
        in-flight one: the stale stream stops emitting, so the UI shows a single
        clean answer with no flicker.
      * Speculative generation: when a high-confidence question is present AND the
        VAD reports the speaker is near end-of-speech, answering starts early
        (bypassing the cooldown). If the finalized text then differs materially
        from the speculative text, the in-flight answer is cancelled and reissued.
    """

    question_detected = Signal(str)   # The detected question
    answer_chunk = Signal(str)        # Streamed full-text-so-far (replaces in UI)
    answer_ready = Signal(str)        # The full generated answer
    thinking = Signal()               # LLM call started
    error = Signal(str)
    debug_log = Signal(str)

    # Question patterns
    QUESTION_PATTERNS = [
        r'\b(?:what\s+(?:is|are|was|were|do|does|did|would|could|should|can))\b',
        r'\b(?:why\s+(?:is|are|do|does|did|would|could|should|can|was|were))\b',
        r'\b(?:how\s+(?:is|are|do|does|did|would|could|should|can|to|many|much))\b',
        r'\bexplain\b',
        r'\b(?:difference|differences)\s+between\b',
        r'\btell\s+me\s+about\b',
        r'\bdescribe\b',
        r'\b(?:can|could|would)\s+you\s+(?:explain|tell|describe|help)\b',
        r'\bdo\s+you\s+know\b',
        r'\bwhat\'?s\b',
        r'\bhow\'?s\b',
        r'\bwhy\'?s\b',
    ]

    # Tuning knobs (sourced from styles.py — no magic numbers)
    SIMILARITY_THRESHOLD = QUESTION_SIMILARITY_THRESHOLD  # near-duplicate suppression
    COOLDOWN_SECONDS = QUESTION_COOLDOWN_S                # min seconds between auto-answers
    SPECULATIVE_CONFIDENCE = SPECULATIVE_CONFIDENCE        # confidence to speculate early
    SPECULATIVE_MATCH_THRESHOLD = SPECULATIVE_MATCH_THRESHOLD  # spec vs final → reissue
    MIN_TRANSCRIPT_CHARS = 10                              # ignore tiny transcripts

    def __init__(self, provider=None, quota_guard=None):
        super().__init__()
        self._provider = provider
        self._guard = quota_guard
        self.last_detected_question = ""
        self.last_detection_time = 0.0
        self._compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self.QUESTION_PATTERNS]
        self._lock = threading.Lock()
        self._gen_lock = threading.Lock()   # serializes provider streaming across generations
        self._stop = False

        # Speculative / cancellation state
        self._near_end_of_speech = False
        self._answer_inflight = False
        self._speculative_question = None
        self._gen_id = 0
        self._gen_threads = []

    def set_provider(self, provider):
        """Hot-swap the provider (e.g. when connectivity changes)."""
        self._provider = provider

    def stop(self):
        """Signal the worker to stop processing and cancel any in-flight answer."""
        self._stop = True
        with self._lock:
            self._gen_id += 1  # invalidate any running generation
            self._answer_inflight = False

    @Slot(bool)
    def set_near_end_of_speech(self, value):
        """Slot: VadGateWorker reports whether the speaker is near end-of-speech."""
        with self._lock:
            self._near_end_of_speech = bool(value)

    def _log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        full = f"[Assistant {ts}] {msg}"
        try:
            print(full, flush=True)
        except UnicodeEncodeError:
            print(full.encode("ascii", errors="replace").decode(), flush=True)
        try:
            self.debug_log.emit(full)
        except RuntimeError:
            pass

    def _normalize_text(self, text: str) -> str:
        """Normalize text for strict duplicate/similarity checks."""
        if not text:
            return ""
        text = text.lower()
        text = re.sub(r'[^\w\s]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _question_confidence(self, question: str) -> float:
        """Heuristic 0..1 confidence that `question` is a genuine question."""
        s = (question or "").strip()
        if not s:
            return 0.0
        score = 0.0
        if s.endswith("?"):
            score = max(score, 0.95)
        low = s.lower()
        if re.match(
            r'^(what|why|how|when|where|who|which|whose|can|could|would|should|'
            r'do|does|did|is|are|will|explain|describe|tell me|define)\b',
            low,
        ):
            score = max(score, 0.85)
        for pat in self._compiled_patterns:
            if pat.search(s):
                score = max(score, 0.8)
                break
        return score

    @Slot(str)
    def analyze(self, transcript: str):
        """Analyze the rolling transcript for a new question (automatic mode).

        Runs on each finalized segment. Gating order:
          A. in-flight speculative answer is now materially wrong → cancel & reissue
          B. near end-of-speech + high confidence → speculate early (no cooldown)
          C. normal path → near-duplicate suppression + cooldown
        """
        if self._stop:
            return
        if not transcript or len(transcript.strip()) < self.MIN_TRANSCRIPT_CHARS:
            return

        question = self._detect_question(transcript)
        if not question:
            return

        conf = self._question_confidence(question)
        now = time.time()

        launch = False
        speculative = False
        with self._lock:
            norm_new = self._normalize_text(question)
            norm_last = self._normalize_text(self.last_detected_question)

            # Exact duplicate of the last answered question → ignore
            if norm_last and norm_last == norm_new:
                return

            sim = (
                difflib.SequenceMatcher(None, norm_last, norm_new).ratio()
                if norm_last else 0.0
            )

            spec_norm = (
                self._normalize_text(self._speculative_question)
                if self._speculative_question else ""
            )
            spec_sim = (
                difflib.SequenceMatcher(None, spec_norm, norm_new).ratio()
                if spec_norm else 0.0
            )

            # Case A — speculative/in-flight answer exists but the now-complete
            # question differs materially → cancel & reissue immediately.
            if self._answer_inflight and spec_norm and spec_sim < self.SPECULATIVE_MATCH_THRESHOLD:
                launch, speculative = True, False
                self._speculative_question = None

            # Case B — speaker is wrapping up and we already have a high-confidence
            # question → answer speculatively now (bypass cooldown).
            elif (self._near_end_of_speech
                  and conf >= self.SPECULATIVE_CONFIDENCE
                  and sim < self.SIMILARITY_THRESHOLD):
                launch, speculative = True, True

            # Case C — normal path: near-duplicate suppression + cooldown.
            else:
                if norm_last and sim >= self.SIMILARITY_THRESHOLD:
                    return
                if now - self.last_detection_time < self.COOLDOWN_SECONDS:
                    return
                launch, speculative = True, False

            if launch:
                self.last_detected_question = question
                self.last_detection_time = now
                if speculative:
                    self._speculative_question = question

        if launch:
            if speculative:
                self._log(f"Speculative answer (conf={conf:.2f}): \"{question[:80]}\"")
            self._generate_answer(question, transcript)

    @Slot(str)
    def manual_analyze(self, transcript: str):
        """Manual analysis — skips cooldown and deduplication."""
        if not transcript or len(transcript.strip()) < self.MIN_TRANSCRIPT_CHARS:
            self.error.emit("No conversation transcript available yet.")
            return

        question = self._detect_question(transcript)
        if not question:
            sentences = self._split_sentences(transcript)
            question = " ".join(sentences[-3:]) if sentences else transcript[-500:]

        with self._lock:
            self.last_detected_question = question
            self.last_detection_time = time.time()
            self._speculative_question = None

        self._generate_answer(question, transcript)

    def _detect_question(self, transcript: str) -> str:
        """Extract the most recent question from the transcript."""
        sentences = self._split_sentences(transcript)

        # Search from the end (most recent) backwards
        for sentence in reversed(sentences):
            stripped = sentence.strip()
            if not stripped or len(stripped) < 8:
                continue

            if stripped.endswith("?"):
                return stripped

            for pattern in self._compiled_patterns:
                if pattern.search(stripped):
                    return stripped

        return ""

    @staticmethod
    def _split_sentences(text: str) -> list:
        """Split text into sentences."""
        parts = re.split(r'(?<=[.?!])\s+', text.strip())
        return [p.strip() for p in parts if p.strip()]

    # ── answer generation (background, cancellable) ──

    def _generate_answer(self, question: str, context: str):
        """Launch (or relaunch) answer generation on a background thread.

        Bumping the generation id cancels any in-flight generation: the older
        streaming thread sees a stale id and stops emitting, so the UI shows a
        single clean answer with no flicker.
        """
        if self._provider is None:
            self.error.emit("No LLM provider available.")
            return

        with self._lock:
            self._gen_id += 1
            gen = self._gen_id
            self._answer_inflight = True

        t = threading.Thread(
            target=self._run_generation, args=(gen, question, context), daemon=True
        )
        # Drop references to finished threads
        self._gen_threads = [th for th in self._gen_threads if th.is_alive()]
        self._gen_threads.append(t)
        t.start()

    def _finish_gen(self, gen: int):
        """Mark generation finished (only if it is still the current one)."""
        with self._lock:
            if gen == self._gen_id:
                self._answer_inflight = False

    def _run_generation(self, gen: int, question: str, context: str):
        """Stream the answer for `gen`; abort silently if superseded/stopped."""
        try:
            if self._stop or gen != self._gen_id:
                return

            self.question_detected.emit(question)
            self.thinking.emit()

            # Quota check for the LLM call
            if self._guard and not self._guard.allow():
                self._log(f"QUOTA EXHAUSTED for LLM — {self._guard.count}/{self._guard.limit}")
                self.error.emit(
                    f"Daily quota reached ({self._guard.limit} requests). Resets tomorrow."
                )
                return

            self._log(f"Generating answer for: \"{question[:80]}\"")
            if self._guard:
                self._log(f"LLM request #{self._guard.count}/{self._guard.limit}")
                if self._guard.remaining <= 200:
                    self.error.emit(
                        f"Warning: Daily Groq quota is almost exhausted "
                        f"({self._guard.remaining} requests left today)."
                    )

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a real-time meeting assistant. You listen to conversations "
                        "and provide concise, accurate answers to questions that arise. "
                        "Your answers must be direct, factual, and immediately useful. "
                        "Never use markdown formatting, bullet points, or numbered lists. "
                        "Keep answers under 6 sentences."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Conversation Context:\n{context}\n\n"
                        f"Question:\n{question}\n\n"
                        f"Generate a short, accurate answer suitable for interviews, meetings, "
                        f"presentations, and technical discussions.\n"
                        f"Maximum 6 sentences.\n"
                        f"No markdown.\n"
                        f"No bullet points."
                    ),
                },
            ]

            full_answer = ""
            t0 = time.time()

            # Serialize provider streaming so a relaunch cleanly supersedes the
            # previous stream (the old thread releases the lock once it notices
            # the generation id changed).
            with self._gen_lock:
                if self._stop or gen != self._gen_id:
                    return
                for delta in self._provider.answer_stream(messages):
                    if self._stop or gen != self._gen_id:
                        # Cancelled / superseded — stop emitting (no stale chunks)
                        return
                    full_answer += delta
                    self.answer_chunk.emit(full_answer)

            full_answer = full_answer.strip()
            if not self._stop and gen == self._gen_id:
                elapsed = time.time() - t0
                self._log(f"Answer generated ({elapsed:.1f}s): \"{full_answer[:100]}...\"")
                self.answer_ready.emit(full_answer)

        except Exception as e:
            msg = str(e)
            if "10061" in msg or "Connection refused" in msg or "ConnectionError" in msg:
                msg = "LLM provider is not reachable. Check your connection or start Ollama."
            if gen == self._gen_id:
                self._log(f"Answer generation error: {msg}")
                self.error.emit(msg)
        finally:
            self._finish_gen(gen)
