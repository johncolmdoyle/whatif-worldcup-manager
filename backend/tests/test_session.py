"""Unit and integration tests for the SessionStore and session dependency."""

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.models import (
    MatchData,
    MatchEvent,
    MatchStatistics,
    Player,
    Score,
    TeamData,
)
from app.session import SessionStore, get_session_dependency, session_store


# --- Helpers ---


def _make_statistics() -> MatchStatistics:
    return MatchStatistics(
        possessionPct=55.0,
        shotsOnTarget=5,
        totalShots=12,
        passes=400,
        fouls=10,
    )


def _make_players(count: int, prefix: str = "Player") -> list[Player]:
    positions = ["GK"] + ["DEF"] * 4 + ["MID"] * 3 + ["FWD"] * 3
    return [
        Player(name=f"{prefix} {i+1}", squadNumber=i + 1, position=positions[i % len(positions)])
        for i in range(count)
    ]


def _make_match_data(home_name: str = "Argentina", away_name: str = "France") -> MatchData:
    stats = _make_statistics()
    home_team = TeamData(
        name=home_name,
        startingLineup=_make_players(11, "Home"),
        substitutes=_make_players(5, "HomeSub"),
        statistics=stats,
    )
    away_team = TeamData(
        name=away_name,
        startingLineup=_make_players(11, "Away"),
        substitutes=_make_players(3, "AwaySub"),
        statistics=stats,
    )
    return MatchData(
        matchId=str(uuid.uuid4()),
        homeTeam=home_team,
        awayTeam=away_team,
        events=[
            MatchEvent(type="goal", minute=23, playerName="Home 1", teamName=home_name),
        ],
        actualScore=Score(home=2, away=1),
    )


# --- Tests ---


class TestSessionStoreCRUD:
    def test_create_session_returns_uuid_and_data_retrievable(self):
        """create_session returns a valid UUID and get_session retrieves the data."""
        store = SessionStore()
        match_data = _make_match_data()

        session_id = store.create_session(match_data)

        # session_id should be a valid UUID string
        parsed = uuid.UUID(session_id)
        assert str(parsed) == session_id

        # Data should be retrievable
        retrieved = store.get_session(session_id)
        assert retrieved is not None
        assert retrieved == match_data

    def test_get_session_returns_none_for_unknown_id(self):
        """get_session returns None for a session_id that doesn't exist."""
        store = SessionStore()

        result = store.get_session("nonexistent-session-id")

        assert result is None

    def test_set_session_updates_stored_data(self):
        """set_session replaces the stored MatchData for an existing session."""
        store = SessionStore()
        original_data = _make_match_data(home_name="Argentina", away_name="France")
        session_id = store.create_session(original_data)

        updated_data = _make_match_data(home_name="Brazil", away_name="Germany")
        store.set_session(session_id, updated_data)

        retrieved = store.get_session(session_id)
        assert retrieved is not None
        assert retrieved.homeTeam.name == "Brazil"
        assert retrieved.awayTeam.name == "Germany"

    def test_delete_session_removes_session(self):
        """delete_session removes the session so get_session returns None."""
        store = SessionStore()
        match_data = _make_match_data()
        session_id = store.create_session(match_data)

        # Confirm it exists first
        assert store.get_session(session_id) is not None

        store.delete_session(session_id)

        # Now it should be gone
        assert store.get_session(session_id) is None

    def test_delete_session_nonexistent_does_not_raise(self):
        """delete_session on a nonexistent session_id does not raise."""
        store = SessionStore()
        # Should not raise
        store.delete_session("does-not-exist")

    def test_set_session_nonexistent_does_not_create(self):
        """set_session on a nonexistent session_id does not create a new entry."""
        store = SessionStore()
        match_data = _make_match_data()

        store.set_session("nonexistent-id", match_data)

        assert store.get_session("nonexistent-id") is None


