"""End-to-end integration tests for the FIFA Match Predictor.

These tests exercise the full application flow using FastAPI's TestClient
with mocked PDF parsing, covering:
- Task 16.3: Full flow — upload PDF, view extraction summary, edit lineup,
  predict, view result, edit again, predict again
- Task 16.4: Error flows — invalid file upload, session expiry, prediction
  engine error with retry
- Task 16.5: Clear session flow with confirmation (DELETE /api/session)
"""

import uuid
from datetime import datetime, timedelta
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
from app.session import SESSION_TTL_SECONDS, session_store


# ==============================================================================
# Fixtures
# ==============================================================================


def _build_realistic_match_data() -> MatchData:
    """Build a realistic MatchData object for e2e testing."""
    home_players = [
        Player(name="Home GK", squadNumber=1, position="GK"),
        Player(name="Home DEF 1", squadNumber=2, position="DEF"),
        Player(name="Home DEF 2", squadNumber=3, position="DEF"),
        Player(name="Home DEF 3", squadNumber=4, position="DEF"),
        Player(name="Home DEF 4", squadNumber=5, position="DEF"),
        Player(name="Home MID 1", squadNumber=6, position="MID"),
        Player(name="Home MID 2", squadNumber=7, position="MID"),
        Player(name="Home MID 3", squadNumber=8, position="MID"),
        Player(name="Home FWD 1", squadNumber=9, position="FWD"),
        Player(name="Home FWD 2", squadNumber=10, position="FWD"),
        Player(name="Home FWD 3", squadNumber=11, position="FWD"),
    ]
    away_players = [
        Player(name="Away GK", squadNumber=1, position="GK"),
        Player(name="Away DEF 1", squadNumber=2, position="DEF"),
        Player(name="Away DEF 2", squadNumber=3, position="DEF"),
        Player(name="Away DEF 3", squadNumber=4, position="DEF"),
        Player(name="Away DEF 4", squadNumber=5, position="DEF"),
        Player(name="Away MID 1", squadNumber=6, position="MID"),
        Player(name="Away MID 2", squadNumber=7, position="MID"),
        Player(name="Away MID 3", squadNumber=8, position="MID"),
        Player(name="Away FWD 1", squadNumber=9, position="FWD"),
        Player(name="Away FWD 2", squadNumber=10, position="FWD"),
        Player(name="Away FWD 3", squadNumber=11, position="FWD"),
    ]
    home_subs = [
        Player(name="Home Sub GK", squadNumber=12, position="GK"),
        Player(name="Home Sub DEF", squadNumber=13, position="DEF"),
        Player(name="Home Sub MID", squadNumber=14, position="MID"),
        Player(name="Home Sub FWD", squadNumber=15, position="FWD"),
    ]
    away_subs = [
        Player(name="Away Sub GK", squadNumber=12, position="GK"),
        Player(name="Away Sub DEF", squadNumber=13, position="DEF"),
        Player(name="Away Sub MID", squadNumber=14, position="MID"),
        Player(name="Away Sub FWD", squadNumber=15, position="FWD"),
    ]
    home_stats = MatchStatistics(
        possessionPct=58.0, shotsOnTarget=7, totalShots=15, passes=520, fouls=10
    )
    away_stats = MatchStatistics(
        possessionPct=42.0, shotsOnTarget=4, totalShots=11, passes=380, fouls=14
    )

    return MatchData(
        matchId=str(uuid.uuid4()),
        homeTeam=TeamData(
            name="Brazil",
            startingLineup=home_players,
            substitutes=home_subs,
            statistics=home_stats,
        ),
        awayTeam=TeamData(
            name="Argentina",
            startingLineup=away_players,
            substitutes=away_subs,
            statistics=away_stats,
        ),
        events=[
            MatchEvent(type="goal", minute=23, playerName="Home FWD 1", teamName="Brazil"),
            MatchEvent(type="goal", minute=55, playerName="Home FWD 2", teamName="Brazil"),
            MatchEvent(type="goal", minute=78, playerName="Away FWD 1", teamName="Argentina"),
            MatchEvent(type="yellow_card", minute=34, playerName="Home MID 1", teamName="Brazil"),
            MatchEvent(type="substitution", minute=70, playerName="Home Sub MID", teamName="Brazil", relatedPlayerName="Home MID 3"),
        ],
        actualScore=Score(home=2, away=1),
    )


