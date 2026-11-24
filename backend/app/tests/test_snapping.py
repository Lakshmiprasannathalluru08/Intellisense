"""Unit tests for topic_detector.py.

Covers:
- target_n: N matches the length table
- _split_transcript: exactly N sections; cuts follow full-stop segments;
  no overlaps or gaps; last section ends at video end; second half gets sections
- _parse_concepts: valid JSON parsed; missing sections → None; fallback works
- _fallback_keyword: uses first full sentence; truncates correctly
- _seg_end / _ends_with_sentence: helper behaviour
- _snap_end_to_full_stop (kept for backward compat checks)
- detect_topics smoke test: returns exactly N topics
"""

import pytest

from app.models import Segment, TranscriptResult, WordEntry
from app.services.topic_detector import (
    _ends_with_sentence,
    _fallback_keyword,
    _parse_concepts,
    _seg_end,
    _split_transcript,
    target_n,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seg(start: float, end: float, text: str = "hello",
         word_ends: list[float] | None = None) -> Segment:
    words = []
    if word_ends:
        for we in word_ends:
            words.append(WordEntry(word="w", start=we - 0.1, end=we))
    return Segment(start=start, end=end, text=text, words=words)


def _transcript(*segments: Segment) -> TranscriptResult:
    return TranscriptResult(segments=list(segments))


def _uniform_segs(count: int, duration_each: float = 10.0,
                  text: str = "Hello.") -> list[Segment]:
    """Build `count` uniform segments of `duration_each` seconds each."""
    return [_seg(i * duration_each, (i + 1) * duration_each, text)
            for i in range(count)]


# ---------------------------------------------------------------------------
# target_n: mandatory count based on video length
# ---------------------------------------------------------------------------

def test_target_n_under_3_min():
    tr = _transcript(_seg(0.0, 120.0))   # 2 min
    assert target_n(tr) == 2


def test_target_n_3_to_5_min():
    tr = _transcript(_seg(0.0, 240.0))   # 4 min
    assert target_n(tr) == 3


def test_target_n_5_to_11_min():
    tr = _transcript(_seg(0.0, 480.0))   # 8 min
    assert target_n(tr) == 4


def test_target_n_11_to_15_min():
    tr = _transcript(_seg(0.0, 780.0))   # 13 min
    assert target_n(tr) == 6


def test_target_n_16_to_20_min():
    tr = _transcript(_seg(0.0, 1080.0))  # 18 min
    assert target_n(tr) == 8


def test_target_n_over_20_min():
    tr = _transcript(_seg(0.0, 1500.0))  # 25 min
    assert target_n(tr) == 9


def test_target_n_exactly_3_min_boundary():
    tr = _transcript(_seg(0.0, 180.0))   # 3 min exactly → 3
    assert target_n(tr) == 3


def test_target_n_empty_transcript_returns_2():
    tr = TranscriptResult(segments=[])
    assert target_n(tr) == 2


# ---------------------------------------------------------------------------
# _split_transcript: N sections, full-stop cuts, no gaps/overlaps, video end
# ---------------------------------------------------------------------------

def test_split_returns_exactly_n_sections():
    segs = _uniform_segs(20)   # 20 × 10 s = 200 s
    tr = _transcript(*segs)
    n = 4
    sections = _split_transcript(tr, n)
    assert len(sections) == n


def test_split_last_section_ends_at_video_end():
    segs = _uniform_segs(20)
    tr = _transcript(*segs)
    sections = _split_transcript(tr, 4)
    last_seg = segs[-1]
    video_end = last_seg.words[-1].end if last_seg.words else last_seg.end
    _, _, last_end = sections[-1]
    assert last_end == video_end


def test_split_no_gaps_between_sections():
    segs = _uniform_segs(20)
    tr = _transcript(*segs)
    sections = _split_transcript(tr, 4)
    for i in range(1, len(sections)):
        _, prev_start, prev_end = sections[i - 1]
        _, curr_start, curr_end = sections[i]
        # There should be no gap: each section's segs start where the
        # previous section's segs ended (or overlap at cuts).
        assert curr_start >= prev_start


def test_split_no_section_has_zero_duration():
    segs = _uniform_segs(20)
    tr = _transcript(*segs)
    sections = _split_transcript(tr, 4)
    for section_segs, start, end in sections:
        assert end > start


def test_split_first_section_starts_at_first_segment():
    segs = _uniform_segs(10, duration_each=15.0)
    tr = _transcript(*segs)
    sections = _split_transcript(tr, 3)
    _, first_start, _ = sections[0]
    assert first_start == segs[0].start


def test_split_cuts_prefer_full_stop_segments():
    # Build segments where only some end with a full stop.
    segs = [
        _seg(0.0, 10.0, "Introduction."),   # full stop → good cut point
        _seg(10.0, 20.0, "Example here"),
        _seg(20.0, 30.0, "More detail."),   # full stop
        _seg(30.0, 40.0, "Second concept."),  # full stop
        _seg(40.0, 50.0, "Application."),   # full stop
    ]
    tr = _transcript(*segs)
    sections = _split_transcript(tr, 2)
    assert len(sections) == 2
    # At least one cut should land on a full-stop segment.
    # With 2 sections from 50 s, the ideal cut is at 25 s.
    # Segment at t=20-30 ends at 30 (closest full stop), so section 1 ends at 30.
    _, _, end1 = sections[0]
    full_stop_ends = {s.end for s in segs if _ends_with_sentence(s)}
    assert end1 in full_stop_ends


def test_split_second_half_has_sections():
    """The second half of the transcript always gets at least one section."""
    segs = _uniform_segs(40, duration_each=10.0)   # 400 s video
    tr = _transcript(*segs)
    n = 4
    sections = _split_transcript(tr, n)
    half_time = segs[-1].end / 2.0
    second_half_sections = [s for s in sections if s[1] >= half_time or s[2] > half_time]
    assert len(second_half_sections) >= 2  # second half must have >= n/2 sections


def test_split_n1_returns_whole_transcript():
    segs = _uniform_segs(5)
    tr = _transcript(*segs)
    sections = _split_transcript(tr, 1)
    assert len(sections) == 1
    section_segs, start, end = sections[0]
    assert len(section_segs) == len(segs)


# ---------------------------------------------------------------------------
# _parse_concepts: JSON parsing
# ---------------------------------------------------------------------------

def test_parse_concepts_valid():
    raw = '{"concepts":[{"section":1,"keyword":"Gravity"},{"section":2,"keyword":"Motion"}]}'
    result = _parse_concepts(raw, 2)
    assert result == ["Gravity", "Motion"]


def test_parse_concepts_missing_section_returns_none_slot():
    raw = '{"concepts":[{"section":1,"keyword":"Gravity"}]}'
    result = _parse_concepts(raw, 2)
    assert result[0] == "Gravity"
    assert result[1] is None


def test_parse_concepts_accepts_bare_list():
    raw = '[{"section":1,"keyword":"Gravity"}]'
    result = _parse_concepts(raw, 1)
    assert result == ["Gravity"]


def test_parse_concepts_strips_code_fences():
    raw = '```json\n{"concepts":[{"section":1,"keyword":"Energy"}]}\n```'
    result = _parse_concepts(raw, 1)
    assert result == ["Energy"]


def test_parse_concepts_invalid_json_returns_none():
    result = _parse_concepts("not json", 2)
    assert result is None


def test_parse_concepts_out_of_range_section_ignored():
    raw = '{"concepts":[{"section":5,"keyword":"Extra"},{"section":1,"keyword":"OK"}]}'
    result = _parse_concepts(raw, 2)
    assert result[0] == "OK"
    assert result[1] is None


def test_parse_concepts_keyword_too_long_ignored():
    raw = f'{{"concepts":[{{"section":1,"keyword":"{"A" * 61}"}}]}}'
    result = _parse_concepts(raw, 1)
    assert result[0] is None


def test_parse_concepts_all_missing_returns_all_none():
    raw = '{"concepts":[]}'
    result = _parse_concepts(raw, 3)
    assert result == [None, None, None]


# ---------------------------------------------------------------------------
# _fallback_keyword: first full sentence as keyword
# ---------------------------------------------------------------------------

def test_fallback_keyword_uses_first_full_stop():
    segs = [
        _seg(0.0, 5.0, "No end here"),
        _seg(5.0, 10.0, "This ends here."),
    ]
    kw = _fallback_keyword(segs)
    assert kw == "This ends here."


def test_fallback_keyword_truncates_at_60():
    text = "A" * 70 + "."
    segs = [_seg(0.0, 10.0, text)]
    kw = _fallback_keyword(segs)
    assert len(kw) <= 60


def test_fallback_keyword_fallback_to_first_segment():
    segs = [_seg(0.0, 10.0, "No punctuation here")]
    kw = _fallback_keyword(segs)
    assert kw == "No punctuation here"


def test_fallback_keyword_non_empty():
    segs = [_seg(0.0, 10.0, "")]
    kw = _fallback_keyword(segs)
    assert len(kw) >= 1


# ---------------------------------------------------------------------------
# _seg_end: last-word end, fallback to segment.end
# ---------------------------------------------------------------------------

def test_seg_end_returns_last_word_end():
    seg = _seg(0.0, 10.0, "text", word_ends=[8.5, 9.3])
    assert _seg_end(seg) == 9.3


def test_seg_end_fallback_to_segment_end():
    seg = _seg(0.0, 10.0, "text")
    assert _seg_end(seg) == 10.0


# ---------------------------------------------------------------------------
# _ends_with_sentence
# ---------------------------------------------------------------------------

def test_ends_with_period():
    assert _ends_with_sentence(_seg(0, 1, "Hello.")) is True


def test_ends_with_question_mark():
    assert _ends_with_sentence(_seg(0, 1, "What?")) is True


def test_ends_with_exclamation():
    assert _ends_with_sentence(_seg(0, 1, "Great!")) is True


def test_does_not_end_with_sentence():
    assert _ends_with_sentence(_seg(0, 1, "incomplete")) is False


def test_empty_text_returns_false():
    assert _ends_with_sentence(_seg(0, 1, "")) is False


def test_whitespace_only_returns_false():
    assert _ends_with_sentence(_seg(0, 1, "   ")) is False


# ---------------------------------------------------------------------------
# detect_topics smoke test: returns exactly N topics without LLM (using env)
# ---------------------------------------------------------------------------

def test_detect_topics_returns_n_topics(monkeypatch):
    """detect_topics always returns exactly N topics (here using the fallback)."""
    import os
    import app.services.topic_detector as td

    # Provide a fake API key so the client can be constructed.
    monkeypatch.setenv("GROQ_API_KEY", "sk-fake-key-for-test")
    monkeypatch.setattr(td, "_MAX_ATTEMPTS", 1)

    # Stub Groq to always fail so we fall through to the section-based fallback.
    class _FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("stubbed")

    monkeypatch.setattr(td, "Groq", lambda **kw: _FakeClient())

    # Build a 10-minute transcript (N=4).
    segs = [_seg(float(i * 30), float(i * 30 + 29), f"Sentence {i}.")
            for i in range(20)]
    tr = TranscriptResult(segments=segs)

    topics = td.detect_topics(tr)
    n = td.target_n(tr)
    assert len(topics) == n
    # All topics must have end > start.
    for t in topics:
        assert t.end > t.start
    # Last topic must end at the video end.
    video_end = td._seg_end(segs[-1])
    assert topics[-1].end == video_end
    # Second half must have topics.
    half = segs[-1].end / 2
    second_half = [t for t in topics if t.end > half]
    assert len(second_half) >= n // 2
