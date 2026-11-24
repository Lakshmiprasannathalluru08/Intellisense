"""Question generation stage for the adaptive learning AI pipeline.

Stage 4: Generates 1-4 multiple-choice questions per topic using the Groq
LLM, using only that topic's transcript slice.
"""

import json
import os
import random
import re
import sys
import time
from typing import Any, List, Tuple

from groq import Groq

from app.exceptions import QuestionGenerationError
from app.models import Question, Topic


def validate_questions(data: Any) -> bool:
    """Return True iff data is a list of 1 to 4 question objects.

    Each object must have:
    - prompt: str
    - options: list of exactly 4 strings
    - correct_index: int in the range 0-3 inclusive
    - explanation: str

    Returns False (never raises) for any malformed or unexpected input.
    """
    try:
        if not isinstance(data, list):
            return False
        if not (1 <= len(data) <= 4):
            return False
        for item in data:
            if not isinstance(item, dict):
                return False
            if "prompt" not in item:
                return False
            if "options" not in item:
                return False
            if "correct_index" not in item:
                return False
            if "explanation" not in item:
                return False
            if not isinstance(item["prompt"], str):
                return False
            if not isinstance(item["options"], list):
                return False
            if len(item["options"]) != 4:
                return False
            for option in item["options"]:
                if not isinstance(option, str):
                    return False
            if not isinstance(item["correct_index"], int) or isinstance(item["correct_index"], bool):
                return False
            if item["correct_index"] < 0 or item["correct_index"] > 3:
                return False
            if not isinstance(item["explanation"], str):
                return False
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LLM_MODEL = os.environ.get("GROQ_LLM_MODEL", "openai/gpt-oss-20b")
_REQUEST_TIMEOUT = 30
_MAX_ATTEMPTS = 5
_RETRY_WAIT = 5
_MAX_TOKENS = 8000
_MAX_TOKENS_LENGTH = 12000
_CANDIDATE_COUNT = 8
_MAX_QUESTIONS = 4
_QUESTION_KINDS = ("definition", "example", "application", "why-how")


# ---------------------------------------------------------------------------
# Source-wording cleanup
# ---------------------------------------------------------------------------

# Phrases that reveal a question came from a transcript/excerpt.
_SOURCE_PHRASES = (
    "according to the",
    "the excerpt",
    "the transcript",
    "the passage",
    "the speaker",
    "what is said in the video",
    "in the video",
    "excerpt",
    "transcript",
    "passage",
)

# Pattern to strip a leading "According to the excerpt, " style clause.
_LEADING_RE = re.compile(
    r'^(?:according to (?:the )?[^,;:]+|in (?:the )?[^,;:]+|'
    r'as (?:mentioned|stated) [^,;:]+|based on (?:the )?[^,;:]+|'
    r'per (?:the )?[^,;:]+)[,;:]\s*',
    re.IGNORECASE,
)


def _has_forbidden_wording(q: dict) -> bool:
    """True if the prompt or explanation references the source text."""
    text = (str(q.get("prompt", "")) + " " + str(q.get("explanation", ""))).lower()
    return any(p in text for p in _SOURCE_PHRASES)


def _try_clean_question(q: dict) -> dict:
    """Return a copy of *q* with leading source-phrasing stripped from the prompt."""
    prompt = str(q.get("prompt", ""))
    m = _LEADING_RE.match(prompt)
    if m:
        rest = prompt[m.end():]
        cleaned = dict(q)
        cleaned["prompt"] = rest[0].upper() + rest[1:] if rest else rest
        return cleaned
    return q


def _select_questions(raw_candidates: List[dict], max_count: int = _MAX_QUESTIONS) -> List[dict]:
    """Select up to *max_count* questions, preferring one of each kind.

    Splits into clean and source-worded candidates, picks clean first.
    Within the clean pool, picks one per kind (definition, example,
    application, why-how) where possible, then fills remaining slots.
    Falls back to source-worded if fewer than 1 clean question exists.
    """
    clean: List[dict] = []
    sourcey: List[dict] = []
    for q in raw_candidates:
        if not isinstance(q, dict):
            continue
        if _has_forbidden_wording(q):
            sourcey.append(_try_clean_question(q))
        else:
            clean.append(q)
    pool = clean if clean else sourcey

    # Try to pick one of each kind first.
    selected: List[dict] = []
    used_indices: set = set()
    for kind in _QUESTION_KINDS:
        if len(selected) >= max_count:
            break
        for i, q in enumerate(pool):
            if i in used_indices:
                continue
            if (q.get("kind") or "").lower() == kind:
                selected.append(q)
                used_indices.add(i)
                break

    # Fill remaining slots with whatever is left (any kind, in order).
    for i, q in enumerate(pool):
        if len(selected) >= max_count:
            break
        if i not in used_indices:
            selected.append(q)
            used_indices.add(i)

    return selected[:max_count]


