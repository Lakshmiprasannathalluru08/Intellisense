# Implementation Plan: Adaptive Learning Platform — AI Pipeline Module

## Overview

Build the standalone Python AI pipeline in `backend/`, implementing five sequential stages (audio extraction → transcription → topic detection → question generation → JSON output), the CLI entry point, the FastAPI background-job wrapper, and a full test suite. The implementation follows the component order defined in the design document and wires everything together through `pipeline_service.py`.

---

## Tasks

- [x] 1. Scaffold project structure, environment config, and shared data models
  - Create all directories: `backend/app/services/`, `backend/app/jobs/`, `backend/app/tests/`
  - Create `backend/.env.example` with empty values: `GROQ_API_KEY=`, `MONGODB_URI=`, `MONGODB_DB_NAME=learning_assessment`, `JWT_SECRET=`
  - Create `backend/requirements.txt` listing: `groq`, `python-dotenv`, `hypothesis`, `pytest`, `ffmpeg-python` (or use subprocess for ffmpeg directly)
  - Add `backend/.env` to the root `.gitignore`
  - Create `backend/app/models.py` defining all dataclasses: `WordEntry`, `Segment`, `TranscriptResult`, `Topic`, `Question`, `TopicWithQuestions`, `PipelineOutput`
  - Create `backend/app/exceptions.py` defining: `PipelineError` base class and all subclasses (`AudioExtractionError`, `TranscriptionError`, `TopicDetectionError`, `QuestionGenerationError`, `OutputWriteError`, `ConfigurationError`)
  - Add `backend/app/__init__.py`, `backend/app/services/__init__.py`, `backend/app/jobs/__init__.py`, `backend/app/tests/__init__.py`
  - _Requirements: 5.1, 5.2, 5.3, 5.5_

- [x] 2. Implement audio extraction stage
  - [x] 2.1 Implement `backend/app/services/audio_extractor.py`
    - Write `extract_audio(video_path: str) -> str` using `subprocess` to invoke ffmpeg
    - Generate a unique temporary WAV file path with `tempfile.mkstemp`
    - Raise `AudioExtractionError` on non-zero ffmpeg exit code or zero-duration output (probe duration with ffprobe or check file size as a proxy)
    - Do not delete the temp file inside this function — the caller (orchestrator) owns cleanup
    - _Requirements: 1.1, 1.2, 1.3_

  - [ ]* 2.2 Write unit tests for audio extractor
    - Test that a non-zero ffmpeg exit code raises `AudioExtractionError`
    - Test that a zero-duration WAV raises `AudioExtractionError`
    - Use `unittest.mock.patch` to mock `subprocess.run` without invoking real ffmpeg
    - _Requirements: 1.2, 1.3_

- [x] 3. Implement transcription stage
  - [x] 3.1 Implement `backend/app/services/transcriber.py`
    - Write `transcribe(wav_path: str) -> TranscriptResult`
    - Read `GROQ_API_KEY` from environment (already validated by orchestrator — no re-check needed here)
    - Call the Groq Whisper API; parse response into `Segment` / `WordEntry` dataclasses
    - Implement exponential back-off retry: attempt 1 immediate, attempt 2 after 1 s, attempt 3 after 2 s (3 attempts total)
    - Raise `TranscriptionError` after all retries exhausted, or immediately on zero-segment response
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [ ]* 3.2 Write unit tests for transcriber
    - Test that the retry loop fires up to 3 times on API error and then raises `TranscriptionError`
    - Test that a zero-segment response raises `TranscriptionError` without retrying
    - Mock the Groq client so no real API calls are made
    - _Requirements: 2.2, 2.4_

