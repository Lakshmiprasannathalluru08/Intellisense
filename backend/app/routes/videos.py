"""Video routes: upload, list, topics, question, and file streaming.

The correct answer (correct_index) and explanations are NEVER sent by the
topics or question endpoints — only by the answers endpoint after a
submission, and only the result + explanation (not correct_index).
"""

import json
import os
import random
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from app.database import get_db
from app.jobs.pipeline_job import run_pipeline_job
from app.security import get_current_user, require_role, user_from_token

router = APIRouter(prefix="/videos", tags=["videos"])

# routes/videos.py -> backend/app/routes -> backend/app -> backend
_STORAGE = Path(__file__).resolve().parent.parent.parent / "storage"
_VIDEOS_DIR = _STORAGE / "videos"
_OUTPUTS_DIR = _STORAGE / "outputs"

_MAX_SUBJECT = 60
_MAX_DESCRIPTION = 500
_ALLOWED_VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}

_VIDEO_MIME = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".m4v": "video/x-m4v",
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class VideoOut(BaseModel):
    id: str
    title: str
    subject: str
    description: str
    teacher_name: str
    status: str
    error: str | None = None
    topic_count: int = 0
    created_at: str | None = None


class TopicOut(BaseModel):
    index: int
    start: float
    end: float


class QuestionOut(BaseModel):
    question_index: int
    prompt: str
    options: list[str]


# ---------------------------------------------------------------------------
# Shared helpers (also used by routes/answers.py)
# ---------------------------------------------------------------------------

