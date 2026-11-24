"""Background job that runs the AI pipeline for an uploaded video.

Status transitions: transcribing -> analyzing -> generating -> ready,
or failed only if transcription or topic detection itself fails.

If question generation fails or returns nothing for a topic, that topic
is kept in the output with an empty questions list. The video is marked
ready as long as transcription and topic detection succeeded.
"""

import os
import sys
import traceback

from app.database import get_db
from app.models import PipelineOutput, TopicWithQuestions
from app.services.audio_extractor import extract_audio
from app.services.output_writer import write_output
from app.services.question_generator import generate_questions
from app.services.topic_detector import detect_topics
from app.services.transcriber import transcribe


def _log(msg: str) -> None:
    print(f"[pipeline_job] {msg}", file=sys.stderr, flush=True)


def _set_status(video_id, status: str, **extra) -> None:
    update = {"status": status}
    update.update(extra)
    get_db()["videos"].update_one({"_id": video_id}, {"$set": update})


def _topic_slice(transcript, topic) -> str:
    texts = []
    for seg in transcript.segments:
        if seg.start < topic.end and seg.end > topic.start:
            texts.append(seg.text)
    return " ".join(texts)


def run_pipeline_job(video_id, video_path: str, output_path: str) -> None:
    """Run the full pipeline for one uploaded video, updating its status."""
    _log(f"Starting pipeline for video {video_id} ({video_path})")
    wav_path = None
    try:
        # --- transcribing: extract audio + transcribe ---
        _set_status(video_id, "transcribing")
        _log("Stage 1/4 - transcribing: extracting audio")
        wav_path = extract_audio(video_path)
        _log("Stage 1/4 - transcribing: transcribing audio via Whisper")
        transcript = transcribe(wav_path)

        # --- analyzing: detect topics ---
        _set_status(video_id, "analyzing")
        _log("Stage 2/4 - analyzing: detecting topics")
        topics = detect_topics(transcript)

        # --- generating: question generation per topic ---
        _set_status(video_id, "generating")
        _log("Stage 3/4 - generating: creating questions per topic")
        topics_with_questions = []
        for i, topic in enumerate(topics, start=1):
            _log(f"  generating questions for topic {i}/{len(topics)}: {topic.keyword!r}")
            transcript_slice = _topic_slice(transcript, topic)
            questions = []
            try:
                questions = generate_questions(topic, transcript_slice)
            except Exception as qexc:  # noqa: BLE001
                _log(f"  question generation raised for topic {i}: {qexc}")
            if not questions:
                _log(f"  topic {i} ({topic.keyword!r}) has 0 questions — kept with empty list")
            topics_with_questions.append(
                TopicWithQuestions(
                    keyword=topic.keyword,
                    start=topic.start,
                    end=topic.end,
                    questions=questions,
                )
            )

        # --- ready: write output --- (always reached if transcription + detection succeeded)
        _log("Stage 4/4 - ready: writing output JSON")
        result = PipelineOutput(video_path=video_path, topics=topics_with_questions)
        write_output(result, output_path)
        _set_status(video_id, "ready", topic_count=len(topics_with_questions))
        topics_with_q = sum(1 for t in topics_with_questions if t.questions)
        _log(
            f"Pipeline complete: {len(topics_with_questions)} topics "
            f"({topics_with_q} with questions) -> {output_path}"
        )

    except Exception as exc:  # noqa: BLE001
        _log(f"FAILED: {exc}")
        _log(traceback.format_exc())
        get_db()["videos"].update_one(
            {"_id": video_id},
            {"$set": {"status": "failed", "error": str(exc)}},
        )
    finally:
        if wav_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except OSError as e:
                _log(f"Warning: could not delete temp audio file {wav_path}: {e}")
