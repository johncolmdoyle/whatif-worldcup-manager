"""Tests for GET /api/session endpoint."""

import uuid
from datetime import datetime, timedelta

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


class TestGetSessionEndpoint:
    """Tests for GET /api/session."""

    def setup_method(self):
        """Clear session store before each test."""
        session_store._sessions.clear()

    def test_returns_200_with_match_data_when_session_active(self):
        """GET /api/session returns 200 with matchData when session is valid."""
        client = TestClient(app)
        match_data = _make_match_data()
        session_id = session_store.create_session(match_data)

        response = client.get("/api/session", cookies={"session_id": session_id})

        assert response.status_code == 200
        body = response.json()
        assert "matchData" in body
        assert body["matchData"]["homeTeam"]["name"] == "Argentina"
        assert body["matchData"]["awayTeam"]["name"] == "France"
        assert body["matchData"]["actualScore"] == {"home": 2, "away": 1}

    def test_returns_401_when_no_session_cookie(self):
        """GET /api/session returns 401 when no session_id cookie is present."""
        client = TestClient(app)

        response = client.get("/api/session")

        assert response.status_code == 401
        assert response.json() == {"detail": {"error": "session_expired"}}

    def test_returns_401_when_session_expired(self):
        """GET /api/session returns 401 when session has expired."""
        client = TestClient(app)
        match_data = _make_match_data()
        session_id = session_store.create_session(match_data)

        # Backdate last_accessed to 31 minutes ago to simulate expiry
        session_store._sessions[session_id]["last_accessed"] = datetime.utcnow() - timedelta(
            minutes=31
        )

        response = client.get("/api/session", cookies={"session_id": session_id})

        assert response.status_code == 401
        assert response.json() == {"detail": {"error": "session_expired"}}

    def test_returns_401_when_session_id_unknown(self):
        """GET /api/session returns 401 when session_id cookie doesn't match any session."""
        client = TestClient(app)

        response = client.get("/api/session", cookies={"session_id": "unknown-session-id"})

        assert response.status_code == 401
        assert response.json() == {"detail": {"error": "session_expired"}}

    def test_match_data_structure_is_complete(self):
        """GET /api/session returns the full MatchData structure."""
        client = TestClient(app)
        match_data = _make_match_data()
        session_id = session_store.create_session(match_data)

        response = client.get("/api/session", cookies={"session_id": session_id})

        assert response.status_code == 200
        body = response.json()["matchData"]

        # Verify all top-level keys are present
        assert "matchId" in body
        assert "homeTeam" in body
        assert "awayTeam" in body
        assert "events" in body
        assert "actualScore" in body

        # Verify team structure
        assert len(body["homeTeam"]["startingLineup"]) == 11
        assert len(body["awayTeam"]["startingLineup"]) == 11
        assert "statistics" in body["homeTeam"]
        assert "statistics" in body["awayTeam"]
