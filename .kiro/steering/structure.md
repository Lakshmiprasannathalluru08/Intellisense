# Project Structure & AI Pipeline

## Directory Layout

- `backend/app/` — main.py, routes, services, jobs, models
- `frontend/src/` — pages, components, api

## AI Pipeline

Build the AI pipeline as a standalone Python module in `backend/app/services` and `backend/app/jobs`.

**Input:** a video file. **Output:** JSON saved to disk.

1. Extract audio with ffmpeg.
2. Transcribe with Whisper through the Groq API, keeping start and end time of every segment.
3. Send the timestamped transcript to a Groq LLM and get exactly 4 main topics as strict JSON: keyword, start, end.
4. Snap each topic''s end time to the nearest segment end so the pause never happens mid-sentence. Topics must be in order and not overlap.
5. For each topic generate 4 different multiple-choice questions (4 options, correct index, short explanation) from that topic''s transcript only. Validate the JSON.
6. Add retries for invalid JSON and error handling.
7. Add a script: `python run_pipeline.py video.mp4`, plus unit tests for end time snapping and JSON validation.

## Environment & Dependencies

- `backend/.env.example` and `backend/.env` with empty values: `GROQ_API_KEY=`, `MONGODB_URI=`, `MONGODB_DB_NAME=learning_assessment`, `JWT_SECRET=`
- `.gitignore` must ignore `backend/.env`
- Use python-dotenv; create `backend/requirements.txt`
- Never write real keys in code