def _filter_questions_by_stars(
    questions: List[dict], min_count: int = 1, max_count: int = _MAX_QUESTIONS
) -> List[dict]:
    """Legacy helper kept for test compatibility. Returns up to max_count questions."""
    # With stars removed from prompts, all questions are treated equally.
    # We just filter out non-dicts and cap.
    result = [q for q in questions if isinstance(q, dict)]
    return result[:max_count]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _build_prompt(topic: Topic, transcript_slice: str) -> str:
    return (
        f'You are an educational assessment designer. The topic is: "{topic.keyword}".\n\n'
        f"Using ONLY the transcript excerpt below, generate {_CANDIDATE_COUNT} multiple-choice "
        "questions that test understanding of this topic. Return a "
        f"JSON array of exactly {_CANDIDATE_COUNT} objects. Each object must have "
        "exactly these five keys:\n"
        '  "prompt":        the question text (string),\n'
        '  "options":       an array of exactly 4 answer strings,\n'
        '  "correct_index": the 0-based index of the correct answer (integer 0-3),\n'
        '  "explanation":   a brief one-sentence explanation of the correct answer (string),\n'
        '  "kind":          one of "definition", "example", "application", or "why-how".\n\n'
        "Rules:\n"
        "- Return ONLY the JSON array — no markdown, no commentary, no extra keys.\n"
        "- Include different kinds: at least one definition, one example, one application, one why-how.\n"
        "- Write each question as a natural, standalone question. "
        "NEVER use phrases like 'according to the excerpt', 'according to the transcript', "
        "'in the excerpt', 'the speaker says', 'the teacher mentions', "
        "'as mentioned in the video' or 'in the passage'. "
        "A student must be able to answer it from knowing the concept. "
        "Wrong options must be plausible and clearly different from each other, and of similar length to the correct answer.\n"
        "- No stars, no ratings, no difficulty, no scores, no timestamps.\n\n"
        "Transcript excerpt:\n"
        f"{transcript_slice}"
    )


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    stripped = re.sub(r"^```[a-zA-Z]*\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _shuffle_options(options: List[str], correct_index: int) -> Tuple[List[str], int]:
    """Randomly shuffle options and return (shuffled, new_correct_index)."""
    indexed = list(enumerate(options))
    random.shuffle(indexed)
    shuffled = [text for _, text in indexed]
    new_correct_index = next(
        i for i, (orig_idx, _) in enumerate(indexed) if orig_idx == correct_index
    )
    return shuffled, new_correct_index


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_questions(topic: Topic, transcript_slice: str) -> List[Question]:
    """Generate 1 to 4 multiple-choice questions for *topic*.

    Returns an empty list when all retries produce no valid questions.
    Never raises — the pipeline_job is responsible for handling empty results.
    """
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    prompt = _build_prompt(topic, transcript_slice)

    last_error: str = "Unknown error"
    max_tokens = _MAX_TOKENS

    for attempt in range(_MAX_ATTEMPTS):
        if attempt > 0:
            time.sleep(_RETRY_WAIT)

        try:
            response = client.chat.completions.create(
                model=_LLM_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a precise JSON-only responder. "
                            "Output nothing except the requested JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                timeout=_REQUEST_TIMEOUT,
                max_completion_tokens=max_tokens,
                reasoning_effort="low",
            )
        except Exception as exc:  # noqa: BLE001
            last_error = f"API error: {exc}"
            print(
                f"[question_generator] Attempt {attempt + 1}/{_MAX_ATTEMPTS} failed (API error): {exc}",
                file=sys.stderr,
            )
            continue

        choice = response.choices[0]
        raw_content: str = choice.message.content or ""
        finish_reason = getattr(choice, "finish_reason", None)
        usage = getattr(response, "usage", None)
        if not raw_content.strip():
            last_error = f"empty model reply (finish_reason={finish_reason})"
            print(
                f"[question_generator] Attempt {attempt + 1}/{_MAX_ATTEMPTS} returned an "
                f"empty reply. finish_reason={finish_reason}, usage={usage}",
                file=sys.stderr, flush=True,
            )
            max_tokens = _MAX_TOKENS_LENGTH if str(finish_reason).lower() == "length" else _MAX_TOKENS
            continue

        clean_content = _strip_code_fences(raw_content)
        try:
            data = json.loads(clean_content)
        except json.JSONDecodeError as exc:
            last_error = f"JSON parse error: {exc}"
            print(
                f"[question_generator] Attempt {attempt + 1}/{_MAX_ATTEMPTS} failed (JSON parse): {exc}",
                file=sys.stderr,
            )
            continue

        if not isinstance(data, list):
            last_error = "Response was not a JSON array."
            print(
                f"[question_generator] Attempt {attempt + 1}/{_MAX_ATTEMPTS} failed: {last_error}",
                file=sys.stderr,
            )
            continue

        kept = _select_questions(data)

        if not validate_questions(kept):
            last_error = (
                "Question validation failed (need 1-4 valid questions; "
                "missing fields, bad types or correct_index out of range)"
            )
            print(
                f"[question_generator] Attempt {attempt + 1}/{_MAX_ATTEMPTS} failed (validation): "
                "filtered questions did not pass validate_questions.",
                file=sys.stderr,
            )
            continue

        questions: List[Question] = []
        for q in kept:
            options = [str(o) for o in q["options"]]
            correct_index = int(q["correct_index"])
            shuffled_options, new_correct_index = _shuffle_options(options, correct_index)
            questions.append(
                Question(
                    prompt=str(q["prompt"]),
                    options=shuffled_options,
                    correct_index=new_correct_index,
                    explanation=str(q["explanation"]),
                    kind=str(q.get("kind", "")).lower(),
                )
            )
        return questions

    # All attempts exhausted — return empty list instead of raising.
    # The pipeline_job logs this and stores the topic with an empty questions list.
    print(
        f"[question_generator] All {_MAX_ATTEMPTS} attempts failed for topic "
        f'"{topic.keyword}". Returning empty list. Last error: {last_error}',
        file=sys.stderr,
    )
    return []
