"""Tests for the POST /api/upload endpoint."""

import io
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
from app.pdf_parser import ParseResult, PDFParseError


def _make_team(name: str) -> TeamData:
    """Create a valid TeamData for testing."""
    positions = ["GK"] + ["DEF"] * 4 + ["MID"] * 3 + ["FWD"] * 3
    starting = [
        Player(name=f"Player {i}", squadNumber=i, position=positions[i - 1])
        for i in range(1, 12)
    ]
    subs = [
        Player(name=f"Sub {i}", squadNumber=i + 11, position="MID")
        for i in range(1, 4)
    ]
    stats = MatchStatistics(
        possessionPct=50.0, shotsOnTarget=5, totalShots=12, passes=400, fouls=10
    )
    return TeamData(name=name, startingLineup=starting, substitutes=subs, statistics=stats)


def _make_match_data() -> MatchData:
    """Create a valid MatchData for testing."""
    import uuid

    return MatchData(
        matchId=str(uuid.uuid4()),
        homeTeam=_make_team("Home FC"),
        awayTeam=_make_team("Away FC"),
        events=[
            MatchEvent(
                type="goal", minute=23, playerName="Player 9", teamName="Home FC"
            )
        ],
        actualScore=Score(home=1, away=0),
    )


@pytest.fixture
def async_client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestUploadEndpoint:
    """Tests for POST /api/upload."""

    async def test_rejects_non_pdf_file(self, async_client):
        """Non-PDF content type returns 400."""
        file_content = b"not a pdf"
        async with async_client as client:
            response = await client.post(
                "/api/upload",
                files={"file": ("test.txt", io.BytesIO(file_content), "text/plain")},
            )
        assert response.status_code == 400
        assert response.json()["error"] == "Only PDF files are accepted"

    async def test_rejects_oversized_file(self, async_client):
        """File exceeding 50 MB returns 413."""
        # Create a fake large PDF content (just over 50 MB)
        large_content = b"%PDF-" + b"x" * (50 * 1024 * 1024 + 1)
        async with async_client as client:
            response = await client.post(
                "/api/upload",
                files={"file": ("big.pdf", io.BytesIO(large_content), "application/pdf")},
            )
        assert response.status_code == 413
        assert response.json()["error"] == "File exceeds 50 MB limit"

    async def test_returns_400_on_parse_error(self, async_client):
        """PDFParseError from the parser returns 400 with error and missingFields."""
        pdf_content = b"%PDF-1.4 fake content"

        with patch("app.main.parse_match_report") as mock_parse:
            mock_parse.side_effect = PDFParseError(
                "Could not extract lineups",
                missing_fields=["homeTeam.startingLineup"],
            )
            async with async_client as client:
                response = await client.post(
                    "/api/upload",
                    files={"file": ("match.pdf", io.BytesIO(pdf_content), "application/pdf")},
                )

        assert response.status_code == 400
        data = response.json()
        assert "Could not extract lineups" in data["error"]
        assert "homeTeam.startingLineup" in data["missingFields"]

    async def test_successful_upload_returns_match_data(self, async_client):
        """Successful parse returns 200 with matchData and sets session cookie."""
        pdf_content = b"%PDF-1.4 fake content"
        match_data = _make_match_data()

        with patch("app.main.parse_match_report") as mock_parse:
            mock_parse.return_value = ParseResult(match_data=match_data, missing_fields=[])
            async with async_client as client:
                response = await client.post(
                    "/api/upload",
                    files={"file": ("match.pdf", io.BytesIO(pdf_content), "application/pdf")},
                )

        assert response.status_code == 200
        data = response.json()
        assert "matchData" in data
        assert data["matchData"]["matchId"] == match_data.matchId
        assert data["matchData"]["homeTeam"]["name"] == "Home FC"
        assert data["matchData"]["awayTeam"]["name"] == "Away FC"
        # Session cookie should be set
        assert "session_id" in response.cookies

    async def test_successful_upload_with_missing_fields(self, async_client):
        """Parse with missing fields returns 200 with matchData and missingFields."""
        pdf_content = b"%PDF-1.4 fake content"
        match_data = _make_match_data()

        with patch("app.main.parse_match_report") as mock_parse:
            mock_parse.return_value = ParseResult(
                match_data=match_data, missing_fields=["events"]
            )
            async with async_client as client:
                response = await client.post(
                    "/api/upload",
                    files={"file": ("match.pdf", io.BytesIO(pdf_content), "application/pdf")},
                )

        assert response.status_code == 200
        data = response.json()
        assert "matchData" in data
        assert data["missingFields"] == ["events"]
        assert "session_id" in response.cookies
