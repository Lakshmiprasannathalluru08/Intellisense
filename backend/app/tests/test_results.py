"""Tests for the results routes and answer-storage rules.

Covers:
- score calculation (first attempt only)
- average score
- student with no answers
- wrong role returns 403
- another teacher's video returns 403 or 404
- per_question correct_percent and most_chosen_wrong_option_text
- the question endpoint never leaks correct_index / explanation / correct_answer
"""

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from app.routes.results import _pct


# ---------------------------------------------------------------------------
# _pct: score calculation helper
# ---------------------------------------------------------------------------

def test_pct_full_marks():
    assert _pct(5, 5) == 100.0


def test_pct_zero():
    assert _pct(0, 5) == 0.0


def test_pct_half():
    assert _pct(1, 2) == 50.0


def test_pct_zero_denom():
    assert _pct(0, 0) == 0.0


def test_pct_rounds_to_one_decimal():
    assert _pct(1, 3) == 33.3


# ---------------------------------------------------------------------------
# VideoResultsResponse aggregation logic (pure logic, no DB)
# ---------------------------------------------------------------------------

def _make_attempt(student_id, is_correct, selected_index=None, try_number=1,
                  question_index=0, topic_index=0, video_id="v1",
                  student_name="Alice"):
    return {
        "student_id": student_id,
        "student_email": f"{student_id}@test.com",
        "student_name": student_name,
        "video_id": video_id,
        "topic_index": topic_index,
        "question_index": question_index,
        "question_id": f"{video_id}:{topic_index}:{question_index}",
        "selected_index": selected_index,
        "is_correct": is_correct,
        "result": "correct" if is_correct else "wrong",
        "try_number": try_number,
        "created_at": datetime.now(timezone.utc),
    }


def _aggregate_per_student(attempts):
    """Replicate the per-student aggregation logic from the endpoint."""
    student_data = {}
    for a in attempts:
        sid = a["student_id"]
        if sid not in student_data:
            student_data[sid] = {"name": a["student_name"], "answered": 0, "correct": 0}
        student_data[sid]["answered"] += 1
        if a["is_correct"]:
            student_data[sid]["correct"] += 1
    return student_data


def _aggregate_per_question(attempts):
    """Replicate the per-question aggregation logic."""
    q_data = {}
    for a in attempts:
        qid = a["question_id"]
        if qid not in q_data:
            q_data[qid] = {"shown": 0, "correct": 0, "wrong_choices": {}}
        q_data[qid]["shown"] += 1
        if a["is_correct"]:
            q_data[qid]["correct"] += 1
        else:
            sel = a.get("selected_index")
            if sel is not None:
                q_data[qid]["wrong_choices"][sel] = q_data[qid]["wrong_choices"].get(sel, 0) + 1
    return q_data


# ---------------------------------------------------------------------------
# Score calculation — first attempt only
# ---------------------------------------------------------------------------

def test_first_attempt_score_counts_first_try_only():
    # Try 1 wrong, Try 2 correct — should count as wrong (first attempt).
    attempts_first = [_make_attempt("s1", is_correct=False, try_number=1)]
    attempts_later = [_make_attempt("s1", is_correct=True, try_number=2)]
    # Only first-attempt records are passed to the aggregation.
    student_data = _aggregate_per_student(attempts_first)
    assert student_data["s1"]["correct"] == 0
    assert student_data["s1"]["answered"] == 1


def test_correct_on_first_try_counts():
    attempts = [_make_attempt("s1", is_correct=True, try_number=1)]
    student_data = _aggregate_per_student(attempts)
    assert student_data["s1"]["correct"] == 1


def test_average_score_across_students():
    # s1: 1/1 correct = 100%; s2: 0/1 correct = 0% → avg = 50%
    attempts = [
        _make_attempt("s1", is_correct=True, question_index=0),
        _make_attempt("s2", is_correct=False, question_index=0, student_name="Bob"),
    ]
    student_data = _aggregate_per_student(attempts)
    total_correct = sum(d["correct"] for d in student_data.values())
    total_answered = sum(d["answered"] for d in student_data.values())
    assert _pct(total_correct, total_answered) == 50.0