- [x] 4. Implement topic detection stage
  - [x] 4.1 Implement `validate_topics` in `backend/app/services/topic_detector.py`
    - Write `validate_topics(data: Any) -> bool`
    - Return `True` only when `data` is a list of exactly 4 objects, each with `keyword` (str, 1–60 chars), `start` (number), `end` (number), topics in chronological order, and no overlapping time ranges
    - Catch all exceptions internally; always return `bool`, never raise
    - _Requirements: 3.2, 3.3_

  - [x] 4.2 Implement `snap_end_time` in `backend/app/services/topic_detector.py`
    - Write `snap_end_time(raw_end: float, segments: list[Segment]) -> float`
    - Return the segment end time with minimum `|segment.end - raw_end|`; on a tie, return the later (larger) value
    - Pure function — no side effects, no mutations
    - _Requirements: 3.5_

  - [ ]* 4.3 Write property test for `snap_end_time` — Property 1: Snap idempotence
    - **Property 1: Snap idempotence**
    - **Validates: Requirements 6.6**
    - Add to `backend/app/tests/test_snapping.py`
    - Use `@given` with a list of segments (1–20 entries, positive-float `end` times) and a random `raw_end`
    - Assert `snap(snap(raw_end, segs), segs) == snap(raw_end, segs)`
    - Tag: `# Feature: adaptive-learning-platform, Property 1: Snap idempotence`

  - [ ]* 4.4 Write property test for `snap_end_time` — Property 2: Snap selects a valid segment end
    - **Property 2: Snap selects a valid segment end**
    - **Validates: Requirements 3.5**
    - Add to `backend/app/tests/test_snapping.py`
    - Assert the return value is a member of `{s.end for s in segments}`
    - Tag: `# Feature: adaptive-learning-platform, Property 2: Snap selects a valid segment end`

  - [ ]* 4.5 Write property test for `snap_end_time` — Property 3: Snap minimises distance
    - **Property 3: Snap minimises distance**
    - **Validates: Requirements 3.5**
    - Add to `backend/app/tests/test_snapping.py`
    - Assert `|result - raw_end| <= |seg.end - raw_end|` for every segment in the list
    - Tag: `# Feature: adaptive-learning-platform, Property 3: Snap minimises distance`

  - [ ]* 4.6 Write property test for `snap_end_time` — Property 4: Snap tie-breaking selects later time
    - **Property 4: Snap tie-breaking selects later time**
    - **Validates: Requirements 3.5**
    - Add to `backend/app/tests/test_snapping.py`
    - Generate a list where ≥2 segments are equidistant from `raw_end`; assert the returned value is `max(equidistant_ends)`
    - Tag: `# Feature: adaptive-learning-platform, Property 4: Snap tie-breaking selects later time`

  - [x] 4.7 Implement `detect_topics` in `backend/app/services/topic_detector.py`
    - Write `detect_topics(transcript: TranscriptResult) -> list[Topic]`
    - Send the full transcript to the Groq LLM requesting strict JSON with exactly 4 topic objects
    - Validate the response with `validate_topics`; retry up to 3 times on failure (discard partial results)
    - Snap each topic's `end` time using `snap_end_time`
    - After snapping, verify that end times are strictly ascending; raise `TopicDetectionError` if not
    - Raise `TopicDetectionError` if all 3 attempts fail validation
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [ ]* 4.8 Write property test for `validate_topics` — Property 5: Topic validation rejects structurally invalid inputs
    - **Property 5: Topic validation rejects structurally invalid inputs**
    - **Validates: Requirements 3.2, 3.3**
    - Add to `backend/app/tests/test_topic_validation.py`
    - Generate randomly malformed topic lists (wrong count, missing fields, bad types, overlapping ranges); assert `validate_topics(data) is False` and no exception is raised
    - Tag: `# Feature: adaptive-learning-platform, Property 5: Topic validation rejects structurally invalid inputs`

