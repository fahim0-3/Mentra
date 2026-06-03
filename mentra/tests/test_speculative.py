"""Speculative generation + cancel-and-reissue tests for MeetingAssistantWorker.

Two layers:
  1. Gating (deterministic, `_generate_answer` mocked): proves speculative start
     on near-end-of-speech and reissue when the finalized question differs
     materially from the speculative one.
  2. Generation lifecycle (real `_run_generation`): proves a superseded
     generation emits nothing (single clean answer, no flicker), and a current
     generation emits its answer.
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from mentra.workers.meeting_assistant_worker import MeetingAssistantWorker


# ── Layer 1: gating ──

def test_speculative_then_reissue_on_material_change():
    w = MeetingAssistantWorker(provider=object())
    calls = []

    def fake_gen(q, ctx):
        calls.append(q)
        w._answer_inflight = True   # emulate the real in-flight state

    w._generate_answer = fake_gen
    w.set_near_end_of_speech(True)

    # High-confidence partial question (interrogative opener) → speculative start
    w.analyze("What is a closure")
    assert calls == ["What is a closure"]
    assert w._speculative_question == "What is a closure"

    # Materially different finalization → cancel & reissue
    w.analyze("What is a closure in JavaScript and how does scope work?")
    assert len(calls) == 2
    assert calls[-1] == "What is a closure in JavaScript and how does scope work?"
    assert w._speculative_question is None


def test_matching_finalization_does_not_reissue():
    w = MeetingAssistantWorker(provider=object())
    calls = []

    def fake_gen(q, ctx):
        calls.append(q)
        w._answer_inflight = True

    w._generate_answer = fake_gen
    w.set_near_end_of_speech(True)

    w.analyze("What is a closure in JavaScript")
    assert len(calls) == 1
    # Near-identical finalization (only punctuation added) → no second answer
    w.analyze("What is a closure in JavaScript?")
    assert len(calls) == 1


def test_near_end_bypasses_cooldown():
    w = MeetingAssistantWorker(provider=object())
    calls = []
    w._generate_answer = lambda q, ctx: calls.append(q)

    # Put the cooldown in effect with an unrelated prior question
    w.last_detected_question = "we were discussing the quarterly roadmap today"
    w.last_detection_time = time.time()

    # near-end False → cooldown suppresses a brand-new question
    w.set_near_end_of_speech(False)
    w.analyze("What is dependency injection?")
    assert calls == []

    # near-end True → speculative path bypasses the cooldown
    w.set_near_end_of_speech(True)
    w.analyze("What is dependency injection?")
    assert calls == ["What is dependency injection?"]


# ── Layer 2: generation lifecycle ──

class FakeStreamProvider:
    def __init__(self, tokens):
        self.tokens = list(tokens)
        self.calls = 0

    def answer_stream(self, messages):
        self.calls += 1
        for t in self.tokens:
            yield t


def test_superseded_generation_emits_nothing():
    w = MeetingAssistantWorker(provider=FakeStreamProvider(["a", "b", "c"]))
    answers = []
    w.answer_ready.connect(answers.append)

    w._gen_id = 5                       # a newer generation is current
    w._run_generation(gen=4, question="old", context="ctx")

    assert answers == []                # stale generation never finalizes
    assert w._provider.calls == 0       # and never even streams


def test_current_generation_emits_answer():
    w = MeetingAssistantWorker(provider=FakeStreamProvider(["Hello ", "world"]))
    answers = []
    chunks = []
    w.answer_ready.connect(answers.append)
    w.answer_chunk.connect(chunks.append)

    w._gen_id = 1
    w._run_generation(gen=1, question="q", context="ctx")

    assert answers == ["Hello world"]
    assert chunks[-1] == "Hello world"
    assert w._provider.calls == 1


def test_generate_answer_bumps_generation_id():
    w = MeetingAssistantWorker(provider=FakeStreamProvider([]))
    start = w._gen_id

    w._generate_answer("q1", "c")
    w._generate_answer("q2", "c")

    # Each launch increments the id (the prior generation is thereby cancelled)
    assert w._gen_id == start + 2

    for t in list(w._gen_threads):
        t.join(timeout=2)


if __name__ == "__main__":
    test_speculative_then_reissue_on_material_change()
    test_matching_finalization_does_not_reissue()
    test_near_end_bypasses_cooldown()
    test_superseded_generation_emits_nothing()
    test_current_generation_emits_answer()
    test_generate_answer_bumps_generation_id()
    print("All speculative generation tests passed!")
