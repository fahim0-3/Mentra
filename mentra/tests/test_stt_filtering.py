"""Tests for Whisper hallucination filtering (cloud verbose_json path)."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from mentra.workers.groq_provider import clean_groq_segments, segment_is_speech


def test_keeps_confident_speech_segment():
    data = {
        "text": "ignored top-level",
        "segments": [
            {"text": " What is Java", "no_speech_prob": 0.05, "avg_logprob": -0.2},
        ],
    }
    assert clean_groq_segments(data) == "What is Java"


def test_drops_high_no_speech_segment():
    data = {
        "segments": [
            {"text": " What is Java", "no_speech_prob": 0.05, "avg_logprob": -0.2},
            {"text": " you", "no_speech_prob": 0.95, "avg_logprob": -1.8},
        ],
    }
    assert clean_groq_segments(data) == "What is Java"


def test_drops_low_logprob_segment():
    data = {
        "segments": [
            {"text": " Bye", "no_speech_prob": 0.3, "avg_logprob": -2.5},
        ],
    }
    # Only segment is low-confidence → dropped → empty
    assert clean_groq_segments(data) == ""


def test_whole_result_hallucination_phrase_dropped():
    # Even if it sneaks past confidence, a result that is *only* a filler is dropped
    data = {"segments": [{"text": "you", "no_speech_prob": 0.1, "avg_logprob": -0.3}]}
    assert clean_groq_segments(data) == ""


def test_real_sentence_with_filler_word_kept():
    data = {
        "segments": [
            {"text": "Thank you for explaining closures", "no_speech_prob": 0.1, "avg_logprob": -0.3},
        ],
    }
    # "thank you ..." inside a real sentence must NOT be dropped
    assert clean_groq_segments(data) == "Thank you for explaining closures"


def test_segment_is_speech_thresholds():
    assert segment_is_speech(0.1, -0.2) is True
    assert segment_is_speech(0.9, -0.2) is False     # too much no-speech
    assert segment_is_speech(0.1, -2.0) is False     # too low confidence
    assert segment_is_speech(None, None) is True     # missing metadata → keep


def test_plain_text_fallback():
    data = {"text": "hello world"}
    assert clean_groq_segments(data) == "hello world"


if __name__ == "__main__":
    test_keeps_confident_speech_segment()
    test_drops_high_no_speech_segment()
    test_drops_low_logprob_segment()
    test_whole_result_hallucination_phrase_dropped()
    test_real_sentence_with_filler_word_kept()
    test_segment_is_speech_thresholds()
    test_plain_text_fallback()
    print("All STT filtering tests passed!")
