"""Topic detection stage for the adaptive learning AI pipeline.

Architecture (new):
- The code splits the transcript into N sections of equal duration, with
  cuts snapped to the nearest full-stop segment within ±20 s.
- The whole transcript is sent to the LLM (with section markers, no times).
- The LLM returns exactly one keyword per section.
- Each section's end time is computed entirely in code from segment timestamps.
- Times are never sent to or returned from the model.
- If the LLM fails, the first full sentence of each section is used as keyword.

Public API:
  detect_topics(transcript) -> List[Topic]
"""

import json
import os
import re
import sys
import time
from typing import Any, List, Optional, Tuple

from groq import Groq

from app.exceptions import TopicDetectionError
from app.models import Segment, Topic, TranscriptResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LLM_MODEL = os.environ.get("GROQ_LLM_MODEL", "openai/gpt-oss-20b")
_MAX_ATTEMPTS = 5
_RETRY_WAIT = 5
_MAX_TOKENS = 8000
_MAX_TOKENS_LENGTH = 12000

_SENTENCE_ENDINGS = frozenset(".?!")
# Max seconds to search either side of an ideal cut point for a full stop.
_CUT_WINDOW = 20.0


# ---------------------------------------------------------------------------
# Target N — mandatory, based on video length
# ---------------------------------------------------------------------------

def target_n(transcript: TranscriptResult) -> int:
    """Return the mandatory number of pop-up sections based on video length."""
    if not transcript.segments:
        return 2
    last_end = transcript.segments[-1].end
    minutes = last_end / 60.0
    if minutes < 3:
        return 2
    elif minutes < 5:
        return 3
    elif minutes < 11:
        return 4
    elif minutes < 16:
        return 6
    elif minutes < 21:
        return 8
    else:
        return 9


# ---------------------------------------------------------------------------
# Sentence-end helpers
# ---------------------------------------------------------------------------

def _ends_with_sentence(seg: Segment) -> bool:
    """True if the segment's text ends with '.', '?' or '!'."""
    text = (seg.text or "").rstrip()
    return bool(text) and text[-1] in _SENTENCE_ENDINGS


def _seg_end(seg: Segment) -> float:
    """Return the last word's end time, falling back to segment.end."""
    return seg.words[-1].end if seg.words else seg.end


def _seg_start(seg: Segment) -> float:
    """Return the first word's start time, falling back to segment.start."""
    return seg.words[0].start if seg.words else seg.start


# ---------------------------------------------------------------------------
# Section splitting
# ---------------------------------------------------------------------------

def _split_transcript(
    transcript: TranscriptResult, n: int
) -> List[Tuple[List[Segment], float, float]]:
    """Split the transcript into *n* sections of roughly equal duration.

    Each cut is moved to the nearest segment whose text ends with a sentence-
    ending character (within ±_CUT_WINDOW seconds), preferring the segment
    that leaves the longest gap before the next one (i.e. the best natural
    pause).

    Returns a list of (segments, start_time, end_time) tuples — one per
    section — where end_time is the last-word end of the final segment in
    that section.  The first section starts at the first segment and the
    last ends at the last segment.  No gaps, no overlaps.
    """
    segs = transcript.segments
    if not segs:
        return []
    if n <= 1:
        end = _seg_end(segs[-1])
        return [(segs, segs[0].start, end)]

    total_start = segs[0].start
    total_end = segs[-1].end
    total_dur = total_end - total_start
    section_dur = total_dur / n

    # Compute ideal cut points (times) between sections.
    ideal_cuts = [total_start + section_dur * i for i in range(1, n)]

    # Snap each cut to the nearest full-stop segment within ±_CUT_WINDOW s.
    def _best_cut_seg(ideal_time: float) -> Optional[int]:
        """Return the index of the best segment to cut after, or None."""
        candidates = []
        for i, seg in enumerate(segs):
            if not _ends_with_sentence(seg):
                continue
            # The segment must end within the window of the ideal cut.
            if abs(seg.end - ideal_time) <= _CUT_WINDOW:
                candidates.append((i, seg))
        if not candidates:
            # Fallback: closest segment regardless of full-stop.
            best_i = min(range(len(segs)), key=lambda i: abs(segs[i].end - ideal_time))
            return best_i
        # Among full-stop candidates, prefer the one whose end is closest to
        # the ideal cut.  Break ties by preferring the later one (more content).
        candidates.sort(key=lambda x: (abs(x[1].end - ideal_time), -x[1].end))
        return candidates[0][0]

    cut_indices: List[int] = []
    for ideal_time in ideal_cuts:
        idx = _best_cut_seg(ideal_time)
        if idx is not None:
            cut_indices.append(idx)

    # Deduplicate and sort, ensuring strictly increasing cuts.
    seen: set = set()
    unique_cuts: List[int] = []
    for idx in sorted(cut_indices):
        if idx not in seen and (not unique_cuts or idx > unique_cuts[-1]):
            seen.add(idx)
            unique_cuts.append(idx)

    # Build the sections from the cut indices.
    sections = []
    prev_end_idx = -1
    for cut_idx in unique_cuts:
        section_segs = segs[prev_end_idx + 1: cut_idx + 1]
        if section_segs:
            start = section_segs[0].start
            end = _seg_end(section_segs[-1])
            sections.append((section_segs, start, end))
        prev_end_idx = cut_idx

    # Last section: everything after the last cut.
    tail_segs = segs[prev_end_idx + 1:]
    if tail_segs:
        start = tail_segs[0].start
        end = _seg_end(tail_segs[-1])
        sections.append((tail_segs, start, end))
    elif sections:
        # If the last cut was the very last segment, absorb it into the last section.
        last_segs, last_start, _ = sections[-1]
        end = _seg_end(segs[-1])
        sections[-1] = (last_segs, last_start, end)

    # Pad or trim to exactly n sections.
    while len(sections) < n and sections:
        # Duplicate the last section (keywords will differ due to retry logic).
        sections.append(sections[-1])
    sections = sections[:n]

    # Force the last section to end at the video end (last word of last segment).
    if sections:
        last_segs, last_start, _ = sections[-1]
        video_end = _seg_end(segs[-1])
        sections[-1] = (last_segs, last_start, video_end)

    return sections