def to_oid(video_id: str) -> ObjectId:
    try:
        return ObjectId(video_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid video id.")


def output_path_for(video_id: str) -> Path:
    return _OUTPUTS_DIR / f"{video_id}.json"


def load_output(video_id: str) -> dict:
    """Read the pipeline output JSON for a video (404 if not ready)."""
    path = output_path_for(video_id)
    if not path.exists():
        raise HTTPException(
            status_code=404, detail="Video topics are not available yet."
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _serialize(doc: dict, include_error: bool) -> VideoOut:
    created_at = doc.get("created_at")
    return VideoOut(
        id=str(doc["_id"]),
        title=doc.get("title", ""),
        subject=doc.get("subject", ""),
        description=doc.get("description", ""),
        teacher_name=doc.get("teacher_name", ""),
        status=doc.get("status", ""),
        error=doc.get("error") if include_error else None,
        topic_count=doc.get("topic_count", 0),
        created_at=created_at.isoformat() if created_at else None,
    )


def _content_type(path: str) -> str:
    return _VIDEO_MIME.get(Path(path).suffix.lower(), "application/octet-stream")


def _stream_file(path: str, request: Request) -> StreamingResponse:
    """Serve a file with HTTP Range support for the <video> element."""
    size = os.path.getsize(path)
    range_header = request.headers.get("range")
    start = 0
    end = size - 1
    code = 200
    ctype = _content_type(path)
    headers = {"Accept-Ranges": "bytes", "Content-Type": ctype}
    if range_header:
        m = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if m:
            start = int(m.group(1))
            if m.group(2):
                end = int(m.group(2))
            code = 206
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    length = end - start + 1
    headers["Content-Length"] = str(length)

    def iterfile():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(iterfile(), status_code=code, headers=headers, media_type=ctype)


# ---------------------------------------------------------------------------
# Upload + list
# ---------------------------------------------------------------------------

@router.post("", response_model=VideoOut, status_code=status.HTTP_201_CREATED)
def upload_video(
    background_tasks: BackgroundTasks,
    title: str = Form(..., min_length=1, max_length=200),
    subject: str = Form(..., min_length=1, max_length=_MAX_SUBJECT),
    description: str = Form("", max_length=_MAX_DESCRIPTION),
    file: UploadFile = File(...),
    user: dict = Depends(require_role("teacher")),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_VIDEO_EXT:
        raise HTTPException(status_code=400, detail="Unsupported video file type.")

    _VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    _OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    stored_name = f"{uuid.uuid4().hex}{ext}"
    video_path = _VIDEOS_DIR / stored_name
    with open(video_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    doc = {
        "title": title.strip(),
        "subject": subject.strip(),
        "description": description.strip(),
        "teacher_name": user.get("name", ""),
        "teacher_email": user.get("email", ""),
        "status": "transcribing",
        "error": None,
        "topic_count": 0,
        "video_path": str(video_path),
        "created_at": datetime.now(timezone.utc),
    }
    inserted = get_db()["videos"].insert_one(doc)
    video_id = inserted.inserted_id
    output_path = str(output_path_for(str(video_id)))

    background_tasks.add_task(run_pipeline_job, video_id, str(video_path), output_path)

    doc["_id"] = video_id
    return _serialize(doc, include_error=True)


@router.get("", response_model=list[VideoOut])
def list_videos(user: dict = Depends(get_current_user)):
    videos = get_db()["videos"]
    if user.get("role") == "student":
        cursor = videos.find({"status": "ready"}).sort("created_at", -1)
        return [_serialize(d, include_error=False) for d in cursor]
    cursor = videos.find({"teacher_email": user.get("email")}).sort("created_at", -1)
    return [_serialize(d, include_error=True) for d in cursor]


# ---------------------------------------------------------------------------
# Student playback: topics, question, file
# ---------------------------------------------------------------------------

@router.get("/{video_id}/topics", response_model=list[TopicOut])
def get_topics(video_id: str, user: dict = Depends(get_current_user)):
    video = get_db()["videos"].find_one({"_id": to_oid(video_id)})
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found.")
    if video.get("status") != "ready":
        raise HTTPException(status_code=404, detail="Video is not ready yet.")
    data = load_output(video_id)
    topics = data.get("topics", [])
    return [
        TopicOut(index=i, start=t["start"], end=t["end"])
        for i, t in enumerate(topics)
    ]


@router.get("/{video_id}/topics/{topic_index}/question", response_model=QuestionOut)
def get_question(
    video_id: str,
    topic_index: int,
    try_number: int,
    user: dict = Depends(get_current_user),
):
    """Serve a question for the current try.

    Chooses randomly from the questions this student has NOT yet answered for
    this topic (using the attempts collection), never repeating the question
    shown immediately before. If a question was already served for this try,
    the same one is returned (so a refresh does not change it). The served
    question is recorded so POST /answers can verify it. Never returns
    correct_index or explanation.
    """
    data = load_output(video_id)
    topics = data.get("topics", [])
    if topic_index < 0 or topic_index >= len(topics):
        raise HTTPException(status_code=400, detail="topic_index out of range.")
    questions = topics[topic_index].get("questions", [])
    if not questions:
        raise HTTPException(status_code=404, detail="No questions for this topic.")

    n = len(questions)
    student_id = str(user["_id"])

    # If a question was already served for this try, return it unchanged.
    served = get_db()["served_questions"].find_one({
        "student_id": student_id,
        "video_id": video_id,
        "topic_index": topic_index,
        "try_number": try_number,
    })
    if served is not None:
        q_index = served["question_index"]
    else:
        # Questions the student has already answered for this topic.
        attempts = list(
            get_db()["attempts"]
            .find({"student_id": student_id, "video_id": video_id, "topic_index": topic_index})
            .sort("created_at", -1)
        )
        seen = {a["question_index"] for a in attempts}
        last_shown = attempts[0]["question_index"] if attempts else None
        all_indices = set(range(n))
        unseen = all_indices - seen

        if unseen:
            q_index = random.choice(list(unseen))
        elif n > 1:
            # All seen: reset, never repeat the immediately-before one.
            pool = all_indices - ({last_shown} if last_shown is not None else set())
            q_index = random.choice(list(pool)) if pool else random.choice(list(all_indices))
        else:
            q_index = 0  # only one question; must reuse it

        get_db()["served_questions"].insert_one({
            "student_id": student_id,
            "video_id": video_id,
            "topic_index": topic_index,
            "try_number": try_number,
            "question_index": q_index,
            "created_at": datetime.now(timezone.utc),
        })

    q = questions[q_index]
    return QuestionOut(question_index=q_index, prompt=q["prompt"], options=q["options"])


@router.get("/{video_id}/file")
def get_video_file(video_id: str, token: str, request: Request):
    # The <video> tag cannot send an Authorization header, so the token is
    # passed as a query parameter.
    user_from_token(token)
    video = get_db()["videos"].find_one({"_id": to_oid(video_id)})
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found.")
    path = video.get("video_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video file not found.")
    return _stream_file(path, request)


@router.delete("/{video_id}")
def delete_video(video_id: str, user: dict = Depends(require_role("teacher"))):
    """Delete a teacher's own video, its file, output JSON, and attempt records."""
    video = get_db()["videos"].find_one({"_id": to_oid(video_id)})
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found.")
    if video.get("teacher_email") != user.get("email"):
        raise HTTPException(
            status_code=403, detail="You can only delete your own videos."
        )

    # Delete the stored video file.
    vpath = video.get("video_path")
    if vpath and os.path.exists(vpath):
        try:
            os.remove(vpath)
        except OSError:
            pass
    # Delete the pipeline output JSON.
    out = output_path_for(video_id)
    if out.exists():
        try:
            os.remove(out)
        except OSError:
            pass
    # Delete attempt and served-question records for this video.
    get_db()["attempts"].delete_many({"video_id": video_id})
    get_db()["served_questions"].delete_many({"video_id": video_id})
    # Delete the video document.
    get_db()["videos"].delete_one({"_id": to_oid(video_id)})

    return {"deleted": video_id}
