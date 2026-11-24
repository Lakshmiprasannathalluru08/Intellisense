[README.md](https://github.com/user-attachments/files/35368838/README.md)
# Adaptive Learning Platform

Teachers upload a lecture video. The app transcribes it, identifies the important concepts across the whole video, and generates multiple-choice questions for each concept. While students watch, the video pauses after the teacher finishes each concept and a question pops up. Teachers get a results dashboard showing how students performed.

## Features

**Teacher**
- Register and log in as a teacher
- Upload a video; transcription, concept detection and question generation run automatically
- Results dashboard per video: students attempted, average score, per-student table, per-question table (with the most chosen wrong answer) and a score chart

**Student**
- Watch a video with pop-up questions
- Feedback card after each answer: green "Correct!" or red "Not quite" with the correct answer and a one-sentence explanation
- A Continue button moves the video on; there is no auto-advance timer
- After a wrong answer (with tries left), the video jumps back to the start of that concept and shows a new, different question
- "My results" page with answered count, correct on first try and score

**Pop-up rules**
- The video pauses only after the teacher finishes the concept, at a full stop, plus a short pause
- Concepts are spread across the whole video, from the first line to the last
- The last pop-up appears at the end of the video
- Students never see timestamps, concept names, star ratings or the correct answer before they answer
- If a section has no valid question, the video plays straight through with no message

## Tech Stack

- **Backend:** Python, FastAPI, Uvicorn
- **Database:** MongoDB Atlas
- **AI:** Groq (Whisper for transcription with word timestamps, LLM for concepts and questions)
- **Media:** ffmpeg for audio extraction
- **Auth:** JWT
- **Frontend:** React with Vite

## Project Structure

```
adaptive learning/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI entry point
│   │   ├── routes/                 # auth, videos, questions, answers, results
│   │   ├── services/               # audio_extractor, transcriber,
│   │   │                           # topic_detector, question_generator,
│   │   │                           # pipeline_job
│   │   └── tests/                  # pytest tests
│   ├── storage/                    # uploaded videos and processed output (not committed)
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── pages/                  # TeacherDashboard, Watch, Results, MyResults
│   │   └── Dashboard.css
│   ├── package.json
│   └── .env.example
└── README.md
```

Folder and file names may differ slightly; check the repository for the exact layout.

## Prerequisites

- Python 3.10 or newer
- Node.js 18 or newer
- ffmpeg installed and available on your PATH
- A MongoDB Atlas database
- A Groq API key

## Setup and Run

**Backend**

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
cp .env.example .env            # then fill in your values
uvicorn app.main:app --reload
```

The API runs at http://localhost:8000.

**Frontend**

```bash
cd frontend
npm install
cp .env.example .env            # then fill in your values
npm run dev
```

The app runs at http://localhost:5173.

## Environment Variables

Copy the names from `backend/.env.example` and `frontend/.env.example`. Typical variables:

| Variable | Where | Description |
|---|---|---|
| `GROQ_API_KEY` | backend | Groq API key for transcription and the LLM |
| `MONGODB_URI` | backend | MongoDB Atlas connection string |
| `JWT_SECRET` | backend | Secret for signing tokens (at least 32 random characters) |
| `CORS_ORIGINS` | backend | Comma-separated list of allowed frontend URLs |
| `VITE_API_URL` | frontend | Base URL of the backend API |

Never put real values in this file or commit `.env` files.

## How It Works

1. A teacher uploads a video.
2. ffmpeg extracts the audio.
3. Groq Whisper transcribes it, keeping segment and word timestamps.
4. The transcript is split in code into N equal sections (N depends on video length), each cut moved to a full stop.
5. For each section, one main concept is identified and up to 4 questions are generated (definition, example, application, why/how).
6. The result is saved and the video is marked Ready.
7. Students watch; the player pauses after each section ends and shows a question.
8. Each answer is stored with its attempt number.
9. Results are aggregated for the teacher and for each student.

## Tests

```bash
cd backend
python -m pytest app/tests -q
```

## Deployment

- **Backend:** Render, using a Docker deploy so ffmpeg is installed. Set the backend environment variables and `CORS_ORIGINS` to your frontend URL.
- **Frontend:** Vercel, with root directory `frontend` and `VITE_API_URL` set to the backend URL.
- On free hosting tiers, local disk storage is wiped on restart, so uploaded videos and saved output can disappear. Use persistent or cloud storage for real use.

## Security Notes

- Never commit `.env` files.
- Rotate any key or password that has ever been exposed.
- Use a JWT secret of at least 32 characters.
- The question endpoint never returns the correct answer; it is returned only after an answer is submitted.
