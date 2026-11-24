# Requirements Document

## Introduction

This spec covers the standalone AI pipeline module for the Adaptive Learning Platform. Given a video file path, the pipeline extracts audio using ffmpeg, transcribes it via the Groq Whisper API, identifies exactly four main topics with end-time snapping, generates four multiple-choice questions per topic from that topic's transcript slice only, validates all LLM responses and retries on failure, and persists the final result as JSON to disk. A `run_pipeline.py` CLI script drives the pipeline end-to-end, and unit tests verify the snapping logic and JSON validation functions in isolation.

---

## Glossary

- **AI_Pipeline**: The standalone Python module in `backend/app/services` and `backend/app/jobs` that processes a video file through audio extraction, transcription, topic detection, and question generation.
- **Transcriber**: The component that calls the Groq Whisper API to convert audio to a timestamped transcript.
- **Topic_Detector**: The LLM-based component that extracts exactly four main topics (keyword, start, end) from the transcript.
- **Question_Generator**: The LLM-based component that produces four multiple-choice questions per topic from that topic's transcript slice only.
- **Topic**: One of the four AI-identified segments of a video, described by a keyword, a start timestamp, and an end timestamp snapped to the nearest Whisper segment boundary.
- **Question**: A single multiple-choice item with a prompt, four option strings, a correct option index, and a short explanation.
- **Groq_API**: The external API providing Whisper transcription and LLM completion endpoints.
- **ffmpeg**: The command-line tool used to extract audio from uploaded video files.

---

## Requirements

### Requirement 1: AI Pipeline — Audio Extraction

**User Story:** As a system operator, I want audio extracted from uploaded videos automatically, so that transcription can proceed without manual steps.

#### Acceptance Criteria

1. WHEN the AI_Pipeline job starts for a video, THE AI_Pipeline SHALL invoke ffmpeg to extract the audio track to a temporary WAV file.
2. IF ffmpeg exits with a non-zero exit code, THEN THE AI_Pipeline SHALL print an error message to stderr and stop processing.
3. IF ffmpeg exits with a zero exit code but the extracted WAV file has a duration of zero seconds, THEN THE AI_Pipeline SHALL print an error message to stderr and stop processing.
4. WHEN the AI_Pipeline job completes or fails, THE AI_Pipeline SHALL delete the temporary WAV file.

---

### Requirement 2: AI Pipeline — Transcription

**User Story:** As a system operator, I want the audio transcribed with word-level timestamps, so that topic boundaries can be aligned accurately.

#### Acceptance Criteria

1. WHEN the WAV file is ready, THE Transcriber SHALL call the Groq Whisper API and receive a transcript containing one or more segments, each with a `start` time, `end` time, `text` field, and one or more word-level entries each carrying a `word`, `start` time, and `end` time.
2. IF the Groq Whisper API returns an error, THEN THE Transcriber SHALL retry the request up to three times using exponential back-off with an initial delay of 1 second that doubles on each subsequent attempt, before printing an error message to stderr and stop processing.
3. THE Transcriber SHALL read the Groq API key exclusively from the `GROQ_API_KEY` environment variable.
4. IF the Groq Whisper API returns a response containing zero segments, THEN THE Transcriber SHALL print an error message to stderr and stop processing.

---

### Requirement 3: AI Pipeline — Topic Detection

**User Story:** As a system operator, I want exactly four main topics identified with timestamps, so that the platform knows when to pause the video.

#### Acceptance Criteria

1. WHEN all Whisper transcript segments for a video are persisted, THE Topic_Detector SHALL send the full timestamped transcript to the Groq LLM and request a JSON response containing exactly four objects, each with fields `keyword` (string, 1–60 characters), `start` (number, seconds), and `end` (number, seconds).
2. WHEN the Groq LLM returns a response, THE Topic_Detector SHALL validate that the response is well-formed JSON containing exactly four topic objects in chronological order, with no two objects having overlapping time ranges and each field matching its declared type and length constraint.
3. IF the LLM response fails JSON validation — meaning the response is not parseable as JSON, contains fewer or more than four topic objects, contains a field with a wrong type, violates the 60-character keyword limit, or contains overlapping or non-chronological time ranges — THEN THE Topic_Detector SHALL retry the LLM call, up to three attempts total, discarding any partial result from the failed attempt before each retry.
4. IF all three LLM retry attempts fail validation, THEN THE Topic_Detector SHALL print an error message to stderr and stop processing, discarding all partial topic data.
5. WHEN topic boundaries pass validation, THE Topic_Detector SHALL replace each topic's `end` time with the `end` time of the Whisper segment whose `end` time is closest to the original LLM-returned `end` time, using the later segment on a tie.
6. WHEN snapping is complete, THE Topic_Detector SHALL verify that the snapped `end` times remain in strictly ascending order with no two topics sharing the same `end` time, and SHALL print an error message to stderr and stop processing if this condition is violated.

