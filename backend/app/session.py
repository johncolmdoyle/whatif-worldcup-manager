"""In-memory session store for development use."""

import os
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from fastapi import Cookie, HTTPException, Response

from app.models import MatchData

SESSION_TTL_SECONDS = 30 * 60  # 30 minutes


class SessionStore:
    """Server-side session store backed by an in-memory dict.

    Each session entry stores serialized MatchData and a last-accessed timestamp.
    Structure: {session_id: {"data": MatchData_json_str, "last_accessed": datetime}}
    """

    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}

    def create_session(self, match_data: MatchData) -> str:
        """Create a new session with a UUID, store the serialized match data.

        Args:
            match_data: The MatchData to store in the session.

        Returns:
            The generated session_id (UUID string).
        """
        session_id = str(uuid4())
        self._sessions[session_id] = {
            "data": match_data.serialize(),
            "last_accessed": datetime.utcnow(),
        }
        return session_id

    def get_session(self, session_id: str) -> Optional[MatchData]:
        """Retrieve stored match data for a session.

        Checks the session's last_accessed timestamp against SESSION_TTL_SECONDS.
        If the session has been inactive for longer than the TTL, it is deleted
        and None is returned.

        Args:
            session_id: The session identifier.

        Returns:
            The deserialized MatchData, or None if the session is missing or expired.
        """
        entry = self._sessions.get(session_id)
        if entry is None:
            return None

        now = datetime.utcnow()
        elapsed = now - entry["last_accessed"]
        if elapsed >= timedelta(seconds=SESSION_TTL_SECONDS):
            # Session has expired — delete and return None
            del self._sessions[session_id]
            return None

        # Session is still valid — update last_accessed and return data
        entry["last_accessed"] = now
        return MatchData.deserialize(entry["data"])

    def set_session(self, session_id: str, match_data: MatchData) -> None:
        """Update an existing session with new match data.

        Args:
            session_id: The session identifier.
            match_data: The updated MatchData to store.
        """
        if session_id in self._sessions:
            self._sessions[session_id] = {
                "data": match_data.serialize(),
                "last_accessed": datetime.utcnow(),
            }

    def delete_session(self, session_id: str) -> None:
        """Remove a session.

        Args:
            session_id: The session identifier to delete.
        """
        self._sessions.pop(session_id, None)


# Module-level singleton instance
session_store = SessionStore()


def get_session_dependency(session_id: str | None = Cookie(None)) -> MatchData:
    """FastAPI dependency that retrieves the current session's MatchData.

    Reads session_id from an HTTP-only cookie. If the session doesn't exist
    or has expired, raises 401.
    """
    if session_id is None:
        raise HTTPException(status_code=401, detail={"error": "session_expired"})

    match_data = session_store.get_session(session_id)
    if match_data is None:
        raise HTTPException(status_code=401, detail={"error": "session_expired"})

    return match_data


def set_session_cookie(response: Response, session_id: str) -> None:
    """Set the session_id cookie on the response with HTTP-only and SameSite=Strict."""
    secure = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        samesite="strict",
        secure=secure,
        max_age=30 * 60,  # 30 minutes
    )
