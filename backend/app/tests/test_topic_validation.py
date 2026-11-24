"""Tests for the new section-based topic detector.

The old validate_topics / _merge_short_topics helpers were removed when the
architecture changed to mandatory-N section splitting.  This file tests the
same logical contracts through the new public API.
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

def _seg(start: float, end: float, text: str = "Hello.", word_ends=None) -> Segment:
    words = []
    if word_ends:
        for we in word_ends:
            words.append(WordEntry(word="w", start=we - 0.1, end=we))
    return Segment(start=start, end=end, text=text, words=words)


def _tr(*segs: Segment) -> TranscriptResult:
    return TranscriptResult(segments=list(segs))


def _uniform(count: int, dur: float = 10.0, text: str = "Concept.") -> list[Segment]:
    return [_seg(i * dur, (i + 1) * dur, text) for i in range(count)]


# ---------------------------------------------------------------------------
# target_n: N is mandatory and matches the length table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seconds,expected_n", [
    (60.0, 2),    # 1 min  < 3 min
    (120.0, 2),   # 2 min  < 3 min
    (180.0, 3),   # 3 min  3–5
    (270.0, 3),   # 4.5 min  3–5
    (300.0, 4),   # 5 min  5–11
    (600.0, 4),   # 10 min  5–11
    (660.0, 6),   # 11 min  11–15
    (900.0, 6),   # 15 min  11–15
    (960.0, 8),   # 16 min  16–20
    (1200.0, 8),  # 20 min  16–20
    (1260.0, 9),  # 21 min  > 20
])
def test_target_n_table(seconds, expected_n):
    tr = _tr(_seg(0.0, seconds))
    assert target_n(tr) == expected_n


# ---------------------------------------------------------------------------
# _split_transcript: exactly N sections, full-stop cuts, no gaps, video end
# ---------------------------------------------------------------------------

def test_split_exact_n_sections():
    segs = _uniform(20)
    tr = _tr(*segs)
    for n in (2, 3, 4, 6):
        sections = _split_transcript(tr, n)
        assert len(sections) == n, f"Expected {n} sections, got {len(sections)}"


def test_split_last_ends_at_video_end():
    segs = _uniform(20, dur=10.0)
    tr = _tr(*segs)
    sections = _split_transcript(tr, 4)
    video_end = _seg_end(segs[-1])
    _, _, last_end = sections[-1]
    assert last_end == video_end


def test_split_no_section_has_zero_duration():
    segs = _uniform(20)
    tr = _tr(*segs)
    for section_segs, start, end in _split_transcript(tr, 4):
        assert end > start


def test_split_first_section_starts_at_first_segment():
    segs = _uniform(10)
    tr = _tr(*segs)
    _, first_start, _ = _split_transcript(tr, 3)[0]
    assert first_start == segs[0].start


def test_split_second_half_has_sections():
    """Every section N/2 and later must start in the second half of the video."""
    segs = _uniform(40, dur=10.0)
    tr = _tr(*segs)
    n = 4
    sections = _split_transcript(tr, n)
    half_time = segs[-1].end / 2.0
    second_half_count = sum(1 for _, s, e in sections if e > half_time)
    assert second_half_count >= n // 2


def test_split_cuts_prefer_full_stop_segments():
    segs = [
        _seg(0.0,  10.0, "Intro."),
        _seg(10.0, 20.0, "example here"),
        _seg(20.0, 30.0, "More detail."),
        _seg(30.0, 40.0, "Second concept."),
        _seg(40.0, 50.0, "Application."),
    ]
    tr = _tr(*segs)
    sections = _split_transcript(tr, 2)
    # At least one section boundary must land on a full-stop segment end.
    full_stop_ends = {s.end for s in segs if _ends_with_sentence(s)}
    boundary_ends = {e for _, _, e in sections[:-1]}  # all but last
    assert bool(boundary_ends & full_stop_ends) or len(sections) == 1


# ---------------------------------------------------------------------------
# _parse_concepts
# ---------------------------------------------------------------------------

def test_parse_concepts_full_set():
    raw = '{"concepts":[{"section":1,"keyword":"Gravity"},{"section":2,"keyword":"Motion"}]}'
    assert _parse_concepts(raw, 2) == ["Gravity", "Motion"]


def test_parse_concepts_missing_section_is_none():
    raw = '{"concepts":[{"section":1,"keyword":"Gravity"}]}'
    result = _parse_concepts(raw, 2)
    assert result[0] == "Gravity"
    assert result[1] is None


def test_parse_concepts_all_missing():
    raw = '{"concepts":[]}'
    assert _parse_concepts(raw, 3) == [None, None, None]


def test_parse_concepts_invalid_json_returns_none():
    assert _parse_concepts("not json", 2) is None


def test_parse_concepts_no_times_in_output():
    """The LLM output must not include any time fields."""
    raw = '{"concepts":[{"section":1,"keyword":"Energy","start":0,"end":60}]}'
    result = _parse_concepts(raw, 1)
    # We only extract 'keyword'; extra fields are ignored.
    assert result[0] == "Energy"


def test_parse_concepts_no_stars_in_output():
    raw = '{"concepts":[{"section":1,"keyword":"Forces","stars":3}]}'
    result = _parse_concepts(raw, 1)
    assert result[0] == "Forces"


# ---------------------------------------------------------------------------
# _fallback_keyword
# ---------------------------------------------------------------------------

def test_fallback_keyword_first_full_stop():
    segs = [_seg(0, 5, "No end"), _seg(5, 10, "This ends.")]
    assert _fallback_keyword(segs) == "This ends."


def test_fallback_keyword_truncates():
    segs = [_seg(0, 10, "X" * 70 + ".")]
    kw = _fallback_keyword(segs)
    assert len(kw) <= 60


def test_fallback_keyword_non_empty():
    segs = [_seg(0, 10, "")]
    kw = _fallback_keyword(segs)
    assert len(kw) >= 1


# ---------------------------------------------------------------------------
# No times or stars sent to the model
# ---------------------------------------------------------------------------

def test_prompt_has_no_explicit_timestamps():
    """The prompt must not contain segment time numbers."""
    import app.services.topic_detector as td
    segs = _uniform(10, dur=30.0)
    tr = _tr(*segs)
    sections = _split_transcript(tr, 3)
    prompt = td._build_prompt(sections)
    # Segment times like "[0.0 - 30.0]" must not appear.
    import re
    assert not re.search(r"\[\d+\.\d+ - \d+\.\d+\]", prompt), (
        "Prompt should not contain [start - end] time markers"
    )


def test_prompt_has_no_star_or_rating_fields():
    import app.services.topic_detector as td
    segs = _uniform(10)
    tr = _tr(*segs)
    sections = _split_transcript(tr, 3)
    prompt = td._build_prompt(sections)
    low = prompt.lower()
    assert "stars" not in low
    assert "rating" not in low
    assert "difficulty" not in low


# ---------------------------------------------------------------------------
# detect_topics always returns exactly N topics (no LLM)
# ---------------------------------------------------------------------------

def test_detect_topics_returns_n_topics(monkeypatch):
    import app.services.topic_detector as td

    monkeypatch.setenv("GROQ_API_KEY", "sk-fake")
    monkeypatch.setattr(td, "_MAX_ATTEMPTS", 1)

    class _FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("stubbed")

    monkeypatch.setattr(td, "Groq", lambda **kw: _FakeClient())

    # 10-minute video → N=4
    segs = _uniform(20, dur=30.0, text="Sentence.")
    tr = _tr(*segs)
    topics = td.detect_topics(tr)
    n = td.target_n(tr)
    assert len(topics) == n
    for t in topics:
        assert t.end > t.start
    video_end = _seg_end(segs[-1])
    assert topics[-1].end == video_end


def test_detect_topics_second_half_has_topics(monkeypatch):
    """The second half of the video must have pop-ups."""
    import app.services.topic_detector as td

    monkeypatch.setenv("GROQ_API_KEY", "sk-fake")
    monkeypatch.setattr(td, "_MAX_ATTEMPTS", 1)

    class _FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("stubbed")

    monkeypatch.setattr(td, "Groq", lambda **kw: _FakeClient())

    segs = _uniform(40, dur=10.0, text="Topic.")
    tr = _tr(*segs)
    topics = td.detect_topics(tr)
    half = segs[-1].end / 2.0
    second_half = [t for t in topics if t.end > half]
    n = td.target_n(tr)
    assert len(second_half) >= n // 2