---

### Requirement 4: AI Pipeline — Question Generation

**User Story:** As a system operator, I want four distinct multiple-choice questions generated per topic, so that repeated wrong answers present new questions.

#### Acceptance Criteria

1. WHEN topic boundaries are finalised, THE Question_Generator SHALL send the transcript slice for each Topic independently to the Groq LLM with a timeout of 30 seconds and request exactly four question objects, each containing `prompt` (string), `options` (array of four strings), `correct_index` (integer 0–3), and `explanation` (string).
2. THE Question_Generator SHALL validate that each LLM response contains exactly four question objects, that each object contains all required fields (`prompt`, `options`, `correct_index`, `explanation`), that `options` is an array of exactly four strings, and that `correct_index` is an integer in the range 0 to 3 inclusive.
3. IF a question object fails validation or the LLM call times out, THEN THE Question_Generator SHALL retry the LLM call for that Topic up to three times; IF all three retries fail, THEN THE Question_Generator SHALL print an error message to stderr and stop processing, discarding any questions generated for that Topic.
4. THE Question_Generator SHALL use only the transcript text belonging to the corresponding Topic when generating questions for that Topic, excluding transcript text assigned to any other Topic.
5. WHEN all topics have been processed and every topic's questions are validated, THE AI_Pipeline SHALL write the complete pipeline output — including all four topics and their associated question sets — to a JSON file on disk and exit successfully.
6. IF writing the JSON output file fails, THEN THE AI_Pipeline SHALL print an error message to stderr and exit with a non-zero exit code.

---

### Requirement 5: Environment Configuration and Secrets

**User Story:** As a developer, I want all secrets managed through environment variables, so that credentials are never committed to source control.

#### Acceptance Criteria

1. THE AI_Pipeline SHALL read the `GROQ_API_KEY` credential exclusively from an environment variable loaded via python-dotenv from a `backend/.env` file.
2. THE Backend repository SHALL include a `backend/.env.example` file listing `GROQ_API_KEY=` with an empty value and no real key.
3. THE Backend repository's `.gitignore` SHALL include `backend/.env` to prevent accidental credential exposure.
4. IF `GROQ_API_KEY` is absent or set to an empty string when the pipeline starts, THEN THE AI_Pipeline SHALL print an error message to stderr naming the missing variable and exit with a non-zero exit code without attempting any API calls.
5. THE Backend repository SHALL include a `backend/requirements.txt` listing all Python dependencies required by the pipeline.

---

### Requirement 6: AI Pipeline Script and Unit Tests

**User Story:** As a developer, I want a runnable pipeline script and automated unit tests, so that I can verify the pipeline in isolation.

#### Acceptance Criteria

1. WHEN a valid video file path is provided as a command-line argument to `backend/run_pipeline.py`, THE AI_Pipeline SHALL execute transcription, topic segmentation, end-time snapping, and question generation in sequence, then print the final JSON output to stdout and exit with code 0.
2. IF an invalid or non-existent file path is provided to `backend/run_pipeline.py`, THEN THE AI_Pipeline SHALL print an error message indicating the invalid input to stderr and exit with a non-zero exit code without producing JSON output.
3. THE AI_Pipeline SHALL include unit tests covering at least 5 distinct input cases that verify the end-time snapping function returns a float equal to the nearest segment end time, where ties are broken by selecting the later segment end time.
4. THE AI_Pipeline SHALL include unit tests that verify the topic JSON validation function returns False and raises no unhandled exception when given a topic object missing any required field, when given a topic list containing overlapping time ranges, or when given a topic list containing fewer than 4 or more than 4 topics.
5. THE AI_Pipeline SHALL include unit tests that verify the question JSON validation function returns False and raises no unhandled exception when given a question object with any missing required field or with a `correct_index` value less than 0 or greater than 3.
6. FOR ALL topic lists that pass topic JSON validation, applying the end-time snapping function twice SHALL produce a result identical to applying it once, with no field values differing between the first and second application.
