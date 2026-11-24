"""Results routes.

GET /results/video/{video_id}  — teacher only, own videos only.
GET /results/me                — student only.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from app.database import get_db
from app.routes.videos import load_output, to_oid
from app.security import get_current_user, require_role

router = APIRouter(prefix="/results", tags=["results"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class StudentRow(BaseModel):
    student_name: str
    answered: int
    correct_first_try: int
    score_percent: float
    last_activity: Optional[str]


class QuestionRow(BaseModel):
    question_text: str
    times_shown: int
    correct_percent: float
    most_chosen_wrong_option_text: Optional[str]


class VideoResultsResponse(BaseModel):
    students_attempted: int
    average_score: float
    per_student: List[StudentRow]
    per_question: List[QuestionRow]


class MyVideoResult(BaseModel):
    video_title: str
    answered: int
    correct_first_try: int
    score_percent: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pct(num: int, denom: int) -> float:
    return round(100.0 * num / denom, 1) if denom else 0.0


# ---------------------------------------------------------------------------
# GET /results/video/{video_id}  — teacher only
# ---------------------------------------------------------------------------

@router.get("/video/{video_id}", response_model=VideoResultsResponse)
def video_results(
    video_id: str,
    user: dict = Depends(require_role("teacher")),
):
    """Return aggregated results for one video (teacher only, own videos)."""
    video = get_db()["videos"].find_one({"_id": to_oid(video_id)})
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found.")
    if video.get("teacher_email") != user.get("email"):
        raise HTTPException(status_code=403, detail="Not your video.")

    # Load the pipeline output to get question texts.
    try:
        output = load_output(video_id)
        topics = output.get("topics", [])
    except HTTPException:
        topics = []

    # Build a map question_id → question text and options list.
    q_text_map: dict[str, str] = {}
    q_options_map: dict[str, list] = {}
    for t_idx, topic in enumerate(topics):
        for q_idx, q in enumerate(topic.get("questions", [])):
            qid = f"{video_id}:{t_idx}:{q_idx}"
            q_text_map[qid] = q.get("prompt", "")
            q_options_map[qid] = q.get("options", [])

    # Fetch all first-attempt records for this video in one query.
    attempts = list(
        get_db()["attempts"].find(
            {"video_id": video_id, "try_number": 1}
        )
    )

    if not attempts:
        return VideoResultsResponse(
            students_attempted=0,
            average_score=0.0,
            per_student=[],
            per_question=[],
        )

    # --- Per-student aggregation ---
    student_data: dict[str, dict] = {}
    for a in attempts:
        sid = a.get("student_id", "")
        if sid not in student_data:
            student_data[sid] = {
                "name": a.get("student_name", a.get("student_email", "Unknown")),
                "answered": 0,
                "correct": 0,
                "last_activity": None,
            }
        student_data[sid]["answered"] += 1
        if a.get("is_correct"):
            student_data[sid]["correct"] += 1
        ts: Optional[datetime] = a.get("created_at")
        if ts:
            if student_data[sid]["last_activity"] is None or ts > student_data[sid]["last_activity"]:
                student_data[sid]["last_activity"] = ts

    per_student = [
        StudentRow(
            student_name=d["name"],
            answered=d["answered"],
            correct_first_try=d["correct"],
            score_percent=_pct(d["correct"], d["answered"]),
            last_activity=d["last_activity"].isoformat() if d["last_activity"] else None,
        )
        for d in student_data.values()
    ]
    per_student.sort(key=lambda r: r.score_percent, reverse=True)

    total_answered = sum(d["answered"] for d in student_data.values())
    total_correct = sum(d["correct"] for d in student_data.values())
    average_score = _pct(total_correct, total_answered)

    # --- Per-question aggregation ---
    q_data: dict[str, dict] = {}
    for a in attempts:
        qid = a.get("question_id", "")
        if not qid:
            qid = f"{a.get('video_id')}:{a.get('topic_index')}:{a.get('question_index')}"
        if qid not in q_data:
            q_data[qid] = {
                "shown": 0,
                "correct": 0,
                "wrong_choices": {},
            }
        q_data[qid]["shown"] += 1
        if a.get("is_correct"):
            q_data[qid]["correct"] += 1
        else:
            sel = a.get("selected_index")
            if sel is not None:
                q_data[qid]["wrong_choices"][sel] = q_data[qid]["wrong_choices"].get(sel, 0) + 1

    per_question = []
    for qid, d in q_data.items():
        options = q_options_map.get(qid, [])
        most_wrong_idx = None
        if d["wrong_choices"]:
            most_wrong_idx = max(d["wrong_choices"], key=lambda k: d["wrong_choices"][k])
        most_wrong_text = (
            options[most_wrong_idx] if most_wrong_idx is not None and most_wrong_idx < len(options)
            else None
        )
        per_question.append(QuestionRow(
            question_text=q_text_map.get(qid, f"Question {qid}"),
            times_shown=d["shown"],
            correct_percent=_pct(d["correct"], d["shown"]),
            most_chosen_wrong_option_text=most_wrong_text,
        ))

    return VideoResultsResponse(
        students_attempted=len(student_data),
        average_score=average_score,
        per_student=per_student,
        per_question=per_question,
    )


# ---------------------------------------------------------------------------
# GET /results/me  — student only
# ---------------------------------------------------------------------------

@router.get("/me", response_model=List[MyVideoResult])
def my_results(user: dict = Depends(require_role("student"))):
    """Return the student's own per-video results (first attempts only)."""
    student_id = str(user["_id"])
    attempts = list(
        get_db()["attempts"].find(
            {"student_id": student_id, "try_number": 1}
        )
    )

    # Group by video_id.
    video_data: dict[str, dict] = {}
    for a in attempts:
        vid = a.get("video_id", "")
        if vid not in video_data:
            video_data[vid] = {"answered": 0, "correct": 0}
        video_data[vid]["answered"] += 1
        if a.get("is_correct"):
            video_data[vid]["correct"] += 1

    if not video_data:
        return []

    # Fetch video titles in one query.
    from bson import ObjectId
    oids = []
    for vid in video_data:
        try:
            oids.append(ObjectId(vid))
        except Exception:
            pass
    videos = {str(v["_id"]): v for v in get_db()["videos"].find({"_id": {"$in": oids}})}

    result = []
    for vid, d in video_data.items():
        title = videos.get(vid, {}).get("title", "Unknown video")
        result.append(MyVideoResult(
            video_title=title,
            answered=d["answered"],
            correct_first_try=d["correct"],
            score_percent=_pct(d["correct"], d["answered"]),
        ))
    result.sort(key=lambda r: r.video_title)
    return result