# ---------------------------------------------------------------------------
# LLM concept identification
# ---------------------------------------------------------------------------

def _build_prompt(sections: List[Tuple[List[Segment], float, float]]) -> str:
    """Build the prompt that asks the LLM for one concept per section.

    No times are included.  Segments are numbered and annotated with their
    section header.
    """
    n = len(sections)
    lines = []
    global_line = 1
    for sec_i, (segs, _, _) in enumerate(sections, start=1):
        lines.append(f"--- SECTION {sec_i} of {n} ---")
        for seg in segs:
            lines.append(f"Line {global_line}: {seg.text}")
            global_line += 1

    transcript_text = "\n".join(lines)

    return (
        f"Read the whole lesson from the FIRST line to the LAST line before "
        f"answering. Then return EXACTLY {n} concepts, one for each section, "
        f"in order. Concept 1 must come from the beginning of the lesson and "
        f"concept {n} must come from the end of the lesson. "
        f"For each section, name the ONE main important concept the teacher "
        f"explains there, including its definition, examples and applications. "
        f"Every section must get a concept, especially the second half of the "
        f"lesson. Do not take two concepts from the same part of the lesson.\n\n"
        f"A concept includes its definition, ALL of its examples, and ALL of its "
        f"applications. Do not start a new concept for an example, an analogy, "
        f"a use case or an application of the current concept.\n\n"
        f'Return JSON: {{"concepts":[{{"section":1,"keyword":"..."}}]}}\n\n'
        f"Rules:\n"
        f'- Return EXACTLY {n} objects in the concepts array, one per section.\n'
        f'- "section": integer 1 to {n}.\n'
        f'- "keyword": a concise label for the concept (1-60 characters).\n'
        f"- No times, no line numbers, no extra keys in the output.\n"
        f"- Output ONLY the JSON object, nothing else.\n\n"
        f"Lesson transcript:\n{transcript_text}"
    )


def _parse_concepts(raw: str, n: int) -> Optional[List[Optional[str]]]:
    """Parse the LLM response into a list of n keywords (some may be None).

    Returns None if the JSON cannot be parsed at all.
    """
    # Strip code fences.
    text = raw.strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    # Accept {"concepts":[...]} or bare list.
    if isinstance(parsed, dict):
        concepts_list = parsed.get("concepts")
    elif isinstance(parsed, list):
        concepts_list = parsed
    else:
        return None

    if not isinstance(concepts_list, list):
        return None

    keywords: List[Optional[str]] = [None] * n
    for item in concepts_list:
        if not isinstance(item, dict):
            continue
        sec = item.get("section")
        kw = item.get("keyword")
        if not isinstance(sec, int) or not (1 <= sec <= n):
            continue
        if isinstance(kw, str) and 1 <= len(kw.strip()) <= 60:
            keywords[sec - 1] = kw.strip()
    return keywords