def _lineup_to_dict_list(players: list[Player]) -> list[dict]:
    """Convert a list of Player models to JSON-serializable dicts."""
    return [
        {"name": p.name, "squadNumber": p.squadNumber, "position": p.position}
        for p in players
    ]


# ==============================================================================
# Task 16.3: Full Flow Tests
# ==============================================================================


class TestFullFlowE2E:
    """E2E tests for the happy path: upload → summary → edit → predict → result → edit → predict."""

    async def test_upload_pdf_view_summary_edit_predict_edit_predict_again(self):
        """Complete flow: upload, view extraction summary, edit lineup, predict,
        view result, edit lineup again, predict again with different changes."""
        match_data = _build_realistic_match_data()
        parse_result = ParseResult(match_data=match_data, missing_fields=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # --- Step 1: Upload PDF ---
            with patch("app.main.parse_match_report", return_value=parse_result):
                upload_resp = await client.post(
                    "/api/upload",
                    files={"file": ("match.pdf", b"%PDF-1.4 content", "application/pdf")},
                )

            assert upload_resp.status_code == 200
            upload_body = upload_resp.json()

            # --- Step 2: View Extraction Summary ---
            assert "matchData" in upload_body
            md = upload_body["matchData"]
            assert md["homeTeam"]["name"] == "Brazil"
            assert md["awayTeam"]["name"] == "Argentina"
            assert len(md["homeTeam"]["startingLineup"]) == 11
            assert len(md["awayTeam"]["startingLineup"]) == 11
            assert len(md["homeTeam"]["substitutes"]) == 4
            assert len(md["awayTeam"]["substitutes"]) == 4
            assert len(md["events"]) == 5
            assert md["actualScore"] == {"home": 2, "away": 1}
            # Statistics present
            assert md["homeTeam"]["statistics"]["possessionPct"] == 58.0
            assert md["awayTeam"]["statistics"]["shotsOnTarget"] == 4

            # --- Step 3: Edit Lineup (unchanged) and Predict ---
            original_home = _lineup_to_dict_list(match_data.homeTeam.startingLineup)
            original_away = _lineup_to_dict_list(match_data.awayTeam.startingLineup)

            predict_resp = await client.post(
                "/api/predict",
                json={"homeLineup": original_home, "awayLineup": original_away},
            )

            assert predict_resp.status_code == 200
            outcome1 = predict_resp.json()["predictedOutcome"]

            # --- Step 4: View Result ---
            assert outcome1["predictedScore"]["home"] >= 0
            assert outcome1["predictedScore"]["away"] >= 0
            assert 0 <= outcome1["confidencePct"] <= 100
            assert 3 <= len(outcome1["contributingFactors"]) <= 5
            assert len(outcome1["modifiedHomeLineup"]) == 11
            assert len(outcome1["modifiedAwayLineup"]) == 11

            # With unchanged lineup, score should be within ±1 of actual
            assert abs(outcome1["predictedScore"]["home"] - 2) <= 1
            assert abs(outcome1["predictedScore"]["away"] - 1) <= 1

            # --- Step 5: Edit Lineup Again (swap home FWD with sub) ---
            modified_home = original_home.copy()
            # Replace Home FWD 1 (goal scorer) with Home Sub FWD
            modified_home[8] = {"name": "Home Sub FWD", "squadNumber": 15, "position": "FWD"}

            predict_resp2 = await client.post(
                "/api/predict",
                json={"homeLineup": modified_home, "awayLineup": original_away},
            )

            assert predict_resp2.status_code == 200
            outcome2 = predict_resp2.json()["predictedOutcome"]

            # --- Step 6: View Second Result ---
            assert outcome2["predictedScore"]["home"] >= 0
            assert outcome2["predictedScore"]["away"] >= 0
            assert 0 <= outcome2["confidencePct"] <= 100
            assert 3 <= len(outcome2["contributingFactors"]) <= 5

            # Confidence should be lower with changes (goal scorer removed)
            assert outcome2["confidencePct"] <= outcome1["confidencePct"]

    async def test_session_persists_across_multiple_predictions(self):
        """Session remains valid across multiple prediction requests."""
        match_data = _build_realistic_match_data()
        parse_result = ParseResult(match_data=match_data, missing_fields=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.main.parse_match_report", return_value=parse_result):
                await client.post(
                    "/api/upload",
                    files={"file": ("match.pdf", b"%PDF-1.4", "application/pdf")},
                )

            lineup = _lineup_to_dict_list(match_data.homeTeam.startingLineup)
            away_lineup = _lineup_to_dict_list(match_data.awayTeam.startingLineup)

            # Make 3 successive predictions
            for _ in range(3):
                resp = await client.post(
                    "/api/predict",
                    json={"homeLineup": lineup, "awayLineup": away_lineup},
                )
                assert resp.status_code == 200
                assert "predictedOutcome" in resp.json()

            # Session should still be valid
            session_resp = await client.get("/api/session")
            assert session_resp.status_code == 200


# ==============================================================================
# Task 16.4: Error Flow Tests
# ==============================================================================


class TestErrorFlowsE2E:
    """E2E tests for error scenarios: invalid upload, session expiry, prediction error with retry."""

    async def test_invalid_file_upload_non_pdf(self):
        """Uploading a non-PDF file returns 400 with clear error message."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/upload",
                files={"file": ("document.txt", b"Hello world", "text/plain")},
            )

        assert resp.status_code == 400
        body = resp.json()
        assert body["error"] == "Only PDF files are accepted"

    async def test_invalid_file_upload_oversized(self):
        """Uploading an oversized PDF returns 413."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            oversized = b"x" * (50 * 1024 * 1024 + 1)
            resp = await client.post(
                "/api/upload",
                files={"file": ("big.pdf", oversized, "application/pdf")},
            )

        assert resp.status_code == 413
        assert resp.json()["error"] == "File exceeds 50 MB limit"

    async def test_session_expiry_returns_401_on_get(self):
        """An expired session returns 401 on GET /api/session."""
        match_data = _build_realistic_match_data()
        parse_result = ParseResult(match_data=match_data, missing_fields=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.main.parse_match_report", return_value=parse_result):
                upload_resp = await client.post(
                    "/api/upload",
                    files={"file": ("match.pdf", b"%PDF-1.4", "application/pdf")},
                )
            assert upload_resp.status_code == 200

            # Simulate session expiry by manipulating the session store timestamp
            session_id = client.cookies.get("session_id")
            assert session_id is not None
            entry = session_store._sessions.get(session_id)
            assert entry is not None
            # Set last_accessed to 31 minutes ago
            entry["last_accessed"] = datetime.utcnow() - timedelta(seconds=SESSION_TTL_SECONDS + 60)

            # Now GET /api/session should return 401
            resp = await client.get("/api/session")
            assert resp.status_code == 401
            body = resp.json()
            assert body["detail"]["error"] == "session_expired"

    async def test_session_expiry_returns_401_on_predict(self):
        """An expired session returns 401 on POST /api/predict."""
        match_data = _build_realistic_match_data()
        parse_result = ParseResult(match_data=match_data, missing_fields=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.main.parse_match_report", return_value=parse_result):
                await client.post(
                    "/api/upload",
                    files={"file": ("match.pdf", b"%PDF-1.4", "application/pdf")},
                )

            # Expire the session
            session_id = client.cookies.get("session_id")
            entry = session_store._sessions.get(session_id)
            entry["last_accessed"] = datetime.utcnow() - timedelta(seconds=SESSION_TTL_SECONDS + 60)

            lineup = _lineup_to_dict_list(match_data.homeTeam.startingLineup)
            away_lineup = _lineup_to_dict_list(match_data.awayTeam.startingLineup)

            resp = await client.post(
                "/api/predict",
                json={"homeLineup": lineup, "awayLineup": away_lineup},
            )
            assert resp.status_code == 401

    async def test_prediction_engine_error_then_retry_succeeds(self):
        """Prediction engine error returns 500 with operation; retry after fix succeeds."""
        match_data = _build_realistic_match_data()
        parse_result = ParseResult(match_data=match_data, missing_fields=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.main.parse_match_report", return_value=parse_result):
                await client.post(
                    "/api/upload",
                    files={"file": ("match.pdf", b"%PDF-1.4", "application/pdf")},
                )

            lineup = _lineup_to_dict_list(match_data.homeTeam.startingLineup)
            away_lineup = _lineup_to_dict_list(match_data.awayTeam.startingLineup)

            # First attempt: prediction engine raises an error
            with patch("app.main.predict", side_effect=RuntimeError("Internal engine error")):
                resp1 = await client.post(
                    "/api/predict",
                    json={"homeLineup": lineup, "awayLineup": away_lineup},
                )

            assert resp1.status_code == 500
            body = resp1.json()
            assert body["operation"] == "prediction"
            assert "Internal engine error" in body["error"]

            # Retry: same request without mock — prediction engine works normally
            resp2 = await client.post(
                "/api/predict",
                json={"homeLineup": lineup, "awayLineup": away_lineup},
            )

            assert resp2.status_code == 200
            assert "predictedOutcome" in resp2.json()

    async def test_prediction_validation_error_invalid_lineup_size(self):
        """Submitting fewer than 11 players returns 400."""
        match_data = _build_realistic_match_data()
        parse_result = ParseResult(match_data=match_data, missing_fields=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.main.parse_match_report", return_value=parse_result):
                await client.post(
                    "/api/upload",
                    files={"file": ("match.pdf", b"%PDF-1.4", "application/pdf")},
                )

            # Only 9 home players
            short_lineup = _lineup_to_dict_list(match_data.homeTeam.startingLineup[:9])
            away_lineup = _lineup_to_dict_list(match_data.awayTeam.startingLineup)

            resp = await client.post(
                "/api/predict",
                json={"homeLineup": short_lineup, "awayLineup": away_lineup},
            )

            assert resp.status_code == 400
            assert "11" in resp.json()["error"]


# ==============================================================================
# Task 16.5: Clear Session Flow Tests
# ==============================================================================


class TestClearSessionFlowE2E:
    """E2E tests for the clear session flow (DELETE /api/session)."""

    async def test_clear_session_returns_204_and_invalidates(self):
        """DELETE /api/session returns 204 and subsequent requests get 401."""
        match_data = _build_realistic_match_data()
        parse_result = ParseResult(match_data=match_data, missing_fields=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Upload to create session
            with patch("app.main.parse_match_report", return_value=parse_result):
                upload_resp = await client.post(
                    "/api/upload",
                    files={"file": ("match.pdf", b"%PDF-1.4", "application/pdf")},
                )
            assert upload_resp.status_code == 200
            assert "session_id" in client.cookies

            # Confirm session is active
            session_resp = await client.get("/api/session")
            assert session_resp.status_code == 200

            # Clear session (simulates user confirming dialog)
            delete_resp = await client.delete("/api/session")
            assert delete_resp.status_code == 204

            # Session is now invalid — GET returns 401
            expired_resp = await client.get("/api/session")
            assert expired_resp.status_code == 401

            # Predict also returns 401
            lineup = _lineup_to_dict_list(match_data.homeTeam.startingLineup)
            away_lineup = _lineup_to_dict_list(match_data.awayTeam.startingLineup)
            predict_resp = await client.post(
                "/api/predict",
                json={"homeLineup": lineup, "awayLineup": away_lineup},
            )
            assert predict_resp.status_code == 401

    async def test_clear_session_is_idempotent(self):
        """DELETE /api/session is idempotent — calling it again still returns 204."""
        match_data = _build_realistic_match_data()
        parse_result = ParseResult(match_data=match_data, missing_fields=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.main.parse_match_report", return_value=parse_result):
                await client.post(
                    "/api/upload",
                    files={"file": ("match.pdf", b"%PDF-1.4", "application/pdf")},
                )

            # First delete
            resp1 = await client.delete("/api/session")
            assert resp1.status_code == 204

            # Second delete — still 204 (idempotent)
            resp2 = await client.delete("/api/session")
            assert resp2.status_code == 204

    async def test_clear_session_without_cookie_returns_204(self):
        """DELETE /api/session without a session cookie still returns 204."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/api/session")
            assert resp.status_code == 204

    async def test_can_upload_again_after_clearing_session(self):
        """After clearing a session, user can upload a new PDF and start fresh."""
        match_data = _build_realistic_match_data()
        parse_result = ParseResult(match_data=match_data, missing_fields=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First upload
            with patch("app.main.parse_match_report", return_value=parse_result):
                await client.post(
                    "/api/upload",
                    files={"file": ("match.pdf", b"%PDF-1.4", "application/pdf")},
                )

            # Clear session
            await client.delete("/api/session")

            # Upload again — should work fine
            new_match_data = _build_realistic_match_data()
            new_parse_result = ParseResult(match_data=new_match_data, missing_fields=[])

            with patch("app.main.parse_match_report", return_value=new_parse_result):
                upload_resp = await client.post(
                    "/api/upload",
                    files={"file": ("match2.pdf", b"%PDF-1.4 new", "application/pdf")},
                )

            assert upload_resp.status_code == 200
            assert "matchData" in upload_resp.json()

            # New session should work
            session_resp = await client.get("/api/session")
            assert session_resp.status_code == 200
