"""Tests for DELETE /api/session endpoint."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    MatchData,
    MatchEvent,
    MatchStatistics,
    Player,
    Score,
    TeamData,
)
from app.session import session_store


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


class TestDeleteSessionEndpoint:
    """Tests for DELETE /api/session."""

    def setup_method(self):
        """Clear session store before each test."""
        session_store._sessions.clear()

    def test_returns_204_and_clears_session(self):
        """DELETE /api/session returns 204 and removes the session from the store."""
        client = TestClient(app)
        match_data = _make_match_data()
        session_id = session_store.create_session(match_data)

        # Confirm session exists
        assert session_store.get_session(session_id) is not None

        response = client.delete("/api/session", cookies={"session_id": session_id})

        assert response.status_code == 204
        assert response.content == b""

        # Session should be removed from the store
        assert session_store.get_session(session_id) is None

    def test_returns_204_when_no_session_cookie(self):
        """DELETE /api/session returns 204 even without a session cookie (idempotent)."""
        client = TestClient(app)

        response = client.delete("/api/session")

        assert response.status_code == 204
        assert response.content == b""

    def test_returns_204_when_session_id_unknown(self):
        """DELETE /api/session returns 204 for an unknown session_id (idempotent)."""
        client = TestClient(app)

        response = client.delete("/api/session", cookies={"session_id": "unknown-id"})

        assert response.status_code == 204
        assert response.content == b""

    def test_deletes_session_cookie_from_response(self):
        """DELETE /api/session clears the session_id cookie in the response."""
        client = TestClient(app)
        match_data = _make_match_data()
        session_id = session_store.create_session(match_data)

        response = client.delete("/api/session", cookies={"session_id": session_id})

        assert response.status_code == 204
        # The response should set the cookie to expire (deleted)
        set_cookie_header = response.headers.get("set-cookie", "")
        assert "session_id" in set_cookie_header
        # Cookie deletion typically sets max-age=0 or an expiry in the past
        assert 'max-age=0' in set_cookie_header.lower() or 'expires=' in set_cookie_header.lower()

    def test_session_not_accessible_after_delete(self):
        """After DELETE /api/session, GET /api/session should return 401."""
        client = TestClient(app)
        match_data = _make_match_data()
        session_id = session_store.create_session(match_data)

        # First confirm the session works
        get_response = client.get("/api/session", cookies={"session_id": session_id})
        assert get_response.status_code == 200

        # Delete the session
        delete_response = client.delete("/api/session", cookies={"session_id": session_id})
        assert delete_response.status_code == 204

        # Now the session should be gone
        get_response = client.get("/api/session", cookies={"session_id": session_id})
        assert get_response.status_code == 401

    def test_idempotent_double_delete(self):
        """Calling DELETE /api/session twice returns 204 both times."""
        client = TestClient(app)
        match_data = _make_match_data()
        session_id = session_store.create_session(match_data)

        response1 = client.delete("/api/session", cookies={"session_id": session_id})
        assert response1.status_code == 204

        response2 = client.delete("/api/session", cookies={"session_id": session_id})
        assert response2.status_code == 204
