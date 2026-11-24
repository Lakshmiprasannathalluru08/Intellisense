"""Answer submission route: POST /answers.

The backend is the sole authority on correctness. It returns the result,
the explanation, the correct answer text and correct_index (only in this
response, after the student has submitted), remaining tries, next action
and a weak flag.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import get_db
from app.routes.videos import load_output
from app.security import get_current_user

router = APIRouter(tags=["answers"])

MAX_TRIES = 3


class AnswerRequest(BaseModel):
    video_id: str
    topic_index: int
    question_index: int
    selected_index: int | None = None
    try_number: int
    timed_out: bool = False


class AnswerResponse(BaseModel):
    result: str            # "correct" | "wrong" | "timeout"
    explanation: str
    correct_answer: str    # text of the correct option, revealed after submission
    correct_index: int     # 0-based index of the correct option
    remaining_tries: int
    next_action: str       # "continue" | "replay"
    weak: bool = False


@router.post("/answers", response_model=AnswerResponse)
def submit_answer(payload: AnswerRequest, user: dict = Depends(get_current_user)):
    if not (1 <= payload.try_number <= MAX_TRIES):
        raise HTTPException(status_code=400, detail="try_number out of range (1-3).")

    data = load_output(payload.video_id)
    topics = data.get("topics", [])
    if payload.topic_index < 0 or payload.topic_index >= len(topics):
        raise HTTPException(status_code=400, detail="topic_index out of range.")
    questions = topics[payload.topic_index].get("questions", [])
    if not questions:
        raise HTTPException(status_code=400, detail="No questions for this topic.")
    if payload.question_index < 0 or payload.question_index >= len(questions):
        raise HTTPException(status_code=400, detail="question_index out of range.")

    # The submitted question must be the one served for this try.
    served = get_db()["served_questions"].find_one({
        "student_id": str(user["_id"]),
        "video_id": payload.video_id,
        "topic_index": payload.topic_index,
        "try_number": payload.try_number,
    })
    if served is None:
        raise HTTPException(status_code=400, detail="No question was served for this try.")
    if served["question_index"] != payload.question_index:
        raise HTTPException(status_code=400, detail="This question was not the one served.")

    q = questions[payload.question_index]
    options = q.get("options", [])
    correct_index = q.get("correct_index")
    explanation = q.get("explanation", "")
    correct_answer = options[correct_index] if correct_index is not None and correct_index < len(options) else ""

    if payload.selected_index is not None and not (0 <= payload.selected_index < len(options)):
        raise HTTPException(status_code=400, detail="selected_index out of range.")

    if payload.timed_out or payload.selected_index is None:
        result = "timeout"
    elif payload.selected_index == correct_index:
        result = "correct"
    else:
        result = "wrong"

    if result == "correct":
        next_action = "continue"
        weak = False
        remaining_tries = max(0, MAX_TRIES - payload.try_number)
    elif payload.try_number < MAX_TRIES:
        next_action = "replay"
        weak = False
        remaining_tries = MAX_TRIES - payload.try_number
    else:
        next_action = "continue"
        weak = True
        remaining_tries = 0

    get_db()["attempts"].insert_one({
        "student_id": str(user["_id"]),
        "student_email": user.get("email", ""),
        "student_name": user.get("name", ""),
        "video_id": payload.video_id,
        "topic_index": payload.topic_index,
        "question_index": payload.question_index,
        "question_id": f"{payload.video_id}:{payload.topic_index}:{payload.question_index}",
        "selected_index": payload.selected_index,
        "is_correct": result == "correct",
        "result": result,
        "try_number": payload.try_number,
        "created_at": datetime.now(timezone.utc),
    })

    get_db()["served_questions"].delete_one({"_id": served["_id"]})

    return AnswerResponse(
        result=result,
        explanation=explanation,
        correct_answer=correct_answer,
        correct_index=correct_index,
        remaining_tries=remaining_tries,
        next_action=next_action,
        weak=weak,
    )