class TestSessionStoreTTL:
    def test_expired_session_returns_none(self):
        """A session accessed after 30 minutes of inactivity should return None."""
        store = SessionStore()
        match_data = _make_match_data()
        session_id = store.create_session(match_data)

        # Manually backdate the last_accessed to 31 minutes ago
        from datetime import timedelta

        store._sessions[session_id]["last_accessed"] = datetime.utcnow() - timedelta(minutes=31)

        # get_session should detect the expiry and return None
        result = store.get_session(session_id)
        assert result is None

        # The session entry should have been deleted
        assert session_id not in store._sessions

    def test_fresh_session_is_not_expired(self):
        """A freshly accessed session should NOT be expired and should return data."""
        store = SessionStore()
        match_data = _make_match_data()
        session_id = store.create_session(match_data)

        # Access immediately — should be well within TTL
        result = store.get_session(session_id)
        assert result is not None
        assert result == match_data

    def test_session_at_exactly_30_minutes_is_expired(self):
        """A session accessed at exactly 30 minutes should be expired (>= TTL expires)."""
        store = SessionStore()
        match_data = _make_match_data()
        session_id = store.create_session(match_data)

        # Set last_accessed to exactly 30 minutes ago
        from datetime import timedelta

        store._sessions[session_id]["last_accessed"] = datetime.utcnow() - timedelta(
            seconds=30 * 60
        )

        # At exactly TTL, session should be expired
        result = store.get_session(session_id)
        assert result is None

    def test_access_resets_ttl(self):
        """Accessing a session should reset its last_accessed timestamp."""
        store = SessionStore()
        match_data = _make_match_data()
        session_id = store.create_session(match_data)

        # Backdate to 29 minutes ago (still valid)
        from datetime import timedelta

        store._sessions[session_id]["last_accessed"] = datetime.utcnow() - timedelta(minutes=29)

        # Access the session — this should reset last_accessed
        result = store.get_session(session_id)
        assert result is not None

        # Now last_accessed should be approximately now
        entry = store._sessions[session_id]
        elapsed = datetime.utcnow() - entry["last_accessed"]
        assert elapsed < timedelta(seconds=2)



class TestSessionDependencyIntegration:
    """Integration tests using FastAPI TestClient to verify 401 behavior."""

    def _create_test_app(self) -> FastAPI:
        """Create a minimal FastAPI app with a protected endpoint using get_session_dependency."""
        test_app = FastAPI()

        @test_app.get("/protected")
        async def protected_endpoint(match_data: MatchData = Depends(get_session_dependency)):
            return {"team": match_data.homeTeam.name}

        return test_app

    def test_no_session_cookie_returns_401_session_expired(self):
        """A request without a session_id cookie gets 401 with {"error": "session_expired"}."""
        app = self._create_test_app()
        client = TestClient(app)

        response = client.get("/protected")

        assert response.status_code == 401
        assert response.json() == {"detail": {"error": "session_expired"}}

    def test_invalid_session_id_returns_401_session_expired(self):
        """A request with an unknown session_id cookie gets 401 with {"error": "session_expired"}."""
        app = self._create_test_app()
        client = TestClient(app)

        response = client.get("/protected", cookies={"session_id": "nonexistent-session-id"})

        assert response.status_code == 401
        assert response.json() == {"detail": {"error": "session_expired"}}

    def test_expired_session_id_returns_401_session_expired(self):
        """A request with an expired session_id cookie gets 401 with {"error": "session_expired"}."""
        app = self._create_test_app()
        client = TestClient(app)

        # Create a valid session and then expire it
        match_data = _make_match_data()
        session_id = session_store.create_session(match_data)

        # Backdate to make it expired
        session_store._sessions[session_id]["last_accessed"] = datetime.utcnow() - timedelta(
            minutes=31
        )

        response = client.get("/protected", cookies={"session_id": session_id})

        assert response.status_code == 401
        assert response.json() == {"detail": {"error": "session_expired"}}

        # Clean up
        session_store._sessions.pop(session_id, None)

    def test_valid_session_returns_200(self):
        """A request with a valid, non-expired session_id returns 200 (sanity check)."""
        app = self._create_test_app()
        client = TestClient(app)

        # Create a valid session
        match_data = _make_match_data()
        session_id = session_store.create_session(match_data)

        response = client.get("/protected", cookies={"session_id": session_id})

        assert response.status_code == 200
        assert response.json() == {"team": "Argentina"}

        # Clean up
        session_store.delete_session(session_id)
