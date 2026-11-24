"""FastAPI application entry point.

Run from the backend/ folder:

    uvicorn app.main:app --reload

Loads secrets (MONGODB_URI, MONGODB_DB_NAME, JWT_SECRET, GROQ_API_KEY,
GROQ_LLM_MODEL) from backend/.env BEFORE importing the route modules, so
that env-driven settings are visible at import time. Enables CORS for the
Vite dev server and mounts the auth, videos, and answers routers.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env first, before importing route/service modules.
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path, override=False)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import ensure_indexes
from app.routes.auth import router as auth_router
from app.routes.videos import router as videos_router
from app.routes.answers import router as answers_router
from app.routes.results import router as results_router


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    ensure_indexes()
    yield


app = FastAPI(title="Adaptive Learning Platform", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(videos_router)
app.include_router(answers_router)
app.include_router(results_router)


@app.get("/health")
def health():
    return {"status": "ok"}
