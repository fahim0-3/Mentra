"""Segment-immediate STT tests for GroqSTTWorker.

Each finalized VAD segment must be transcribed immediately (one provider call
per segment), and the daily quota must be respected (one unit per segment).
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from mentra.workers.groq_provider import GroqSTTWorker
from mentra.utils.quota_guard import DailyQuotaGuard


class FakeProvider:
    def __init__(self, text="segment text"):
        self.text = text
        self.calls = []

    def transcribe(self, wav_bytes):
        self.calls.append(wav_bytes)
        return self.text


def _segment(n=512):
    # >= 100 bytes so the worker treats it as a real segment
    return b"\x00" * n


def test_each_segment_transcribed_immediately():
    prov = FakeProvider()
    guard = DailyQuotaGuard(limit=100)
    w = GroqSTTWorker(prov, guard)
    results = []
    w.text_ready.connect(results.append)

    w.transcribe_utterance(_segment())
    w.transcribe_utterance(_segment())

    assert len(prov.calls) == 2          # one transcription per segment, immediate
    assert results == ["segment text", "segment text"]
    assert guard.count == 2              # exactly one quota unit per segment


def test_quota_exhaustion_stops_stt():
    prov = FakeProvider()
    guard = DailyQuotaGuard(limit=1)
    w = GroqSTTWorker(prov, guard)
    exhausted = []
    w.quota_exhausted.connect(lambda: exhausted.append(True))

    w.transcribe_utterance(_segment())   # allowed
    w.transcribe_utterance(_segment())   # denied — quota guard blocks it

    assert len(prov.calls) == 1
    assert exhausted == [True]


def test_short_segment_skipped():
    prov = FakeProvider()
    guard = DailyQuotaGuard(limit=100)
    w = GroqSTTWorker(prov, guard)

    w.transcribe_utterance(b"tiny")      # < 100 bytes → not a real segment

    assert prov.calls == []
    assert guard.count == 0              # no wasted quota on fragments


def test_empty_transcription_does_not_emit():
    prov = FakeProvider(text="")
    guard = DailyQuotaGuard(limit=100)
    w = GroqSTTWorker(prov, guard)
    results = []
    w.text_ready.connect(results.append)

    w.transcribe_utterance(_segment())

    assert prov.calls == [b"\x00" * 512]
    assert results == []                 # no speech → no text_ready


if __name__ == "__main__":
    test_each_segment_transcribed_immediately()
    test_quota_exhaustion_stops_stt()
    test_short_segment_skipped()
    test_empty_transcription_does_not_emit()
    print("All segment-immediate STT tests passed!")