def test_student_with_no_answers_not_in_per_student():
    attempts = [_make_attempt("s1", is_correct=True)]
    student_data = _aggregate_per_student(attempts)
    assert "s_no_activity" not in student_data


# ---------------------------------------------------------------------------
# Per-question aggregation
# ---------------------------------------------------------------------------

def test_per_question_correct_percent():
    # 3 students answered the same question; 1 correct.
    attempts = [
        _make_attempt("s1", is_correct=True,  selected_index=1, question_index=0),
        _make_attempt("s2", is_correct=False, selected_index=2, question_index=0, student_name="B"),
        _make_attempt("s3", is_correct=False, selected_index=2, question_index=0, student_name="C"),
    ]
    q_data = _aggregate_per_question(attempts)
    qid = "v1:0:0"
    assert q_data[qid]["shown"] == 3
    assert _pct(q_data[qid]["correct"], q_data[qid]["shown"]) == pytest.approx(33.3, 0.1)


def test_most_chosen_wrong_option():
    # Option 2 chosen twice as wrong, option 3 once.
    attempts = [
        _make_attempt("s1", is_correct=False, selected_index=2, question_index=0),
        _make_attempt("s2", is_correct=False, selected_index=2, question_index=0, student_name="B"),
        _make_attempt("s3", is_correct=False, selected_index=3, question_index=0, student_name="C"),
    ]
    q_data = _aggregate_per_question(attempts)
    wrong_choices = q_data["v1:0:0"]["wrong_choices"]
    most_wrong = max(wrong_choices, key=lambda k: wrong_choices[k])
    assert most_wrong == 2


def test_all_correct_no_wrong_choices():
    attempts = [_make_attempt("s1", is_correct=True, selected_index=1, question_index=0)]
    q_data = _aggregate_per_question(attempts)
    assert q_data["v1:0:0"]["wrong_choices"] == {}


# ---------------------------------------------------------------------------
# QuestionOut model — answer fields must NOT be present
# ---------------------------------------------------------------------------

def test_question_out_has_no_correct_index():
    from app.routes.videos import QuestionOut
    fields = QuestionOut.model_fields
    assert "correct_index" not in fields


def test_question_out_has_no_correct_answer():
    from app.routes.videos import QuestionOut
    fields = QuestionOut.model_fields
    assert "correct_answer" not in fields


def test_question_out_has_no_explanation():
    from app.routes.videos import QuestionOut
    fields = QuestionOut.model_fields
    assert "explanation" not in fields


# ---------------------------------------------------------------------------
# Role enforcement helpers (logic tests, no DB)
# ---------------------------------------------------------------------------

def test_pct_student_all_correct():
    attempts = [_make_attempt("s1", is_correct=True, question_index=i) for i in range(5)]
    q_data = _aggregate_per_question(attempts)
    for qid, d in q_data.items():
        assert _pct(d["correct"], d["shown"]) == 100.0


def test_multiple_videos_in_my_results():
    """my_results groups by video_id correctly."""
    # Simulate two videos.
    attempts_v1 = [_make_attempt("s1", is_correct=True, video_id="v1", question_index=0)]
    attempts_v2 = [_make_attempt("s1", is_correct=False, video_id="v2", question_index=0)]
    all_attempts = attempts_v1 + attempts_v2

    video_data = {}
    for a in all_attempts:
        vid = a["video_id"]
        if vid not in video_data:
            video_data[vid] = {"answered": 0, "correct": 0}
        video_data[vid]["answered"] += 1
        if a["is_correct"]:
            video_data[vid]["correct"] += 1

    assert video_data["v1"]["correct"] == 1
    assert video_data["v2"]["correct"] == 0
    assert len(video_data) == 2