- [x] 5. Implement question generation stage
  - [x] 5.1 Implement `validate_questions` in `backend/app/services/question_generator.py`
    - Write `validate_questions(data: Any) -> bool`
    - Return `True` only when `data` is a list of exactly 4 objects, each with `prompt` (str), `options` (list of exactly 4 strings), `correct_index` (int, 0–3), and `explanation` (str)
    - Catch all exceptions internally; always return `bool`, never raise
    - _Requirements: 4.2_

  - [ ]* 5.2 Write property test for `validate_questions` — Property 6: Rejects out-of-range correct_index
    - **Property 6: Question validation rejects out-of-range correct_index**
    - **Validates: Requirements 4.2, 4.3**
    - Add to `backend/app/tests/test_question_validation.py`
    - Generate question objects with `correct_index` drawn from integers outside [0, 3]; assert `validate_questions([q]) is False` and no exception is raised
    - Tag: `# Feature: adaptive-learning-platform, Property 6: Question validation rejects out-of-range correct_index`

  - [ ]* 5.3 Write property test for `validate_questions` — Property 7: Rejects missing fields
    - **Property 7: Question validation rejects missing fields**
    - **Validates: Requirements 4.2, 4.3**
    - Add to `backend/app/tests/test_question_validation.py`
    - Generate question objects with one required field removed at random; assert `validate_questions([q]) is False` and no exception is raised
    - Tag: `# Feature: adaptive-learning-platform, Property 7: Question validation rejects missing fields`

  - [x] 5.4 Implement `generate_questions` in `backend/app/services/question_generator.py`
    - Write `generate_questions(topic: Topic, transcript_slice: str) -> list[Question]`
    - Send only `transcript_slice` to the Groq LLM with a 30-second timeout
    - Validate the response with `validate_questions`; retry up to 3 times on validation failure or timeout
    - Raise `QuestionGenerationError` after all retries are exhausted
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 6. Implement output writer
  - [x] 6.1 Implement `backend/app/services/output_writer.py`
    - Write `write_output(result: PipelineOutput, output_path: str) -> None`
    - Serialise `result` to JSON using `dataclasses.asdict` (or a custom encoder for floats)
    - Write atomically where possible (write to a temp file, then rename)
    - Raise `OutputWriteError` on any `OSError` or `IOError`
    - _Requirements: 4.5, 4.6_

  - [ ]* 6.2 Write property test for `output_writer` — Property 8: Pipeline output round-trip serialisation
    - **Property 8: Pipeline output round-trip serialisation**
    - **Validates: Requirements 4.5**
    - Add to `backend/app/tests/test_snapping.py` or a new `test_output_writer.py`
    - Generate valid `PipelineOutput` instances; serialise to JSON string, deserialise back; assert all fields equal (floats within `1e-9`)
    - Tag: `# Feature: adaptive-learning-platform, Property 8: Pipeline output round-trip serialisation`

- [x] 7. Implement the pipeline orchestrator
  - [x] 7.1 Implement `backend/app/services/pipeline_service.py`
    - Write `run_pipeline(video_path: str, output_path: str) -> PipelineOutput`
    - Load `.env` via `python-dotenv`; check `GROQ_API_KEY` is present and non-empty; raise `ConfigurationError` if not
    - Call stages in order: `extract_audio` → `transcribe` → `detect_topics` → `generate_questions` (per topic, using the correct transcript slice) → `write_output`
    - Wrap all stage calls in a `try/finally` block; delete the temp WAV file in `finally` regardless of success or failure
    - For question generation, derive each topic's transcript slice from the `TranscriptResult` segments whose time ranges overlap with that topic's `[start, end]`
    - _Requirements: 1.4, 4.4, 5.1, 5.4_

  - [ ]* 7.2 Write unit tests for orchestrator cleanup and configuration guard
    - Test that the temp WAV file is deleted even when a stage raises an exception
    - Test that a missing or empty `GROQ_API_KEY` raises `ConfigurationError` without calling any API
    - Mock all stage functions so no real work is done
    - _Requirements: 1.4, 5.4_

- [x] 8. Implement the FastAPI background-job wrapper
  - [x] 8.1 Implement `backend/app/jobs/pipeline_job.py`
    - Write `enqueue_pipeline(video_path: str, output_path: str) -> None`
    - Call `run_pipeline(video_path, output_path)`
    - On success, update the database record for the video (use a placeholder / stub if the DB layer is not yet wired)
    - On `PipelineError`, log the error message and update the database record with a failure status
    - _Requirements: 4.5, 4.6_

