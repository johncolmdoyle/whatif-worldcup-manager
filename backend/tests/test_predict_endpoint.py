"""Unit tests for POST /api/predict endpoint."""

import uuid
from unittest.mock import patch

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


def _make_match_data() -> MatchData:
    stats = _make_statistics()
    home_team = TeamData(
        name="Argentina",
        startingLineup=_make_players(11, "Home"),
        substitutes=_make_players(5, "HomeSub"),
        statistics=stats,
    )
    away_team = TeamData(
        name="France",
        startingLineup=_make_players(11, "Away"),
        substitutes=_make_players(3, "AwaySub"),
        statistics=stats,
    )
    return MatchData(
        matchId=str(uuid.uuid4()),
        homeTeam=home_team,
        awayTeam=away_team,
        events=[
            MatchEvent(type="goal", minute=23, playerName="Home 1", teamName="Argentina"),
            MatchEvent(type="goal", minute=36, playerName="Home 5", teamName="Argentina"),
            MatchEvent(type="goal", minute=80, playerName="Away 1", teamName="France"),
        ],
        actualScore=Score(home=2, away=1),
    )


def _create_session_and_client() -> tuple[TestClient, str]:
    """Create a valid session with match data and return the client + session_id."""
    match_data = _make_match_data()
    session_id = session_store.create_session(match_data)
    client = TestClient(app)
    return client, session_id


def _lineup_payload(home_players: list[Player], away_players: list[Player]) -> dict:
    """Build a request payload from player lists."""
    return {
        "homeLineup": [p.model_dump() for p in home_players],
        "awayLineup": [p.model_dump() for p in away_players],
    }


# --- Tests ---


class TestPredictEndpointSuccess:
    def test_predict_with_unchanged_lineups_returns_200(self):
        """Submitting the original lineups unchanged returns a 200 with predictedOutcome."""
        client, session_id = _create_session_and_client()
        try:
            home_lineup = _make_players(11, "Home")
            away_lineup = _make_players(11, "Away")
            payload = _lineup_payload(home_lineup, away_lineup)

            response = client.post(
                "/api/predict",
                json=payload,
                cookies={"session_id": session_id},
            )

            assert response.status_code == 200
            data = response.json()
            assert "predictedOutcome" in data
            outcome = data["predictedOutcome"]
            assert "predictedScore" in outcome
            assert "confidencePct" in outcome
            assert "contributingFactors" in outcome
            assert "modifiedHomeLineup" in outcome
            assert "modifiedAwayLineup" in outcome
            # Confidence should be 100% for unchanged lineups
            assert outcome["confidencePct"] == 100.0
            # Score should match actual for unchanged lineups
            assert outcome["predictedScore"]["home"] == 2
            assert outcome["predictedScore"]["away"] == 1
        finally:
            session_store.delete_session(session_id)

    def test_predict_with_modified_lineup_returns_200(self):
        """Submitting modified lineups returns a valid 200 response."""
        client, session_id = _create_session_and_client()
        try:
            # Modify home lineup: replace one forward with a substitute
            home_lineup = _make_players(11, "Home")
            home_lineup[10] = Player(name="HomeSub 1", squadNumber=12, position="FWD")
            away_lineup = _make_players(11, "Away")
            payload = _lineup_payload(home_lineup, away_lineup)

            response = client.post(
                "/api/predict",
                json=payload,
                cookies={"session_id": session_id},
            )

            assert response.status_code == 200
            data = response.json()
            outcome = data["predictedOutcome"]
            assert 0 <= outcome["confidencePct"] <= 100
            assert 3 <= len(outcome["contributingFactors"]) <= 5
            assert outcome["predictedScore"]["home"] >= 0
            assert outcome["predictedScore"]["away"] >= 0
        finally:
            session_store.delete_session(session_id)


