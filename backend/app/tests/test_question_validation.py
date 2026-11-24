"""Unit tests for validate_questions, _select_questions, _has_forbidden_wording
and _shuffle_options in question_generator.py.

validate_questions accepts 1 to 4 questions. Stars have been removed from
question_generator. Source-wording cleanup is tested via _select_questions.
"""

import pytest
from app.services.question_generator import (
    _has_forbidden_wording,
    _select_questions,
    _shuffle_options,
    validate_questions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_question(
    prompt: str = "What is X?",
    options: list | None = None,
    correct_index: int = 0,
    explanation: str = "Because X.",
) -> dict:
    if options is None:
        options = ["A", "B", "C", "D"]
    return {
        "prompt": prompt,
        "options": options,
        "correct_index": correct_index,
        "explanation": explanation,
    }


def _make_questions(count: int = 4) -> list[dict]:
    return [_make_question(prompt=f"Question {i+1}?", correct_index=i % 4) for i in range(count)]


# ---------------------------------------------------------------------------
# validate_questions: 1-4 accepted
# ---------------------------------------------------------------------------

def test_valid_one_question_returns_true():
    assert validate_questions(_make_questions(1)) is True


def test_valid_two_questions_returns_true():
    assert validate_questions(_make_questions(2)) is True


def test_valid_three_questions_returns_true():
    assert validate_questions(_make_questions(3)) is True


def test_valid_four_questions_returns_true():
    assert validate_questions(_make_questions(4)) is True


def test_zero_questions_returns_false():
    assert validate_questions([]) is False


def test_five_questions_returns_false():
    assert validate_questions(_make_questions(5)) is False


def test_valid_all_correct_index_values():
    for idx in range(4):
        questions = _make_questions(1)
        questions[0]["correct_index"] = idx
        assert validate_questions(questions) is True


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------

def test_missing_prompt_returns_false():
    questions = _make_questions(1)
    del questions[0]["prompt"]
    assert validate_questions(questions) is False


def test_missing_options_returns_false():
    questions = _make_questions(1)
    del questions[0]["options"]
    assert validate_questions(questions) is False


def test_missing_correct_index_returns_false():
    questions = _make_questions(1)
    del questions[0]["correct_index"]
    assert validate_questions(questions) is False


def test_missing_explanation_returns_false():
    questions = _make_questions(1)
    del questions[0]["explanation"]
    assert validate_questions(questions) is False


# ---------------------------------------------------------------------------
# Wrong number of options
# ---------------------------------------------------------------------------

def test_options_has_3_elements_returns_false():
    questions = _make_questions(1)
    questions[0]["options"] = ["A", "B", "C"]
    assert validate_questions(questions) is False


def test_options_has_5_elements_returns_false():
    questions = _make_questions(1)
    questions[0]["options"] = ["A", "B", "C", "D", "E"]
    assert validate_questions(questions) is False


# ---------------------------------------------------------------------------
# Out-of-range correct_index
# ---------------------------------------------------------------------------

def test_correct_index_negative_returns_false():
    questions = _make_questions(1)
    questions[0]["correct_index"] = -1
    assert validate_questions(questions) is False


def test_correct_index_four_returns_false():
    questions = _make_questions(1)
    questions[0]["correct_index"] = 4
    assert validate_questions(questions) is False


def test_correct_index_is_bool_returns_false():
    questions = _make_questions(1)
    questions[0]["correct_index"] = True
    assert validate_questions(questions) is False


def test_correct_index_is_float_returns_false():
    questions = _make_questions(1)
    questions[0]["correct_index"] = 1.0
    assert validate_questions(questions) is False


# ---------------------------------------------------------------------------
# Wrong field types
# ---------------------------------------------------------------------------

def test_prompt_not_a_string_returns_false():
    questions = _make_questions(1)
    questions[0]["prompt"] = 42
    assert validate_questions(questions) is False


def test_options_contains_non_string_returns_false():
    questions = _make_questions(1)
    questions[0]["options"] = ["A", "B", "C", 4]
    assert validate_questions(questions) is False


def test_item_not_a_dict_returns_false():
    assert validate_questions(["not a dict"]) is False


def test_data_is_none_returns_false():
    assert validate_questions(None) is False


@pytest.mark.parametrize("bad_input", [None, 42, 3.14, "string", object()])
def test_never_raises(bad_input):
    assert isinstance(validate_questions(bad_input), bool)


# ---------------------------------------------------------------------------
# _has_forbidden_wording
# ---------------------------------------------------------------------------

def test_wording_rejects_excerpt_in_prompt():
    q = _make_question(prompt="According to the excerpt, what is X?")
    assert _has_forbidden_wording(q) is True


def test_wording_rejects_transcript_in_prompt():
    q = _make_question(prompt="As stated in the transcript, which is true?")
    assert _has_forbidden_wording(q) is True


def test_wording_rejects_passage():
    q = _make_question(prompt="In the passage, what is stated?")
    assert _has_forbidden_wording(q) is True


def test_wording_checks_explanation_too():
    q = _make_question(prompt="What is X?", explanation="The excerpt says X is Y.")
    assert _has_forbidden_wording(q) is True


def test_wording_is_case_insensitive():
    q = _make_question(prompt="According To The Excerpt, what is X?")
    assert _has_forbidden_wording(q) is True


def test_wording_allows_clean_question():
    q = _make_question(
        prompt="What is the main input for photosynthesis?",
        explanation="Plants use CO2.",
    )
    assert _has_forbidden_wording(q) is False


# ---------------------------------------------------------------------------
# _select_questions: clean-first, source-worded fallback, cap 4
# ---------------------------------------------------------------------------

def test_select_prefers_clean_over_source_worded():
    clean = _make_question(prompt="What is photosynthesis?")
    dirty = _make_question(prompt="According to the transcript, what is X?")
    kept = _select_questions([dirty, clean])
    assert len(kept) >= 1
    assert kept[0]["prompt"] == "What is photosynthesis?"


def test_select_uses_source_worded_when_no_clean():
    dirty1 = _make_question(prompt="According to the transcript, what is X?")
    dirty2 = _make_question(prompt="In the excerpt, what is Y?")
    kept = _select_questions([dirty1, dirty2])
    assert len(kept) >= 1


def test_select_caps_at_four():
    questions = [_make_question(prompt=f"Q{i}?") for i in range(8)]
    kept = _select_questions(questions)
    assert len(kept) == 4


def test_select_empty_input_returns_empty():
    assert _select_questions([]) == []


def test_select_cleans_leading_phrase():
    dirty = _make_question(prompt="According to the excerpt, what does X mean?")
    kept = _select_questions([dirty])
    assert len(kept) == 1
    # The leading phrase should be stripped
    assert not kept[0]["prompt"].lower().startswith("according to")


# ---------------------------------------------------------------------------
# _shuffle_options: invariants
# ---------------------------------------------------------------------------

def _options() -> list[str]:
    return ["Alpha", "Beta", "Gamma", "Delta"]


def test_shuffle_correct_text_preserved_all_indices():
    options = _options()
    for correct_index in range(4):
        correct_text = options[correct_index]
        for _ in range(50):
            shuffled, new_index = _shuffle_options(options, correct_index)
            assert shuffled[new_index] == correct_text


def test_shuffle_preserves_set_of_options():
    options = _options()
    shuffled, _ = _shuffle_options(options, 0)
    assert sorted(shuffled) == sorted(options)


def test_shuffle_does_not_mutate_original():
    options = _options()
    original = list(options)
    _shuffle_options(options, 0)
    assert options == original


def test_shuffle_new_index_in_range():
    options = _options()
    for correct_index in range(4):
        _, new_index = _shuffle_options(options, correct_index)
        assert 0 <= new_index < 4


def test_shuffle_actually_reorders():
    options = _options()
    seen_positions = set()
    for _ in range(200):
        _, new_index = _shuffle_options(options, 0)
        seen_positions.add(new_index)
    assert len(seen_positions) > 1


# ---------------------------------------------------------------------------
# generate_questions returns [] on failure — never raises
# ---------------------------------------------------------------------------

def test_generate_questions_returns_empty_list_on_failure(monkeypatch):
    """When all LLM attempts fail, generate_questions returns [] not raises."""
    from app.services.question_generator import generate_questions
    from app.models import Topic
    import app.services.question_generator as qg

    # Limit to 1 attempt so the test doesn't wait for retries.
    monkeypatch.setattr(qg, "_MAX_ATTEMPTS", 1)

    # Stub the Groq client to always raise so all retries fail.
    class _FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("network error")

    monkeypatch.setattr(qg, "Groq", lambda **kw: _FakeClient())
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    topic = Topic(keyword="Photosynthesis", start=0.0, end=60.0)
    result = generate_questions(topic, "some transcript text")
    assert result == []  # returns empty list, never raises


# ---------------------------------------------------------------------------
# Video is Ready even when no topic has questions (pipeline_job contract)
# ---------------------------------------------------------------------------

def test_pipeline_job_marks_ready_when_all_topics_have_zero_questions(monkeypatch):
    """The pipeline marks the video ready even if every topic returns []."""
    import app.jobs.pipeline_job as pj
    from app.models import Segment, TranscriptResult, Topic

    # Minimal in-memory stubs so no real DB / ffmpeg / API is needed.
    calls = {}

    def _extract(path):
        calls["extract"] = True
        return "/tmp/fake.mp3"

    def _transcribe(path):
        calls["transcribe"] = True
        seg = Segment(start=0.0, end=120.0, text="Hello.", words=[])
        return TranscriptResult(segments=[seg])

    def _detect(transcript):
        calls["detect"] = True
        return [Topic(keyword="K1", start=0.0, end=120.0)]

    def _generate(topic, slice_):
        calls["generate"] = True
        return []  # zero questions

    statuses = []
    extras = {}

    def _update_one(filt, upd, **kw):
        set_doc = upd.get("$set", {})
        statuses.append(set_doc.get("status"))
        extras.update(set_doc)

    class _FakeCollection:
        def update_one(self, f, u, **kw): _update_one(f, u)

    class _FakeDB:
        def __getitem__(self, name): return _FakeCollection()

    def _fake_write(result, path):
        calls["write"] = True

    def _fake_exists(path): return True
    def _fake_remove(path): pass

    monkeypatch.setattr(pj, "extract_audio", _extract)
    monkeypatch.setattr(pj, "transcribe", _transcribe)
    monkeypatch.setattr(pj, "detect_topics", _detect)
    monkeypatch.setattr(pj, "generate_questions", _generate)
    monkeypatch.setattr(pj, "write_output", _fake_write)
    monkeypatch.setattr(pj, "get_db", lambda: _FakeDB())
    monkeypatch.setattr("os.path.exists", _fake_exists)
    monkeypatch.setattr("os.remove", _fake_remove)

    pj.run_pipeline_job("vid123", "/fake/video.mp4", "/fake/out.json")

    # Must have been marked ready, never failed.
    assert "ready" in statuses
    assert "failed" not in statuses


# ---------------------------------------------------------------------------
# QuestionOut model never leaks correct_index / explanation / correct_answer
# ---------------------------------------------------------------------------

def test_question_out_model_has_no_answer_fields():
    """The QuestionOut Pydantic model must not contain answer-revealing fields."""
    from app.routes.videos import QuestionOut
    import inspect

    fields = QuestionOut.model_fields  # Pydantic v2
    forbidden = {"correct_index", "correct_answer", "explanation", "stars"}
    leaked = forbidden & set(fields.keys())
    assert not leaked, f"QuestionOut leaks answer fields: {leaked}"
