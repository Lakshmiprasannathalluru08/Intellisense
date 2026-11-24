"""Shared data models for the adaptive learning AI pipeline."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class WordEntry:
    """A single word with its timestamp from Whisper's word-level output."""
    word: str
    start: float  # seconds
    end: float    # seconds


@dataclass
class Segment:
    """A transcript segment from Whisper, containing words and timing."""
    start: float          # seconds
    end: float            # seconds
    text: str
    words: List[WordEntry]


@dataclass
class TranscriptResult:
    """The full transcript returned by the Groq Whisper API.

    Invariant: len(segments) >= 1
    """
    segments: List[Segment]


@dataclass
class Topic:
    """A single topic identified by the LLM topic detector.

    keyword is 1–60 characters.
    end is snapped to the nearest Whisper segment boundary.
    """
    keyword: str   # 1–60 characters
    start: float   # seconds
    end: float     # seconds, snapped to nearest segment boundary


@dataclass
class Question:
    """A single multiple-choice question produced by the question generator."""
    prompt: str
    options: List[str]   # exactly 4 elements
    correct_index: int   # 0–3 inclusive
    explanation: str
    stars: int = 3       # importance 1-3; saved to JSON, never sent to the browser
    kind: str = ""       # definition | example | application | why-how; never sent to browser


@dataclass
class TopicWithQuestions:
    """A topic paired with its generated questions."""
    keyword: str
    start: float
    end: float
    questions: List[Question]  # exactly 4


@dataclass
class PipelineOutput:
    """The complete output of a single pipeline run, written to disk as JSON."""
    video_path: str
    topics: List[TopicWithQuestions]  # exactly 4, in chronological order