def _fallback_keyword(segs: List[Segment]) -> str:
    """Return the first full sentence of *segs* as a keyword (up to 60 chars).

    Falls back to the first segment's text if no sentence-ending segment is
    found.
    """
    for seg in segs:
        if _ends_with_sentence(seg):
            text = seg.text.strip()
            if len(text) <= 60:
                return text
            truncated = text[:60].rsplit(" ", 1)[0]
            return truncated or text[:60]
    # No full stop found — use the first segment's text.
    text = (segs[0].text if segs else "").strip()
    if len(text) <= 60:
        return text or "Introduction"
    truncated = text[:60].rsplit(" ", 1)[0]
    return truncated or text[:60]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_topics(transcript: TranscriptResult) -> List[Topic]:
    """Detect exactly N topics from a Whisper transcript.

    N is determined by video length (target_n).  The transcript is split into
    N sections in code, then the LLM is asked for one concept keyword per
    section.  Times are never sent to the model.

    Returns a list of exactly N Topic objects.  Raises TopicDetectionError
    only when the transcript is empty; otherwise always returns N topics.
    """
    if not transcript.segments:
        raise TopicDetectionError("Cannot detect topics: transcript has no segments.")

    n = target_n(transcript)
    sections = _split_transcript(transcript, n)

    # If splitting produced fewer than n sections (e.g. very short transcript),
    # pad with copies of the last section.
    while len(sections) < n:
        sections.append(sections[-1])
    sections = sections[:n]

    print(
        f"[topic_detector] Targeting {n} sections "
        f"(video ~{transcript.segments[-1].end / 60:.1f} min).",
        file=sys.stderr, flush=True,
    )

    prompt = _build_prompt(sections)
    print(
        f"[topic_detector] Prompt (first 500 chars):\n{prompt[:500]}",
        file=sys.stderr, flush=True,
    )

    # We start with all keywords missing.
    keywords: List[Optional[str]] = [None] * n
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    max_tokens = _MAX_TOKENS

    for attempt in range(_MAX_ATTEMPTS):
        if attempt > 0:
            time.sleep(_RETRY_WAIT)

        # On retries, ask again for all missing sections.
        missing = [i + 1 for i, kw in enumerate(keywords) if kw is None]
        if not missing:
            break

        if attempt == 0:
            user_content = prompt
        else:
            user_content = (
                f"Your previous response was missing sections: {missing}.\n"
                f"Return ONLY a JSON object with a 'concepts' array containing "
                f"entries for the missing sections only.\n"
                f'Format: {{"concepts":[{{"section":N,"keyword":"..."}}]}}\n\n'
                + prompt
            )

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
                    {"role": "user", "content": user_content},
                ],
                max_completion_tokens=max_tokens,
                reasoning_effort="low",
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"[topic_detector] Attempt {attempt + 1}/{_MAX_ATTEMPTS} API error: {exc}",
                file=sys.stderr,
            )
            continue

        choice = response.choices[0]
        raw_content: str = choice.message.content or ""
        finish_reason = getattr(choice, "finish_reason", None)
        if not raw_content.strip():
            print(
                f"[topic_detector] Attempt {attempt + 1}/{_MAX_ATTEMPTS} empty reply "
                f"(finish_reason={finish_reason}).",
                file=sys.stderr, flush=True,
            )
            max_tokens = _MAX_TOKENS_LENGTH if str(finish_reason).lower() == "length" else _MAX_TOKENS
            continue

        parsed = _parse_concepts(raw_content, n)
        if parsed is None:
            print(
                f"[topic_detector] Attempt {attempt + 1}/{_MAX_ATTEMPTS} could not "
                f"parse response.",
                file=sys.stderr,
            )
            continue

        # Merge newly received keywords into our running list.
        for i, kw in enumerate(parsed):
            if kw is not None and keywords[i] is None:
                keywords[i] = kw

    # Fill any remaining None keywords with the section's first full sentence.
    for i, kw in enumerate(keywords):
        if kw is None:
            segs_for_section, _, _ = sections[i]
            kw = _fallback_keyword(segs_for_section)
            print(
                f"[topic_detector] Section {i + 1}: using fallback keyword {kw!r}.",
                file=sys.stderr,
            )
            keywords[i] = kw

    # Build Topic objects: start and end come entirely from the section splits.
    topics: List[Topic] = []
    for i, (segs, start, end) in enumerate(sections):
        # Each non-last topic: snap end to the last full-stop within the section.
        if i < n - 1:
            # Walk back from section end to the last full-stop segment.
            for seg in reversed(segs):
                if _ends_with_sentence(seg):
                    end = _seg_end(seg)
                    break
        # Ensure end > start.
        if end <= start:
            end = _seg_end(segs[-1]) if segs else start + 1.0
        topics.append(Topic(
            keyword=str(keywords[i]),
            start=float(start),
            end=float(end),
        ))

    # Close gaps: each topic's start = previous topic's end.
    for i in range(1, len(topics)):
        topics[i] = Topic(
            keyword=topics[i].keyword,
            start=topics[i - 1].end,
            end=topics[i].end,
        )

    # Force the last topic to the video end.
    video_end = _seg_end(transcript.segments[-1])
    if topics:
        last = topics[-1]
        topics[-1] = Topic(keyword=last.keyword, start=last.start, end=video_end)

    print(
        f"[topic_detector] Final topics: "
        + ", ".join(f'"{t.keyword}" [{t.start:.1f}-{t.end:.1f}]' for t in topics),
        file=sys.stderr, flush=True,
    )
    return topics