class TestPredictEndpointValidation:
    def test_home_lineup_too_few_returns_400(self):
        """Submitting fewer than 11 home players returns 400."""
        client, session_id = _create_session_and_client()
        try:
            home_lineup = _make_players(10, "Home")  # Only 10 players
            away_lineup = _make_players(11, "Away")
            payload = _lineup_payload(home_lineup, away_lineup)

            response = client.post(
                "/api/predict",
                json=payload,
                cookies={"session_id": session_id},
            )

            assert response.status_code == 400
            assert "error" in response.json()
            assert "11" in response.json()["error"]
        finally:
            session_store.delete_session(session_id)

    def test_away_lineup_too_many_returns_400(self):
        """Submitting more than 11 away players returns 400."""
        client, session_id = _create_session_and_client()
        try:
            home_lineup = _make_players(11, "Home")
            away_lineup = _make_players(12, "Away")  # 12 players
            payload = _lineup_payload(home_lineup, away_lineup)

            response = client.post(
                "/api/predict",
                json=payload,
                cookies={"session_id": session_id},
            )

            assert response.status_code == 400
            assert "error" in response.json()
            assert "11" in response.json()["error"]
        finally:
            session_store.delete_session(session_id)

    def test_both_lineups_wrong_count_returns_400_for_home(self):
        """If both lineups are wrong, returns 400 for the home lineup first."""
        client, session_id = _create_session_and_client()
        try:
            home_lineup = _make_players(9, "Home")
            away_lineup = _make_players(13, "Away")
            payload = _lineup_payload(home_lineup, away_lineup)

            response = client.post(
                "/api/predict",
                json=payload,
                cookies={"session_id": session_id},
            )

            assert response.status_code == 400
            assert "Home" in response.json()["error"]
        finally:
            session_store.delete_session(session_id)


class TestPredictEndpointSession:
    def test_no_session_returns_401(self):
        """A request without a session cookie returns 401."""
        client = TestClient(app)
        home_lineup = _make_players(11, "Home")
        away_lineup = _make_players(11, "Away")
        payload = _lineup_payload(home_lineup, away_lineup)

        response = client.post("/api/predict", json=payload)

        assert response.status_code == 401

    def test_invalid_session_returns_401(self):
        """A request with an invalid session_id returns 401."""
        client = TestClient(app)
        home_lineup = _make_players(11, "Home")
        away_lineup = _make_players(11, "Away")
        payload = _lineup_payload(home_lineup, away_lineup)

        response = client.post(
            "/api/predict",
            json=payload,
            cookies={"session_id": "nonexistent-session"},
        )

        assert response.status_code == 401


class TestPredictEndpointErrors:
    def test_prediction_engine_value_error_returns_400(self):
        """If the prediction engine raises ValueError, return 400."""
        client, session_id = _create_session_and_client()
        try:
            home_lineup = _make_players(11, "Home")
            away_lineup = _make_players(11, "Away")
            payload = _lineup_payload(home_lineup, away_lineup)

            with patch("app.main.predict", side_effect=ValueError("Invalid lineup data")):
                response = client.post(
                    "/api/predict",
                    json=payload,
                    cookies={"session_id": session_id},
                )

            assert response.status_code == 400
            assert response.json()["error"] == "Invalid lineup data"
        finally:
            session_store.delete_session(session_id)

    def test_prediction_engine_unexpected_error_returns_500(self):
        """If the prediction engine raises an unexpected exception, return 500."""
        client, session_id = _create_session_and_client()
        try:
            home_lineup = _make_players(11, "Home")
            away_lineup = _make_players(11, "Away")
            payload = _lineup_payload(home_lineup, away_lineup)

            with patch("app.main.predict", side_effect=RuntimeError("Unexpected failure")):
                response = client.post(
                    "/api/predict",
                    json=payload,
                    cookies={"session_id": session_id},
                )

            assert response.status_code == 500
            data = response.json()
            assert data["error"] == "Unexpected failure"
            assert data["operation"] == "prediction"
        finally:
            session_store.delete_session(session_id)
