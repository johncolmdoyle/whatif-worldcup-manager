"""Integration tests for API endpoint error responses and full lifecycle flow.

Tests verify that error responses match the design spec format:
- 400: {"error": string} or {"error": string, "missingFields": string[]}
- 413: {"error": "File exceeds 50 MB limit"}
- 500: {"error": string, "operation": string}

And that the full lifecycle flow works correctly:
- Upload PDF → session created with MatchData
- GET session → returns stored MatchData
- POST predict → returns PredictedOutcome
- DELETE session → returns 204
- GET session after delete → returns 401
"""

import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import (
    MatchData,
    MatchEvent,
    MatchStatistics,
    Player,
    Score,
    TeamData,
)
from app.pdf_parser import PDFParseError, ParseResult
from app.session import session_store


@pytest.fixture
def client():
    """Create an async test client for the FastAPI app."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ==============================================================================
# POST /api/upload — Error Response Tests
# ==============================================================================


class TestUploadErrorResponses:
    """Tests for POST /api/upload error responses."""

    async def test_400_non_pdf_file(self, client):
        """400 response for non-PDF file has correct format: {"error": string}."""
        async with client:
            response = await client.post(
                "/api/upload",
                files={"file": ("test.txt", b"hello world", "text/plain")},
            )

        assert response.status_code == 400
        body = response.json()
        assert "error" in body
        assert isinstance(body["error"], str)
        assert body["error"] == "Only PDF files are accepted"

    async def test_413_oversized_file(self, client):
        """413 response for oversized file has correct format: {"error": "File exceeds 50 MB limit"}."""
        # Create a file slightly over 50 MB
        oversized_content = b"x" * (50 * 1024 * 1024 + 1)

        async with client:
            response = await client.post(
                "/api/upload",
                files={"file": ("large.pdf", oversized_content, "application/pdf")},
            )

        assert response.status_code == 413
        body = response.json()
        assert body == {"error": "File exceeds 50 MB limit"}

    async def test_400_pdf_parse_error_with_missing_fields(self, client):
        """400 response for PDFParseError has format: {"error": string, "missingFields": string[]}."""
        mock_error = PDFParseError(
            "Could not extract lineup data",
            missing_fields=["homeTeam.startingLineup", "awayTeam.startingLineup"],
        )

        with patch("app.main.parse_match_report", side_effect=mock_error):
            async with client:
                response = await client.post(
                    "/api/upload",
                    files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
                )

        assert response.status_code == 400
        body = response.json()
        assert "error" in body
        assert isinstance(body["error"], str)
        assert "missingFields" in body
        assert isinstance(body["missingFields"], list)
        assert all(isinstance(f, str) for f in body["missingFields"])
        assert body["error"] == "Could not extract lineup data"
        assert body["missingFields"] == ["homeTeam.startingLineup", "awayTeam.startingLineup"]

    async def test_400_pdf_parse_error_empty_missing_fields(self, client):
        """400 response for PDFParseError with no missing fields still includes the key."""
        mock_error = PDFParseError("PDF file is empty (0 bytes)")

        with patch("app.main.parse_match_report", side_effect=mock_error):
            async with client:
                response = await client.post(
                    "/api/upload",
                    files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
                )

        assert response.status_code == 400
        body = response.json()
        assert "error" in body
        assert isinstance(body["error"], str)
        assert "missingFields" in body
        assert isinstance(body["missingFields"], list)
        assert body["missingFields"] == []

    async def test_500_internal_parsing_error(self, client):
        """500 response for internal failure has format: {"error": string, "operation": string}."""
        with patch(
            "app.main.parse_match_report",
            side_effect=RuntimeError("Unexpected segfault in parser"),
        ):
            async with client:
                response = await client.post(
                    "/api/upload",
                    files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
                )

        assert response.status_code == 500
        body = response.json()
        assert "error" in body
        assert isinstance(body["error"], str)
        assert "operation" in body
        assert isinstance(body["operation"], str)
        assert body["operation"] == "pdf_parsing"
        assert "Unexpected segfault" in body["error"]


# ==============================================================================
# POST /api/predict — Error Response Tests
# ==============================================================================


class TestPredictErrorResponses:
    """Tests for POST /api/predict error responses."""

    @pytest.fixture
    def session_cookie(self):
        """Create a valid session with mock match data."""
        import uuid

        from app.models import (
            MatchData,
            MatchStatistics,
            Player,
            Score,
            TeamData,
        )
        from app.session import session_store

        # Create a valid MatchData object
        players = [
            Player(name=f"Player {i}", squadNumber=i, position="MID")
            for i in range(1, 12)
        ]
        subs = [
            Player(name=f"Sub {i}", squadNumber=i + 11, position="DEF")
            for i in range(1, 6)
        ]
        stats = MatchStatistics(
            possessionPct=55.0, shotsOnTarget=5, totalShots=12, passes=450, fouls=10
        )
        match_data = MatchData(
            matchId=str(uuid.uuid4()),
            homeTeam=TeamData(
                name="Team A",
                startingLineup=players,
                substitutes=subs,
                statistics=stats,
            ),
            awayTeam=TeamData(
                name="Team B",
                startingLineup=players,
                substitutes=subs,
                statistics=stats,
            ),
            events=[],
            actualScore=Score(home=2, away=1),
        )

        session_id = session_store.create_session(match_data)
        return {"session_id": session_id}

    async def test_400_home_lineup_wrong_count(self, client, session_cookie):
        """400 response for wrong lineup count has format: {"error": string}."""
        payload = {
            "homeLineup": [
                {"name": f"Player {i}", "squadNumber": i, "position": "MID"}
                for i in range(1, 10)  # Only 9 players
            ],
            "awayLineup": [
                {"name": f"Player {i}", "squadNumber": i, "position": "MID"}
                for i in range(1, 12)
            ],
        }

        async with client:
            response = await client.post(
                "/api/predict",
                json=payload,
                cookies=session_cookie,
            )

        assert response.status_code == 400
        body = response.json()
        assert "error" in body
        assert isinstance(body["error"], str)
        assert "11" in body["error"]
        assert "Home" in body["error"] or "home" in body["error"]

    async def test_400_away_lineup_wrong_count(self, client, session_cookie):
        """400 response for wrong away lineup count has format: {"error": string}."""
        payload = {
            "homeLineup": [
                {"name": f"Player {i}", "squadNumber": i, "position": "MID"}
                for i in range(1, 12)
            ],
            "awayLineup": [
                {"name": f"Player {i}", "squadNumber": i, "position": "MID"}
                for i in range(1, 14)  # 13 players
            ],
        }

        async with client:
            response = await client.post(
                "/api/predict",
                json=payload,
                cookies=session_cookie,
            )

        assert response.status_code == 400
        body = response.json()
        assert "error" in body
        assert isinstance(body["error"], str)
        assert "11" in body["error"]
        assert "Away" in body["error"] or "away" in body["error"]

    async def test_500_prediction_engine_failure(self, client, session_cookie):
        """500 response for engine failure has format: {"error": string, "operation": string}."""
        payload = {
            "homeLineup": [
                {"name": f"Player {i}", "squadNumber": i, "position": "MID"}
                for i in range(1, 12)
            ],
            "awayLineup": [
                {"name": f"Player {i}", "squadNumber": i, "position": "MID"}
                for i in range(1, 12)
            ],
        }

        with patch(
            "app.main.predict",
            side_effect=RuntimeError("Division by zero in scoring model"),
        ):
            async with client:
                response = await client.post(
                    "/api/predict",
                    json=payload,
                    cookies=session_cookie,
                )

        assert response.status_code == 500
        body = response.json()
        assert "error" in body
        assert isinstance(body["error"], str)
        assert "operation" in body
        assert isinstance(body["operation"], str)
        assert body["operation"] == "prediction"
        assert "Division by zero" in body["error"]

    async def test_401_no_session(self, client):
        """401 response for missing session has correct format."""
        payload = {
            "homeLineup": [
                {"name": f"Player {i}", "squadNumber": i, "position": "MID"}
                for i in range(1, 12)
            ],
            "awayLineup": [
                {"name": f"Player {i}", "squadNumber": i, "position": "MID"}
                for i in range(1, 12)
            ],
        }

        async with client:
            response = await client.post("/api/predict", json=payload)

        assert response.status_code == 401


# ==============================================================================
# Full Lifecycle Integration Tests
# ==============================================================================


def _build_match_data() -> MatchData:
    """Build a realistic MatchData object for integration testing."""
    home_players = [
        Player(name=f"Home Player {i}", squadNumber=i, position="GK" if i == 1 else "DEF" if i <= 4 else "MID" if i <= 8 else "FWD")
        for i in range(1, 12)
    ]
    away_players = [
        Player(name=f"Away Player {i}", squadNumber=i, position="GK" if i == 1 else "DEF" if i <= 4 else "MID" if i <= 8 else "FWD")
        for i in range(1, 12)
    ]
    home_subs = [
        Player(name=f"Home Sub {i}", squadNumber=i + 11, position="MID")
        for i in range(1, 6)
    ]
    away_subs = [
        Player(name=f"Away Sub {i}", squadNumber=i + 11, position="MID")
        for i in range(1, 6)
    ]
    stats_home = MatchStatistics(
        possessionPct=55.0, shotsOnTarget=6, totalShots=14, passes=500, fouls=12
    )
    stats_away = MatchStatistics(
        possessionPct=45.0, shotsOnTarget=4, totalShots=10, passes=400, fouls=14
    )
    return MatchData(
        matchId=str(uuid.uuid4()),
        homeTeam=TeamData(
            name="Brazil",
            startingLineup=home_players,
            substitutes=home_subs,
            statistics=stats_home,
        ),
        awayTeam=TeamData(
            name="Germany",
            startingLineup=away_players,
            substitutes=away_subs,
            statistics=stats_away,
        ),
        events=[
            MatchEvent(type="goal", minute=23, playerName="Home Player 9", teamName="Brazil"),
            MatchEvent(type="goal", minute=67, playerName="Away Player 10", teamName="Germany"),
        ],
        actualScore=Score(home=2, away=1),
    )


class TestFullLifecycleIntegration:
    """Integration tests for the complete API lifecycle flow.

    Tests the full flow: Upload → Get Session → Predict → Delete → Verify 401.
    """

    async def test_full_lifecycle_upload_to_delete(self):
        """Full lifecycle: upload PDF, get session, predict, delete session, verify 401."""
        match_data = _build_match_data()
        parse_result = ParseResult(match_data=match_data, missing_fields=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Step 1: Upload PDF → expect 200 with matchData and session cookie
            with patch("app.main.parse_match_report", return_value=parse_result):
                upload_response = await client.post(
                    "/api/upload",
                    files={"file": ("match_report.pdf", b"%PDF-1.4 fake content", "application/pdf")},
                )

            assert upload_response.status_code == 200
            upload_body = upload_response.json()
            assert "matchData" in upload_body
            assert upload_body["matchData"]["homeTeam"]["name"] == "Brazil"
            assert upload_body["matchData"]["awayTeam"]["name"] == "Germany"
            assert len(upload_body["matchData"]["homeTeam"]["startingLineup"]) == 11
            assert len(upload_body["matchData"]["awayTeam"]["startingLineup"]) == 11

            # Verify session cookie was set
            assert "session_id" in client.cookies

            # Step 2: GET /api/session → expect 200 with the same matchData
            session_response = await client.get("/api/session")

            assert session_response.status_code == 200
            session_body = session_response.json()
            assert "matchData" in session_body
            assert session_body["matchData"]["homeTeam"]["name"] == "Brazil"
            assert session_body["matchData"]["awayTeam"]["name"] == "Germany"
            assert session_body["matchData"]["actualScore"] == {"home": 2, "away": 1}

            # Step 3: POST /api/predict with valid lineups → expect 200 with PredictedOutcome
            predict_payload = {
                "homeLineup": [
                    {"name": f"Home Player {i}", "squadNumber": i, "position": "GK" if i == 1 else "DEF" if i <= 4 else "MID" if i <= 8 else "FWD"}
                    for i in range(1, 12)
                ],
                "awayLineup": [
                    {"name": f"Away Player {i}", "squadNumber": i, "position": "GK" if i == 1 else "DEF" if i <= 4 else "MID" if i <= 8 else "FWD"}
                    for i in range(1, 12)
                ],
            }

            predict_response = await client.post("/api/predict", json=predict_payload)

            assert predict_response.status_code == 200
            predict_body = predict_response.json()
            assert "predictedOutcome" in predict_body
            outcome = predict_body["predictedOutcome"]
            assert "predictedScore" in outcome
            assert outcome["predictedScore"]["home"] >= 0
            assert outcome["predictedScore"]["away"] >= 0
            assert "confidencePct" in outcome
            assert 0 <= outcome["confidencePct"] <= 100
            assert "contributingFactors" in outcome
            assert 3 <= len(outcome["contributingFactors"]) <= 5
            assert "modifiedHomeLineup" in outcome
            assert "modifiedAwayLineup" in outcome
            assert len(outcome["modifiedHomeLineup"]) == 11
            assert len(outcome["modifiedAwayLineup"]) == 11

            # Step 4: DELETE /api/session → expect 204
            delete_response = await client.delete("/api/session")

            assert delete_response.status_code == 204

            # Step 5: GET /api/session after delete → expect 401
            expired_response = await client.get("/api/session")

            assert expired_response.status_code == 401

    async def test_lifecycle_predict_with_modified_lineup(self):
        """Predict with a modified lineup (swap a player with a substitute)."""
        match_data = _build_match_data()
        parse_result = ParseResult(match_data=match_data, missing_fields=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Upload to establish a session
            with patch("app.main.parse_match_report", return_value=parse_result):
                upload_response = await client.post(
                    "/api/upload",
                    files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
                )
            assert upload_response.status_code == 200

            # Predict with a modified home lineup — swap FWD player 9 with sub
            modified_home = [
                {"name": f"Home Player {i}", "squadNumber": i, "position": "GK" if i == 1 else "DEF" if i <= 4 else "MID" if i <= 8 else "FWD"}
                for i in range(1, 12)
            ]
            # Swap player 9 (FWD) with "Home Sub 1" (MID)
            modified_home[8] = {"name": "Home Sub 1", "squadNumber": 12, "position": "MID"}

            predict_payload = {
                "homeLineup": modified_home,
                "awayLineup": [
                    {"name": f"Away Player {i}", "squadNumber": i, "position": "GK" if i == 1 else "DEF" if i <= 4 else "MID" if i <= 8 else "FWD"}
                    for i in range(1, 12)
                ],
            }

            predict_response = await client.post("/api/predict", json=predict_payload)

            assert predict_response.status_code == 200
            outcome = predict_response.json()["predictedOutcome"]
            assert outcome["predictedScore"]["home"] >= 0
            assert outcome["predictedScore"]["away"] >= 0
            assert 0 <= outcome["confidencePct"] <= 100
            assert 3 <= len(outcome["contributingFactors"]) <= 5

    async def test_lifecycle_upload_with_partial_extraction(self):
        """Upload with partial extraction returns matchData and missingFields."""
        match_data = _build_match_data()
        parse_result = ParseResult(
            match_data=match_data,
            missing_fields=["awayTeam.substitutes"],
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.main.parse_match_report", return_value=parse_result):
                response = await client.post(
                    "/api/upload",
                    files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
                )

            assert response.status_code == 200
            body = response.json()
            assert "matchData" in body
            assert "missingFields" in body
            assert body["missingFields"] == ["awayTeam.substitutes"]

    async def test_lifecycle_delete_then_predict_returns_401(self):
        """After deleting a session, predict returns 401."""
        match_data = _build_match_data()
        parse_result = ParseResult(match_data=match_data, missing_fields=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Upload
            with patch("app.main.parse_match_report", return_value=parse_result):
                await client.post(
                    "/api/upload",
                    files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
                )

            # Delete session
            delete_response = await client.delete("/api/session")
            assert delete_response.status_code == 204

            # Predict after delete → should be 401
            predict_payload = {
                "homeLineup": [
                    {"name": f"Player {i}", "squadNumber": i, "position": "MID"}
                    for i in range(1, 12)
                ],
                "awayLineup": [
                    {"name": f"Player {i}", "squadNumber": i, "position": "MID"}
                    for i in range(1, 12)
                ],
            }
            predict_response = await client.post("/api/predict", json=predict_payload)
            assert predict_response.status_code == 401