- [~] 9. Checkpoint — Ensure all unit tests pass
  - Run `pytest backend/app/tests/` and confirm all existing tests pass before proceeding.
  - Ask the user if any questions arise.

- [ ] 10. Implement the CLI entry point
  - [~] 10.1 Implement `backend/run_pipeline.py`
    - Accept a single positional command-line argument (video file path) using `argparse`
    - Validate that the provided path exists and is a file; print an error to stderr and exit with non-zero code if not
    - Call `run_pipeline(video_path, output_path)` where `output_path` is derived from the input file name (e.g. `<stem>_output.json` in the same directory, or accept a second optional `--output` argument)
    - On success, print the final JSON to stdout and exit with code 0
    - On `PipelineError`, print the error message to stderr and exit with a non-zero code
    - _Requirements: 6.1, 6.2_

  - [ ]* 10.2 Write unit tests for the CLI
    - Test that a non-existent path prints to stderr and exits non-zero (use `subprocess.run` or `click.testing.CliRunner` / `argparse` test helpers)
    - Test that a valid path triggers `run_pipeline` and exits 0 (mock `run_pipeline`)
    - _Requirements: 6.1, 6.2_

- [ ] 11. Complete the unit test suite
  - [ ] 11.1 Write example-based unit tests for `snap_end_time` in `backend/app/tests/test_snapping.py`
    - Cover at minimum 5 distinct cases from the design: single segment, exact match, nearest-is-earlier, nearest-is-later, tie-breaking (two equidistant segments → returns later), all-equidistant (multiple segments → returns latest)
    - _Requirements: 6.3_

  - [-] 11.2 Write example-based unit tests for `validate_topics` in `backend/app/tests/test_topic_validation.py`
    - Cover all cases from the design table: valid input → True; missing `keyword`, `start`, or `end` → False; overlapping ranges → False; non-chronological order → False; fewer than 4 topics → False; more than 4 topics → False; `keyword` exceeds 60 chars → False; non-numeric `start`/`end` → False
    - _Requirements: 6.4_

  - [-] 11.3 Write example-based unit tests for `validate_questions` in `backend/app/tests/test_question_validation.py`
    - Cover all cases from the design table: valid input → True; missing `prompt`, `options`, `correct_index`, or `explanation` → False; `options` with 3 or 5 elements → False; `correct_index` = -1 or 4 → False; fewer than 4 questions → False; more than 4 questions → False
    - _Requirements: 6.5_

- [~] 12. Final checkpoint — Ensure all tests pass
  - Run `pytest backend/app/tests/ -v` and confirm every test (unit + property-based) passes.
  - Ask the user if any questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP, but the property-based tests (Properties 1–8) encode the correctness guarantees from the design document and are strongly recommended before connecting the pipeline to real API keys.
- Each task references specific requirements for traceability; the requirement numbering matches `requirements.md`.
- Property tests use **Hypothesis** (`@given`, `@settings(max_examples=100)`); install it via `requirements.txt`.
- The orchestrator owns temp-file cleanup; stage modules must not delete files they did not create.
- Transcript slicing for question generation: collect all `Segment.text` values whose `[start, end]` overlap with the topic's `[start, end]`, join with a space, and pass as `transcript_slice`.
- For the round-trip property test (Property 8), compare floats with `math.isclose(a, b, rel_tol=1e-9)`.

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "3.1", "4.1", "4.2", "5.1", "6.1"] },
    { "id": 2, "tasks": ["2.2", "3.2", "4.3", "4.4", "4.5", "4.6", "5.2", "5.3", "6.2", "4.7"] },
    { "id": 3, "tasks": ["4.8", "5.4", "7.1"] },
    { "id": 4, "tasks": ["7.2", "8.1", "11.1", "11.2", "11.3"] },
    { "id": 5, "tasks": ["10.1"] },
    { "id": 6, "tasks": ["10.2"] }
  ]
}
```
