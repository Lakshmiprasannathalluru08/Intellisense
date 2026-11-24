"""Stage 2: Transcription via the Groq Whisper API.

Exposes a single public function:
    transcribe(audio_path: str) -> TranscriptResult

Accepts any audio file Groq Whisper supports (mp3, flac, wav, ...) as
produced by the audio-extraction stage.

Retry strategy:
    attempt 1 — immediate
    attempt 2 — wait 2 s
    attempt 3 — wait 4 s
    attempt 4 — wait 8 s
    attempt 5 — wait 16 s
Total: 5 attempts; each Groq Whisper call has a 120-second timeout.

The GROQ_API_KEY is read from the environment.  The orchestrator has
already validated its presence before calling this module, so no
re-check is performed here (Requirement 2.3).
"""

import os
import sys
import time

from groq import Groq

from app.exceptions import TranscriptionError
from app.models import Segment, TranscriptResult, WordEntry

# Delays (seconds) between successive attempts.  Index i is the delay
# *before* attempt i+1.  Attempt 1 is always immediate.
_RETRY_DELAYS = [2, 4, 8, 16]
_MAX_ATTEMPTS = len(_RETRY_DELAYS) + 1  # 5 total attempts

# Per-call timeout (seconds) for the Groq Whisper request.
_WHISPER_TIMEOUT = 120

# Whisper model to use — turbo gives the best speed/accuracy trade-off.
_WHISPER_MODEL = "whisper-large-v3-turbo"


def _field(obj, key, default=None):
    """Read a field from a dict OR an SDK object.

    The Groq SDK may return transcript segments/words either as objects
    with attributes OR as plain dicts depending on the SDK version and
    response format.  Using ``getattr`` alone silently returns the default
    (e.g. 0.0) when a dict is involved, which produces zero-time, empty-text
    segments.  This helper handles both shapes.
    """
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _to_float(value, default=0.0):
    """Convert a value to float, accepting numbers and numeric strings.

    Returns *default* (never raising) for None, empty, or non-numeric input.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def transcribe(audio_path: str) -> TranscriptResult:
    """Call the Groq Whisper API and return a parsed TranscriptResult.

    Parameters
    ----------
    audio_path:
        Absolute or relative path to an audio file (mp3, flac, wav, ...)
        previously created by the audio-extraction stage.

    Returns
    -------
    TranscriptResult
        Contains one or more segments, each with word-level timestamps.

    Raises
    ------
    TranscriptionError
        * If all API attempts raise an exception (network, auth, timeout,
          server error, etc.).
        * If the API returns a response with zero segments.
    """
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    last_exc: Exception | None = None

    for attempt in range(_MAX_ATTEMPTS):
        # Wait before each retry.
        if attempt > 0:
            time.sleep(_RETRY_DELAYS[attempt - 1])

        try:
            with open(audio_path, "rb") as audio_file:
                response = client.audio.transcriptions.create(
                    file=(os.path.basename(audio_path), audio_file),
                    model=_WHISPER_MODEL,
                    response_format="verbose_json",
                    timestamp_granularities=["word", "segment"],
                    timeout=_WHISPER_TIMEOUT,
                )
        except Exception as exc:
            last_exc = exc
            continue  # retry

        # --- Parse the response ----------------------------------------
        # response may be an SDK object (use _field, which also handles dicts).
        raw_segments = _field(response, "segments", None) or []
        raw_words = _field(response, "words", None) or []

        # Zero-segment response is a hard error — no retry (Requirement 2.4).
        if len(raw_segments) == 0:
            raise TranscriptionError(
                "Groq Whisper returned a response with zero segments "
                f"for file '{audio_path}'."
            )

        # Group word-level entries by their containing segment.
        # Whisper may return words as a flat list at the top level
        # (timestamp_granularities=["word"]) rather than nested inside
        # each segment.  We handle both layouts.
        segment_words: dict[int, list[WordEntry]] = {
            i: [] for i in range(len(raw_segments))
        }

        for raw_word in raw_words:
            w_start = _to_float(_field(raw_word, "start"))
            w_end = _to_float(_field(raw_word, "end"))
            word_text = str(_field(raw_word, "word", "") or "")

            # Assign the word to the segment whose [start, end] contains
            # the word's midpoint.  Fall back to the last segment.
            midpoint = (w_start + w_end) / 2.0
            assigned = len(raw_segments) - 1
            for i, seg in enumerate(raw_segments):
                seg_start = _to_float(_field(seg, "start"))
                seg_end = _to_float(_field(seg, "end"))
                if seg_start <= midpoint <= seg_end:
                    assigned = i
                    break

            segment_words[assigned].append(
                WordEntry(word=word_text, start=w_start, end=w_end)
            )

        segments: list[Segment] = []
        for i, raw_seg in enumerate(raw_segments):
            # Try to pick up words nested directly on the segment object
            # first (some SDK versions include them there); if absent, use
            # the flat-list assignment computed above.
            nested = _field(raw_seg, "words", None)
            if nested:
                words = [
                    WordEntry(
                        word=str(_field(w, "word", "") or ""),
                        start=_to_float(_field(w, "start")),
                        end=_to_float(_field(w, "end")),
                    )
                    for w in nested
                ]
            else:
                words = segment_words.get(i, [])

            segments.append(
                Segment(
                    start=_to_float(_field(raw_seg, "start")),
                    end=_to_float(_field(raw_seg, "end")),
                    text=str(_field(raw_seg, "text", "") or "").strip(),
                    words=words,
                )
            )

        # --- Diagnostic: confirm we parsed real segment times/text -----
        print(
            f"[transcriber] Parsed {len(segments)} segment(s). "
            f"First segment: start={segments[0].start}, "
            f"end={segments[0].end}, "
            f"text={segments[0].text[:80]!r}",
            file=sys.stderr,
            flush=True,
        )

        return TranscriptResult(segments=segments)

    # All attempts raised exceptions.
    raise TranscriptionError(
        f"Groq Whisper API failed after {_MAX_ATTEMPTS} attempts for file "
        f"'{audio_path}'. Last error: {last_exc}"
    ) from last_exc
