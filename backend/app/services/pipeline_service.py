"""Pipeline orchestrator for the adaptive learning AI pipeline.

Drives all five stages in sequence:
  1. Audio extraction  (audio_extractor.extract_audio)
  2. Transcription     (transcriber.transcribe)
  3. Topic detection   (topic_detector.detect_topics)
  4. Question generation per topic (question_generator.generate_questions)
  5. Output persistence (output_writer.write_output)

Environment:
    GROQ_API_KEY must be set (non-empty) in the environment or in
    ``backend/.env`` before calling run_pipeline.  The function loads
    .env via python-dotenv at startup and raises ConfigurationError
    immediately if the key is absent or empty (Requirement 5.4).

Temp-file cleanup:
    The WAV file created by extract_audio is deleted in a ``finally``
    block regardless of whether the pipeline succeeds or fails
    (Requirement 1.4).
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from app.exceptions import ConfigurationError
from app.models import PipelineOutput, TopicWithQuestions
from app.services.audio_extractor import extract_audio
from app.services.output_writer import write_output
from app.services.question_generator import generate_questions
from app.services.topic_detector import detect_topics
from app.services.transcriber import transcribe


def _load_env() -> None:
    """Load environment variables from backend/.env if present.

    Uses python-dotenv so that the file is optional — if .env does not
    exist the function is a no-op and the calling process's environment
    is used as-is.
    """
    # Walk up from this file to find backend/.env regardless of the
    # working directory the caller used.
    this_dir = Path(__file__).resolve().parent          # .../backend/app/services
    backend_dir = this_dir.parent.parent                # .../backend
    env_path = backend_dir / ".env"
    load_dotenv(dotenv_path=env_path, override=False)


def _check_api_key() -> None:
    """Raise ConfigurationError if GROQ_API_KEY is absent or empty.

    Prints the missing variable name to stderr before raising, as
    required by Requirement 5.4.
    """
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        msg = (
            "Configuration error: GROQ_API_KEY is absent or empty. "
            "Set it in your environment or in backend/.env before running the pipeline."
        )
        print(f"[pipeline_service] {msg}", file=sys.stderr)
        raise ConfigurationError(msg)


def _extract_transcript_slice(transcript, topic) -> str:
    """Return the joined text of all segments that overlap with *topic*.

    A segment overlaps a topic when their time ranges intersect, i.e.
    ``segment.start < topic.end and segment.end > topic.start``.

    Parameters
    ----------
    transcript:
        A TranscriptResult produced by the transcription stage.
    topic:
        A Topic dataclass produced by the topic detection stage.

    Returns
    -------
    str
        A single string of segment texts joined by spaces.  Returns an
        empty string if no segments overlap (which should not occur for
        well-formed pipeline data).
    """
    texts = []
    for segment in transcript.segments:
        # Standard interval-overlap test: two intervals [a,b] and [c,d]
        # overlap when a < d and c < b.
        if segment.start < topic.end and segment.end > topic.start:
            texts.append(segment.text)
    return " ".join(texts)


def run_pipeline(video_path: str, output_path: str) -> PipelineOutput:
    """Run the full AI pipeline and return the completed PipelineOutput.

    Stages
    ------
    1. Load .env and validate GROQ_API_KEY.
    2. Extract audio from *video_path* to a temporary WAV file.
    3. Transcribe the WAV via Groq Whisper → TranscriptResult.
    4. Detect topics via Groq LLM → list[Topic] (as many as the content has).
    5. For each topic, derive its transcript slice and generate 4 questions.
    6. Build PipelineOutput and write it to *output_path*.
    7. Return the PipelineOutput.

    The temporary WAV file is deleted in a ``finally`` block regardless
    of success or failure.

    Parameters
    ----------
    video_path:
        Path to the input video file.
    output_path:
        Destination path for the JSON output file.

    Returns
    -------
    PipelineOutput
        The complete pipeline result, also persisted to *output_path*.

    Raises
    ------
    ConfigurationError
        If GROQ_API_KEY is absent or empty.
    PipelineError (or any subclass)
        If any pipeline stage fails.
    """
    # --- Stage 0: environment validation ---------------------------------
    _load_env()
    _check_api_key()

    wav_path: str | None = None
    try:
        # --- Stage 1: audio extraction -----------------------------------
        print(
            f"[pipeline_service] Stage 1/5 — Extracting audio from '{video_path}' …",
            flush=True,
        )
        wav_path = extract_audio(video_path)
        print(
            f"[pipeline_service] Stage 1/5 — Audio extracted to '{wav_path}'.",
            flush=True,
        )

        # --- Stage 2: transcription --------------------------------------
        print(
            "[pipeline_service] Stage 2/5 — Transcribing audio via Groq Whisper …",
            flush=True,
        )
        transcript = transcribe(wav_path)
        print(
            f"[pipeline_service] Stage 2/5 — Transcription complete "
            f"({len(transcript.segments)} segment(s)).",
            flush=True,
        )

        # --- Stage 3: topic detection ------------------------------------
        print(
            "[pipeline_service] Stage 3/5 — Detecting topics via Groq LLM …",
            flush=True,
        )
        topics = detect_topics(transcript)
        print(
            f"[pipeline_service] Stage 3/5 — Detected {len(topics)} topic(s): "
            + ", ".join(f'"{t.keyword}"' for t in topics),
            flush=True,
        )

        # --- Stage 4: question generation --------------------------------
        print(
            "[pipeline_service] Stage 4/5 — Generating questions for each topic …",
            flush=True,
        )
        topics_with_questions = []
        for i, topic in enumerate(topics, start=1):
            print(
                f"[pipeline_service]   Topic {i}/{len(topics)}: "
                f'"{topic.keyword}" [{topic.start:.2f}s – {topic.end:.2f}s] …',
                flush=True,
            )
            transcript_slice = _extract_transcript_slice(transcript, topic)
            questions = generate_questions(topic, transcript_slice)
            topics_with_questions.append(
                TopicWithQuestions(
                    keyword=topic.keyword,
                    start=topic.start,
                    end=topic.end,
                    questions=questions,
                )
            )
        print(
            "[pipeline_service] Stage 4/5 — Question generation complete.",
            flush=True,
        )

        # --- Stage 5: output persistence ---------------------------------
        print(
            f"[pipeline_service] Stage 5/5 — Writing output to '{output_path}' …",
            flush=True,
        )
        result = PipelineOutput(
            video_path=video_path,
            topics=topics_with_questions,
        )
        write_output(result, output_path)
        print(
            f"[pipeline_service] Stage 5/5 — Output written successfully to '{output_path}'.",
            flush=True,
        )

        print(
            "[pipeline_service] Pipeline completed successfully.",
            flush=True,
        )
        return result

    finally:
        # Always clean up the temporary WAV file (Requirement 1.4).
        if wav_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
                print(
                    f"[pipeline_service] Cleaned up temporary WAV file '{wav_path}'.",
                    flush=True,
                )
            except OSError as exc:
                # Non-fatal: log and continue — the pipeline result is not
                # affected by a cleanup failure.
                print(
                    f"[pipeline_service] Warning: could not delete temp WAV "
                    f"file '{wav_path}': {exc}",
                    file=sys.stderr,
                )
