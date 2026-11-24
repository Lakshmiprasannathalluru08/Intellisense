"""MongoDB Atlas connection setup using PyMongo.

Reads MONGODB_URI and MONGODB_DB_NAME from the environment (loaded from
backend/.env by main.py). Provides a lazy singleton client, a get_db()
helper, and a unique index on the users.email field.
"""

import os

from pymongo import ASCENDING
from pymongo import MongoClient

_client: "MongoClient | None" = None


def get_client() -> MongoClient:
    """Return a lazily-created, shared MongoClient."""
    global _client
    if _client is None:
        uri = os.environ["MONGODB_URI"]
        _client = MongoClient(uri)
    return _client


def get_db():
    """Return the configured database handle."""
    return get_client()[os.environ["MONGODB_DB_NAME"]]


def get_users_collection():
    """Return the users collection."""
    return get_db()["users"]


def ensure_indexes() -> None:
    """Create a unique index on users.email (idempotent)."""
    get_users_collection().create_index(
        [("email", ASCENDING)],
        unique=True,
        name="email_unique",
    )


def get_videos_collection():
    """Return the videos collection."""
    return get_db()["videos"]
