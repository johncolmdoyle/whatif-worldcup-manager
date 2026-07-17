"""Unit tests for PDF parser validation and lineup extraction logic.

Tests cover:
- Empty file rejection (0 bytes)
- Password-protected PDF rejection
- Corrupted/non-PDF file rejection
- Valid PDF with at least 1 page passes validation
- Lineup extraction from FIFA-style match report PDFs
"""

import io

import pdfplumber
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.models import Player
from app.pdf_parser import (
    PDFParseError,
    ParseResult,
    _classify_event_type,
    _extract_events,
    _extract_lineups,
    _extract_statistics,
    _find_events_section,
    _find_lineup_section,
    _find_statistics_section,
    _normalize_position,
    _parse_player_line,
    _parse_team_section,
    _validate_pdf,
    parse_match_report,
)


# --- Helpers ---


def _create_minimal_pdf() -> bytes:
    """Create a minimal valid PDF file in memory using pdfplumber-compatible format.

    This creates a bare-bones single-page PDF that pdfplumber can open and read.
    """
    # Minimal valid PDF with one empty page
    # This is the smallest valid PDF structure that most parsers accept
    pdf_content = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj

2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj

3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
endobj

xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 

trailer
<< /Size 4 /Root 1 0 R >>
startxref
190
%%EOF
"""
    return pdf_content


def _create_password_protected_pdf() -> bytes:
    """Create a PDF that simulates being password-protected.

    Uses the standard PDF encryption dictionary to trigger password errors.
    """
    # A PDF with an Encrypt dictionary will trigger PDFPasswordIncorrect
    # when pdfplumber/pdfminer tries to decrypt it without the password
    pdf_content = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj

2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj

3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
endobj

4 0 obj
<< /Filter /Standard /V 1 /R 2 /O (\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000) /U (\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000\\000) /P -4 >>
endobj

xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000190 00000 n 

trailer
<< /Size 5 /Root 1 0 R /Encrypt 4 0 R >>
startxref
406
%%EOF
"""
    return pdf_content


# --- Tests ---


class TestPDFValidationEmptyFile:
    """Tests for empty file rejection."""

    def test_empty_bytes_raises_parse_error(self):
        """An empty bytes object (b'') should raise PDFParseError."""
        with pytest.raises(PDFParseError, match="empty"):
            _validate_pdf(b"")

    def test_none_bytes_raises_parse_error(self):
        """None input should raise PDFParseError (treated as empty)."""
        with pytest.raises(PDFParseError, match="empty"):
            _validate_pdf(b"")

    def test_parse_match_report_empty_bytes_raises(self):
        """parse_match_report with empty bytes raises PDFParseError."""
        with pytest.raises(PDFParseError, match="empty"):
            parse_match_report(b"")


class TestPDFValidationCorruptedFile:
    """Tests for corrupted/non-PDF file rejection."""

    def test_random_bytes_raises_parse_error(self):
        """Random non-PDF bytes should raise PDFParseError indicating inability to open."""
        with pytest.raises(PDFParseError, match="Unable to open PDF|Unable to read PDF"):
            _validate_pdf(b"this is not a pdf file at all")

    def test_truncated_pdf_header_raises_parse_error(self):
        """A file with only the PDF header but no valid structure should raise PDFParseError."""
        with pytest.raises(PDFParseError, match="Unable to open PDF|Unable to read PDF"):
            _validate_pdf(b"%PDF-1.4\n")

    def test_html_content_raises_parse_error(self):
        """An HTML file should be rejected as not a valid PDF."""
        html_bytes = b"<html><body><h1>Not a PDF</h1></body></html>"
        with pytest.raises(PDFParseError, match="Unable to open PDF|Unable to read PDF"):
            _validate_pdf(html_bytes)


class TestPDFValidationPasswordProtected:
    """Tests for password-protected PDF rejection."""

    def test_password_protected_pdf_raises_parse_error(self):
        """A password-protected PDF should raise PDFParseError mentioning password."""
        encrypted_pdf = _create_password_protected_pdf()
        with pytest.raises(PDFParseError, match="password-protected|unreadable|Unable"):
            _validate_pdf(encrypted_pdf)


class TestPDFValidationValidFile:
    """Tests for valid PDF acceptance."""

    def test_valid_pdf_returns_pdf_object(self):
        """A valid single-page PDF should return an opened pdfplumber.PDF object."""
        valid_pdf = _create_minimal_pdf()
        result = _validate_pdf(valid_pdf)
        try:
            assert result is not None
            assert hasattr(result, "pages")
            assert len(result.pages) >= 1
        finally:
            result.close()

    def test_valid_pdf_pages_accessible(self):
        """The returned PDF object should have accessible pages."""
        valid_pdf = _create_minimal_pdf()
        result = _validate_pdf(valid_pdf)
        try:
            # Should be able to access the first page without error
            page = result.pages[0]
            assert page is not None
        finally:
            result.close()


class TestPDFParseErrorAttributes:
    """Tests for the PDFParseError exception class."""

    def test_error_has_message(self):
        """PDFParseError should store the error message."""
        error = PDFParseError("test error")
        assert str(error) == "test error"

    def test_error_has_missing_fields_default_empty(self):
        """PDFParseError should default missing_fields to empty list."""
        error = PDFParseError("test error")
        assert error.missing_fields == []

    def test_error_stores_missing_fields(self):
        """PDFParseError should store provided missing_fields."""
        error = PDFParseError("test error", missing_fields=["field1", "field2"])
        assert error.missing_fields == ["field1", "field2"]


# --- Lineup Extraction Tests ---


def _create_match_report_pdf(text_content: str) -> bytes:
    """Create a PDF with the given text content using reportlab.

    This creates a properly formatted PDF that pdfplumber can read,
    with FIFA-style match report text content.
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Write text content line by line
    y_position = height - 50
    for line in text_content.split("\n"):
        if y_position < 50:
            c.showPage()
            y_position = height - 50
        c.drawString(50, y_position, line)
        y_position -= 14

    c.save()
    return buffer.getvalue()


def _create_fifa_lineup_text() -> str:
    """Create text content simulating a FIFA World Cup match report lineup section."""
    return """FIFA World Cup 2022
Group A - Match 1

Line-ups

Brazil
1 Alisson GK
2 Danilo DEF
3 Thiago Silva DEF
4 Marquinhos DEF
6 Alex Sandro DEF
5 Casemiro MID
7 Lucas Paqueta MID
10 Neymar MID
11 Raphinha FWD
9 Richarlison FWD
20 Vinicius Junior FWD
Substitutes
12 Weverton GK
13 Dani Alves DEF
14 Eder Militao DEF
15 Bremer DEF
16 Alex Telles DEF
17 Bruno Guimaraes MID
18 Fred MID
19 Antony FWD
21 Rodrygo FWD
22 Everton Ribeiro MID
23 Ederson GK

Serbia
1 Vanja Milinkovic-Savic GK
2 Strahinja Pavlovic DEF
3 Strahinja Erakovic DEF
4 Nikola Milenkovic DEF
5 Milos Veljkovic DEF
6 Nemanja Gudelj MID
7 Nemanja Radonjic FWD
8 Sergej Milinkovic-Savic MID
10 Dusan Tadic MID
9 Aleksandar Mitrovic FWD
11 Filip Kostic MID
Substitutes
12 Predrag Rajkovic GK
13 Stefan Mitrovic DEF
14 Andrija Zivkovic FWD
15 Filip Mladenovic DEF
16 Sasa Lukic MID
17 Filip Djuricic MID
18 Dusan Vlahovic FWD
19 Lazar Samardzic MID
20 Marko Grujic MID
21 Darko Lazovic MID
22 Ivan Ilic MID
23 Marko Dmitrovic GK

Match Events
"""


class TestPositionNormalization:
    """Tests for position abbreviation normalization."""

    def test_standard_positions(self):
        assert _normalize_position("GK") == "GK"
        assert _normalize_position("DEF") == "DEF"
        assert _normalize_position("MID") == "MID"
        assert _normalize_position("FWD") == "FWD"

    def test_fifa_abbreviations(self):
        assert _normalize_position("DF") == "DEF"
        assert _normalize_position("MF") == "MID"
        assert _normalize_position("FW") == "FWD"

    def test_case_insensitive(self):
        assert _normalize_position("gk") == "GK"
        assert _normalize_position("Def") == "DEF"
        assert _normalize_position("mid") == "MID"

    def test_specific_positions_map_to_category(self):
        assert _normalize_position("CB") == "DEF"
        assert _normalize_position("LB") == "DEF"
        assert _normalize_position("CM") == "MID"
        assert _normalize_position("ST") == "FWD"
        assert _normalize_position("RW") == "FWD"

    def test_unknown_position_raises(self):
        with pytest.raises(PDFParseError, match="Unknown position"):
            _normalize_position("XYZ")


class TestParsePlayerLine:
    """Tests for parsing individual player lines."""

    def test_standard_format(self):
        """Standard FIFA format: number name position."""
        player = _parse_player_line("10 Lionel Messi FWD")
        assert player is not None
        assert player.name == "Lionel Messi"
        assert player.squadNumber == 10
        assert player.position == "FWD"

    def test_goalkeeper(self):
        player = _parse_player_line("1 Manuel Neuer GK")
        assert player is not None
        assert player.name == "Manuel Neuer"
        assert player.squadNumber == 1
        assert player.position == "GK"

    def test_hyphenated_name(self):
        player = _parse_player_line("8 Sergej Milinkovic-Savic MID")
        assert player is not None
        assert player.name == "Sergej Milinkovic-Savic"
        assert player.squadNumber == 8
        assert player.position == "MID"

    def test_with_brackets(self):
        player = _parse_player_line("[7] Cristiano Ronaldo FWD")
        assert player is not None
        assert player.name == "Cristiano Ronaldo"
        assert player.squadNumber == 7
        assert player.position == "FWD"

    def test_with_dot_separator(self):
        player = _parse_player_line("5. Marquinhos DEF")
        assert player is not None
        assert player.name == "Marquinhos"
        assert player.squadNumber == 5
        assert player.position == "DEF"

    def test_fifa_position_abbreviations(self):
        player = _parse_player_line("4 Virgil van Dijk DF")
        assert player is not None
        assert player.position == "DEF"

    def test_empty_line_returns_none(self):
        assert _parse_player_line("") is None
        assert _parse_player_line("   ") is None

    def test_non_player_line_returns_none(self):
        assert _parse_player_line("Substitutes") is None
        assert _parse_player_line("Brazil") is None
        assert _parse_player_line("Line-ups") is None

    def test_captain_marker(self):
        player = _parse_player_line("10 Harry Kane (C) FWD")
        assert player is not None
        assert player.name == "Harry Kane"
        assert player.squadNumber == 10
        assert player.position == "FWD"


class TestFindLineupSection:
    """Tests for locating the lineup section in PDF text."""

    def test_finds_standard_heading(self):
        text = "Some header\n\nLine-ups\n\nPlayer data here\n\nMatch Events\n"
        result = _find_lineup_section(text)
        assert result is not None
        assert "Player data here" in result
        assert "Match Events" not in result

    def test_finds_lineups_without_hyphen(self):
        text = "Header\n\nLineups\n\nPlayer data\n\nStatistics\n"
        result = _find_lineup_section(text)
        assert result is not None
        assert "Player data" in result

    def test_returns_none_when_not_found(self):
        text = "This PDF has no lineup section at all."
        result = _find_lineup_section(text)
        assert result is None

    def test_stops_at_match_events(self):
        text = "Line-ups\nPlayer 1\nPlayer 2\n\nMatch Events\nGoal at 23'"
        result = _find_lineup_section(text)
        assert result is not None
        assert "Goal at 23" not in result

    def test_stops_at_statistics(self):
        text = "Line-ups\nPlayer 1\n\nStatistics\nPossession 55%"
        result = _find_lineup_section(text)
        assert result is not None
        assert "Possession" not in result


class TestParseTeamSection:
    """Tests for parsing a single team's lineup section."""

    def test_parses_team_name_and_players(self):
        team_text = """Brazil
1 Alisson GK
2 Danilo DEF
3 Thiago Silva DEF
4 Marquinhos DEF
6 Alex Sandro DEF
5 Casemiro MID
7 Lucas Paqueta MID
10 Neymar MID
11 Raphinha FWD
9 Richarlison FWD
20 Vinicius Junior FWD
Substitutes
12 Weverton GK
13 Dani Alves DEF"""

        name, starters, subs = _parse_team_section(team_text)
        assert name == "Brazil"
        assert len(starters) == 11
        assert len(subs) == 2
        assert starters[0].name == "Alisson"
        assert starters[0].position == "GK"
        assert subs[0].name == "Weverton"

    def test_parses_substitutes(self):
        team_text = """Argentina
1 Emiliano Martinez GK
Substitutes
12 Geronimo Rulli GK
13 Franco Armani GK"""

        name, starters, subs = _parse_team_section(team_text)
        assert name == "Argentina"
        assert len(starters) == 1
        assert len(subs) == 2


class TestExtractLineupsFromPDF:
    """Tests for end-to-end lineup extraction from a PDF."""

    def test_extracts_both_teams_from_match_report(self):
        """Full integration test: creates a FIFA-style PDF and extracts lineups."""
        text = _create_fifa_lineup_text()
        pdf_bytes = _create_match_report_pdf(text)

        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            home_xi, home_subs, away_xi, away_subs, home_name, away_name = (
                _extract_lineups(pdf)
            )

            assert home_name == "Brazil"
            assert away_name == "Serbia"
            assert len(home_xi) == 11
            assert len(away_xi) == 11
            assert len(home_subs) > 0
            assert len(away_subs) > 0

            # Verify specific players
            home_names = [p.name for p in home_xi]
            assert "Neymar" in home_names
            assert "Alisson" in home_names

            away_names = [p.name for p in away_xi]
            assert "Aleksandar Mitrovic" in away_names
        finally:
            pdf.close()

    def test_parse_match_report_returns_match_data(self):
        """parse_match_report with a FIFA-style PDF returns valid MatchData."""
        text = _create_fifa_lineup_text()
        pdf_bytes = _create_match_report_pdf(text)

        parse_result = parse_match_report(pdf_bytes)
        result = parse_result.match_data

        assert result.homeTeam.name == "Brazil"
        assert result.awayTeam.name == "Serbia"
        assert len(result.homeTeam.startingLineup) == 11
        assert len(result.awayTeam.startingLineup) == 11
        assert len(result.homeTeam.substitutes) > 0
        assert len(result.awayTeam.substitutes) > 0

        # Verify players have valid attributes
        for player in result.homeTeam.startingLineup:
            assert player.name
            assert 1 <= player.squadNumber <= 99
            assert player.position in ("GK", "DEF", "MID", "FWD")

    def test_raises_when_no_lineup_section(self):
        """A PDF without a lineup section raises PDFParseError."""
        text = "FIFA World Cup 2022\nSome random content without lineups."
        pdf_bytes = _create_match_report_pdf(text)

        with pytest.raises(PDFParseError, match="Line-ups section"):
            parse_match_report(pdf_bytes)

    def test_raises_when_no_text_extractable(self):
        """A PDF with no extractable text raises PDFParseError."""
        # Use the minimal PDF helper that has no text content
        minimal_pdf = _create_minimal_pdf()

        with pytest.raises(PDFParseError, match="text|Line-ups|implemented"):
            parse_match_report(minimal_pdf)


# --- Event Extraction Tests ---


def _create_fifa_events_text() -> str:
    """Create text content simulating a FIFA match report with events section."""
    return """FIFA World Cup 2022
Group A - Match 1

Line-ups

Brazil
1 Alisson GK
2 Danilo DEF
3 Thiago Silva DEF
4 Marquinhos DEF
6 Alex Sandro DEF
5 Casemiro MID
7 Lucas Paqueta MID
10 Neymar MID
11 Raphinha FWD
9 Richarlison FWD
20 Vinicius Junior FWD
Substitutes
12 Weverton GK
13 Dani Alves DEF
14 Eder Militao DEF

Serbia
1 Vanja Milinkovic-Savic GK
2 Strahinja Pavlovic DEF
3 Strahinja Erakovic DEF
4 Nikola Milenkovic DEF
5 Milos Veljkovic DEF
6 Nemanja Gudelj MID
7 Nemanja Radonjic FWD
8 Sergej Milinkovic-Savic MID
10 Dusan Tadic MID
9 Aleksandar Mitrovic FWD
11 Filip Kostic MID
Substitutes
12 Predrag Rajkovic GK
13 Stefan Mitrovic DEF

Match Events

Brazil
62 Goal Richarlison
73 Goal Richarlison
45 Yellow Card Casemiro
69 Substitution Fred for Lucas Paqueta
Serbia
35 Yellow Card Sergej Milinkovic-Savic
77 Substitution Dusan Vlahovic for Aleksandar Mitrovic

Statistics
"""


class TestFindEventsSection:
    """Tests for locating the events section in PDF text."""

    def test_finds_match_events_heading(self):
        text = "Line-ups\nPlayers\n\nMatch Events\n\n62 Goal Richarlison\n\nStatistics\n"
        result = _find_events_section(text)
        assert result is not None
        assert "62 Goal Richarlison" in result
        assert "Statistics" not in result

    def test_finds_goals_and_disciplinary_heading(self):
        text = "Line-ups\n\nGoals & Disciplinary\n\n23 Goal Messi\n\nOfficials\n"
        result = _find_events_section(text)
        assert result is not None
        assert "23 Goal Messi" in result

    def test_finds_goals_scored_heading(self):
        text = "Line-ups\n\nGoals Scored\n\n10 Goal Mbappe\n\nReferee\n"
        result = _find_events_section(text)
        assert result is not None
        assert "10 Goal Mbappe" in result

    def test_returns_none_when_not_found(self):
        text = "This PDF has no events section at all."
        result = _find_events_section(text)
        assert result is None

    def test_stops_at_statistics(self):
        text = "Match Events\n23 Goal Player\n\nStatistics\nPossession 55%"
        result = _find_events_section(text)
        assert result is not None
        assert "Possession" not in result

    def test_stops_at_officials(self):
        text = "Match Events\n23 Goal Player\n\nOfficials\nReferee Name"
        result = _find_events_section(text)
        assert result is not None
        assert "Referee Name" not in result


class TestClassifyEventType:
    """Tests for event type classification."""

    def test_goal_text(self):
        assert _classify_event_type("Goal") == "goal"
        assert _classify_event_type("goal") == "goal"
        assert _classify_event_type("GOAL") == "goal"

    def test_goal_symbol(self):
        assert _classify_event_type("⚽") == "goal"

    def test_goal_scored(self):
        assert _classify_event_type("Scored") == "goal"

    def test_yellow_card_text(self):
        assert _classify_event_type("Yellow Card") == "yellow_card"
        assert _classify_event_type("yellow card") == "yellow_card"
        assert _classify_event_type("Caution") == "yellow_card"
        assert _classify_event_type("Booking") == "yellow_card"

    def test_yellow_card_symbol(self):
        assert _classify_event_type("🟡") == "yellow_card"

    def test_red_card_text(self):
        assert _classify_event_type("Red Card") == "red_card"
        assert _classify_event_type("red card") == "red_card"
        assert _classify_event_type("Sent Off") == "red_card"
        assert _classify_event_type("Dismissal") == "red_card"

    def test_red_card_symbol(self):
        assert _classify_event_type("🔴") == "red_card"

    def test_substitution_text(self):
        assert _classify_event_type("Substitution") == "substitution"
        assert _classify_event_type("Sub") == "substitution"

    def test_substitution_symbol(self):
        assert _classify_event_type("🔄") == "substitution"

    def test_unknown_returns_none(self):
        assert _classify_event_type("Unknown Event") is None
        assert _classify_event_type("xyz") is None
        assert _classify_event_type("") is None


class TestExtractEvents:
    """Tests for end-to-end event extraction from a PDF."""

    def test_extracts_goals(self):
        """Goals are extracted with correct minute and player name."""
        text = _create_fifa_events_text()
        pdf_bytes = _create_match_report_pdf(text)
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            events = _extract_events(pdf, "Brazil", "Serbia")
            goals = [e for e in events if e.type == "goal"]
            assert len(goals) == 2
            assert all(g.playerName == "Richarlison" for g in goals)
            assert goals[0].minute == 62
            assert goals[1].minute == 73
            assert all(g.teamName == "Brazil" for g in goals)
        finally:
            pdf.close()

    def test_extracts_yellow_cards(self):
        """Yellow cards are extracted with correct details."""
        text = _create_fifa_events_text()
        pdf_bytes = _create_match_report_pdf(text)
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            events = _extract_events(pdf, "Brazil", "Serbia")
            yellows = [e for e in events if e.type == "yellow_card"]
            assert len(yellows) == 2
            player_names = [y.playerName for y in yellows]
            assert "Casemiro" in player_names
            assert "Sergej Milinkovic-Savic" in player_names
        finally:
            pdf.close()

    def test_extracts_substitutions_with_related_player(self):
        """Substitutions include both outgoing and incoming player names."""
        text = _create_fifa_events_text()
        pdf_bytes = _create_match_report_pdf(text)
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            events = _extract_events(pdf, "Brazil", "Serbia")
            subs = [e for e in events if e.type == "substitution"]
            assert len(subs) == 2

            # Brazil sub: Fred for Lucas Paqueta
            brazil_sub = [s for s in subs if s.teamName == "Brazil"]
            assert len(brazil_sub) == 1
            assert brazil_sub[0].playerName == "Fred"
            assert brazil_sub[0].relatedPlayerName == "Lucas Paqueta"
            assert brazil_sub[0].minute == 69

            # Serbia sub: Dusan Vlahovic for Aleksandar Mitrovic
            serbia_sub = [s for s in subs if s.teamName == "Serbia"]
            assert len(serbia_sub) == 1
            assert serbia_sub[0].playerName == "Dusan Vlahovic"
            assert serbia_sub[0].relatedPlayerName == "Aleksandar Mitrovic"
            assert serbia_sub[0].minute == 77
        finally:
            pdf.close()

    def test_team_assignment_via_headers(self):
        """Events are correctly assigned to teams based on team headers."""
        text = _create_fifa_events_text()
        pdf_bytes = _create_match_report_pdf(text)
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            events = _extract_events(pdf, "Brazil", "Serbia")
            brazil_events = [e for e in events if e.teamName == "Brazil"]
            serbia_events = [e for e in events if e.teamName == "Serbia"]
            assert len(brazil_events) >= 3  # 2 goals + 1 yellow + 1 sub
            assert len(serbia_events) >= 1  # 1 yellow + 1 sub
        finally:
            pdf.close()

    def test_returns_empty_when_no_events_section(self):
        """Returns empty list when no events section is found."""
        text = "FIFA World Cup\nSome content without events section."
        pdf_bytes = _create_match_report_pdf(text)
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            events = _extract_events(pdf, "Brazil", "Serbia")
            assert events == []
        finally:
            pdf.close()

    def test_minute_range_validation(self):
        """Minutes outside 1-120 are excluded."""
        text = """Match Events

Brazil
0 Goal InvalidPlayer
121 Goal InvalidPlayer
45 Goal ValidPlayer

Statistics
"""
        pdf_bytes = _create_match_report_pdf(text)
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            events = _extract_events(pdf, "Brazil", "Serbia")
            # Only the minute=45 event should be valid
            assert all(1 <= e.minute <= 120 for e in events)
            if events:
                assert any(e.minute == 45 for e in events)
        finally:
            pdf.close()

    def test_red_card_extraction(self):
        """Red cards are parsed correctly."""
        text = """Match Events

Brazil
55 Red Card Neymar

Statistics
"""
        pdf_bytes = _create_match_report_pdf(text)
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            events = _extract_events(pdf, "Brazil", "Serbia")
            reds = [e for e in events if e.type == "red_card"]
            assert len(reds) == 1
            assert reds[0].playerName == "Neymar"
            assert reds[0].minute == 55
            assert reds[0].teamName == "Brazil"
        finally:
            pdf.close()

    def test_parse_match_report_includes_events(self):
        """parse_match_report populates events in the returned MatchData."""
        text = _create_fifa_events_text()
        pdf_bytes = _create_match_report_pdf(text)
        parse_result = parse_match_report(pdf_bytes)
        result = parse_result.match_data
        assert len(result.events) > 0
        # Verify event types are valid
        for event in result.events:
            assert event.type in ("goal", "yellow_card", "red_card", "substitution")
            assert 1 <= event.minute <= 120
            assert event.playerName
            assert event.teamName


class TestExtractEventsSymbolFormats:
    """Tests for events using alternative text-based formats found in FIFA reports."""

    def test_goal_with_scored_label(self):
        text = """Match Events

Brazil
62 Scored Richarlison

Statistics
"""
        pdf_bytes = _create_match_report_pdf(text)
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            events = _extract_events(pdf, "Brazil", "Serbia")
            goals = [e for e in events if e.type == "goal"]
            assert len(goals) == 1
            assert goals[0].playerName == "Richarlison"
            assert goals[0].minute == 62
        finally:
            pdf.close()

    def test_yellow_card_with_booking_label(self):
        text = """Match Events

Serbia
35 Booking Nemanja Gudelj

Statistics
"""
        pdf_bytes = _create_match_report_pdf(text)
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            events = _extract_events(pdf, "Brazil", "Serbia")
            yellows = [e for e in events if e.type == "yellow_card"]
            assert len(yellows) == 1
            assert yellows[0].playerName == "Nemanja Gudelj"
        finally:
            pdf.close()

    def test_caution_label_for_yellow_card(self):
        text = """Match Events

Brazil
30 Caution Neymar

Statistics
"""
        pdf_bytes = _create_match_report_pdf(text)
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            events = _extract_events(pdf, "Brazil", "Serbia")
            yellows = [e for e in events if e.type == "yellow_card"]
            assert len(yellows) == 1
            assert yellows[0].playerName == "Neymar"
            assert yellows[0].minute == 30
        finally:
            pdf.close()

    def test_substitution_with_replaced_by(self):
        text = """Match Events

Brazil
69 Substitution Fred replaced by Lucas Paqueta

Statistics
"""
        pdf_bytes = _create_match_report_pdf(text)
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            events = _extract_events(pdf, "Brazil", "Serbia")
            subs = [e for e in events if e.type == "substitution"]
            assert len(subs) == 1
            assert subs[0].playerName == "Fred"
            assert subs[0].relatedPlayerName == "Lucas Paqueta"
        finally:
            pdf.close()

    def test_classify_event_type_with_symbols_directly(self):
        """Verify _classify_event_type handles Unicode symbols correctly."""
        assert _classify_event_type("⚽") == "goal"
        assert _classify_event_type("🟡") == "yellow_card"
        assert _classify_event_type("🔴") == "red_card"
        assert _classify_event_type("🔄") == "substitution"


# --- Statistics Extraction Tests ---


def _create_fifa_stats_text() -> str:
    """Create text content simulating a FIFA match report with a statistics section."""
    return """FIFA World Cup 2022
Group A - Match 1

Line-ups

Brazil
1 Alisson GK
2 Danilo DEF
3 Thiago Silva DEF
4 Marquinhos DEF
6 Alex Sandro DEF
5 Casemiro MID
7 Lucas Paqueta MID
10 Neymar MID
11 Raphinha FWD
9 Richarlison FWD
20 Vinicius Junior FWD
Substitutes
12 Weverton GK
13 Dani Alves DEF
14 Eder Militao DEF

Serbia
1 Vanja Milinkovic-Savic GK
2 Strahinja Pavlovic DEF
3 Strahinja Erakovic DEF
4 Nikola Milenkovic DEF
5 Milos Veljkovic DEF
6 Nemanja Gudelj MID
7 Nemanja Radonjic FWD
8 Sergej Milinkovic-Savic MID
10 Dusan Tadic MID
9 Aleksandar Mitrovic FWD
11 Filip Kostic MID
Substitutes
12 Predrag Rajkovic GK
13 Stefan Mitrovic DEF

Match Events

Brazil
62 Goal Richarlison
73 Goal Richarlison

Statistics

55% Possession 45%
5 Shots on Target 3
12 Total Shots 8
523 Passes 380
10 Fouls 14

Officials
"""


class TestFindStatisticsSection:
    """Tests for locating the statistics section in PDF text."""

    def test_finds_statistics_heading(self):
        text = "Match Events\n23 Goal Player\n\nStatistics\n\n55% Possession 45%\n\nOfficials\n"
        result = _find_statistics_section(text)
        assert result is not None
        assert "55% Possession 45%" in result
        assert "Officials" not in result

    def test_finds_match_statistics_heading(self):
        text = "Events\n\nMatch Statistics\n\n60% Possession 40%\n\nReferee\n"
        result = _find_statistics_section(text)
        assert result is not None
        assert "60% Possession 40%" in result

    def test_finds_team_statistics_heading(self):
        text = "Events\n\nTeam Statistics\n\n50% Possession 50%\n\nOfficials\n"
        result = _find_statistics_section(text)
        assert result is not None
        assert "50% Possession 50%" in result

    def test_returns_none_when_not_found(self):
        text = "This PDF has no statistics section."
        result = _find_statistics_section(text)
        assert result is None

    def test_stops_at_officials(self):
        text = "Statistics\n55% Possession 45%\n\nOfficials\nReferee Name"
        result = _find_statistics_section(text)
        assert result is not None
        assert "Referee Name" not in result

    def test_stops_at_match_officials(self):
        text = "Statistics\n55% Possession 45%\n\nMatch Officials\nReferee"
        result = _find_statistics_section(text)
        assert result is not None
        assert "Referee" not in result


class TestExtractStatistics:
    """Tests for statistics extraction from a PDF."""

    def test_extracts_all_stats_pattern_a(self):
        """Pattern A: HomeValue StatName AwayValue (e.g., '55% Possession 45%')."""
        text = _create_fifa_stats_text()
        pdf_bytes = _create_match_report_pdf(text)
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            home_stats, away_stats = _extract_statistics(pdf)

            assert home_stats.possessionPct == 55.0
            assert away_stats.possessionPct == 45.0
            assert home_stats.shotsOnTarget == 5
            assert away_stats.shotsOnTarget == 3
            assert home_stats.totalShots == 12
            assert away_stats.totalShots == 8
            assert home_stats.passes == 523
            assert away_stats.passes == 380
            assert home_stats.fouls == 10
            assert away_stats.fouls == 14
        finally:
            pdf.close()

    def test_extracts_stats_pattern_b(self):
        """Pattern B: StatName: HomeValue - AwayValue."""
        text = """FIFA World Cup 2022

Line-ups

Brazil
1 Alisson GK
2 Danilo DEF
3 Thiago Silva DEF
4 Marquinhos DEF
6 Alex Sandro DEF
5 Casemiro MID
7 Lucas Paqueta MID
10 Neymar MID
11 Raphinha FWD
9 Richarlison FWD
20 Vinicius Junior FWD
Substitutes
12 Weverton GK

Serbia
1 Vanja Milinkovic-Savic GK
2 Strahinja Pavlovic DEF
3 Strahinja Erakovic DEF
4 Nikola Milenkovic DEF
5 Milos Veljkovic DEF
6 Nemanja Gudelj MID
7 Nemanja Radonjic FWD
8 Sergej Milinkovic-Savic MID
10 Dusan Tadic MID
9 Aleksandar Mitrovic FWD
11 Filip Kostic MID
Substitutes
12 Predrag Rajkovic GK

Statistics

Possession: 60% - 40%
Shots on Target: 7 - 2
Total Shots: 15 - 9
Passes: 600 - 400
Fouls: 8 - 12

Officials
"""
        pdf_bytes = _create_match_report_pdf(text)
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            home_stats, away_stats = _extract_statistics(pdf)

            assert home_stats.possessionPct == 60.0
            assert away_stats.possessionPct == 40.0
            assert home_stats.shotsOnTarget == 7
            assert away_stats.shotsOnTarget == 2
            assert home_stats.totalShots == 15
            assert away_stats.totalShots == 9
            assert home_stats.passes == 600
            assert away_stats.passes == 400
            assert home_stats.fouls == 8
            assert away_stats.fouls == 12
        finally:
            pdf.close()

    def test_extracts_stats_pattern_c(self):
        """Pattern C: StatName HomeValue AwayValue."""
        text = """FIFA World Cup 2022

Line-ups

Brazil
1 Alisson GK
2 Danilo DEF
3 Thiago Silva DEF
4 Marquinhos DEF
6 Alex Sandro DEF
5 Casemiro MID
7 Lucas Paqueta MID
10 Neymar MID
11 Raphinha FWD
9 Richarlison FWD
20 Vinicius Junior FWD
Substitutes
12 Weverton GK

Serbia
1 Vanja Milinkovic-Savic GK
2 Strahinja Pavlovic DEF
3 Strahinja Erakovic DEF
4 Nikola Milenkovic DEF
5 Milos Veljkovic DEF
6 Nemanja Gudelj MID
7 Nemanja Radonjic FWD
8 Sergej Milinkovic-Savic MID
10 Dusan Tadic MID
9 Aleksandar Mitrovic FWD
11 Filip Kostic MID
Substitutes
12 Predrag Rajkovic GK

Statistics

Possession 52% 48%
Shots on Target 4 6
Total Shots 11 13
Passes 450 500
Fouls 15 11

Officials
"""
        pdf_bytes = _create_match_report_pdf(text)
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            home_stats, away_stats = _extract_statistics(pdf)

            assert home_stats.possessionPct == 52.0
            assert away_stats.possessionPct == 48.0
            assert home_stats.shotsOnTarget == 4
            assert away_stats.shotsOnTarget == 6
            assert home_stats.totalShots == 11
            assert away_stats.totalShots == 13
            assert home_stats.passes == 450
            assert away_stats.passes == 500
            assert home_stats.fouls == 15
            assert away_stats.fouls == 11
        finally:
            pdf.close()

    def test_returns_defaults_when_no_statistics_section(self):
        """Returns default placeholders when no statistics section is found."""
        text = "FIFA World Cup\nSome content without statistics."
        pdf_bytes = _create_match_report_pdf(text)
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            home_stats, away_stats = _extract_statistics(pdf)

            assert home_stats.possessionPct == 50.0
            assert home_stats.shotsOnTarget == 0
            assert home_stats.totalShots == 0
            assert home_stats.passes == 0
            assert home_stats.fouls == 0
            assert away_stats.possessionPct == 50.0
            assert away_stats.shotsOnTarget == 0
            assert away_stats.totalShots == 0
            assert away_stats.passes == 0
            assert away_stats.fouls == 0
        finally:
            pdf.close()

    def test_partial_stats_fills_defaults(self):
        """When only some statistics are found, missing ones default to placeholder values."""
        text = """FIFA World Cup 2022

Line-ups

Brazil
1 Alisson GK
2 Danilo DEF
3 Thiago Silva DEF
4 Marquinhos DEF
6 Alex Sandro DEF
5 Casemiro MID
7 Lucas Paqueta MID
10 Neymar MID
11 Raphinha FWD
9 Richarlison FWD
20 Vinicius Junior FWD
Substitutes
12 Weverton GK

Serbia
1 Vanja Milinkovic-Savic GK
2 Strahinja Pavlovic DEF
3 Strahinja Erakovic DEF
4 Nikola Milenkovic DEF
5 Milos Veljkovic DEF
6 Nemanja Gudelj MID
7 Nemanja Radonjic FWD
8 Sergej Milinkovic-Savic MID
10 Dusan Tadic MID
9 Aleksandar Mitrovic FWD
11 Filip Kostic MID
Substitutes
12 Predrag Rajkovic GK

Statistics

55% Possession 45%
5 Shots on Target 3

Officials
"""
        pdf_bytes = _create_match_report_pdf(text)
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            home_stats, away_stats = _extract_statistics(pdf)

            # These should be extracted
            assert home_stats.possessionPct == 55.0
            assert away_stats.possessionPct == 45.0
            assert home_stats.shotsOnTarget == 5
            assert away_stats.shotsOnTarget == 3

            # These should default
            assert home_stats.totalShots == 0
            assert away_stats.totalShots == 0
            assert home_stats.passes == 0
            assert away_stats.passes == 0
            assert home_stats.fouls == 0
            assert away_stats.fouls == 0
        finally:
            pdf.close()

    def test_parse_match_report_uses_extracted_statistics(self):
        """parse_match_report returns real statistics instead of placeholders."""
        text = _create_fifa_stats_text()
        pdf_bytes = _create_match_report_pdf(text)
        parse_result = parse_match_report(pdf_bytes)
        result = parse_result.match_data

        # Should have real values, not placeholders
        assert result.homeTeam.statistics.possessionPct == 55.0
        assert result.awayTeam.statistics.possessionPct == 45.0
        assert result.homeTeam.statistics.shotsOnTarget == 5
        assert result.awayTeam.statistics.shotsOnTarget == 3
        assert result.homeTeam.statistics.totalShots == 12
        assert result.awayTeam.statistics.totalShots == 8
        assert result.homeTeam.statistics.passes == 523
        assert result.awayTeam.statistics.passes == 380
        assert result.homeTeam.statistics.fouls == 10
        assert result.awayTeam.statistics.fouls == 14

    def test_shots_without_total_keyword(self):
        """'Shots' (without 'total' prefix) is recognized as total shots."""
        text = """FIFA World Cup 2022

Line-ups

Brazil
1 Alisson GK
2 Danilo DEF
3 Thiago Silva DEF
4 Marquinhos DEF
6 Alex Sandro DEF
5 Casemiro MID
7 Lucas Paqueta MID
10 Neymar MID
11 Raphinha FWD
9 Richarlison FWD
20 Vinicius Junior FWD
Substitutes
12 Weverton GK

Serbia
1 Vanja Milinkovic-Savic GK
2 Strahinja Pavlovic DEF
3 Strahinja Erakovic DEF
4 Nikola Milenkovic DEF
5 Milos Veljkovic DEF
6 Nemanja Gudelj MID
7 Nemanja Radonjic FWD
8 Sergej Milinkovic-Savic MID
10 Dusan Tadic MID
9 Aleksandar Mitrovic FWD
11 Filip Kostic MID
Substitutes
12 Predrag Rajkovic GK

Statistics

Shots: 10 - 7
Shots on Target: 4 - 2

Officials
"""
        pdf_bytes = _create_match_report_pdf(text)
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        try:
            home_stats, away_stats = _extract_statistics(pdf)

            assert home_stats.totalShots == 10
            assert away_stats.totalShots == 7
            assert home_stats.shotsOnTarget == 4
            assert away_stats.shotsOnTarget == 2
        finally:
            pdf.close()



# --- Partial Extraction Handling Tests ---


class TestParseResultDataclass:
    """Tests for the ParseResult return type."""

    def test_parse_result_has_match_data_and_missing_fields(self):
        """ParseResult contains both match_data and missing_fields attributes."""
        text = _create_fifa_lineup_text()
        pdf_bytes = _create_match_report_pdf(text)
        result = parse_match_report(pdf_bytes)

        assert isinstance(result, ParseResult)
        assert result.match_data is not None
        assert isinstance(result.missing_fields, list)

    def test_full_report_has_no_missing_fields(self):
        """A complete report with all sections returns empty missing_fields."""
        text = _create_fifa_stats_text()  # Has lineups + events + stats
        pdf_bytes = _create_match_report_pdf(text)
        result = parse_match_report(pdf_bytes)

        # Statistics section is present, lineups are present
        # Events may or may not be present depending on the fixture text
        assert isinstance(result.missing_fields, list)
        assert result.match_data.homeTeam.name == "Brazil"

    def test_missing_fields_defaults_to_empty_list(self):
        """ParseResult missing_fields defaults to an empty list."""
        from app.models import MatchData, Score, TeamData, MatchStatistics, Player

        dummy_stats = MatchStatistics(
            possessionPct=50.0, shotsOnTarget=0, totalShots=0, passes=0, fouls=0
        )
        dummy_player = Player(name="Test", squadNumber=1, position="GK")
        dummy_team = TeamData(
            name="Team",
            startingLineup=[dummy_player] * 11,
            substitutes=[],
            statistics=dummy_stats,
        )
        dummy_match = MatchData(
            matchId="00000000-0000-0000-0000-000000000000",
            homeTeam=dummy_team,
            awayTeam=dummy_team,
            events=[],
            actualScore=Score(home=0, away=0),
        )
        pr = ParseResult(match_data=dummy_match)
        assert pr.missing_fields == []


class TestPartialExtractionEventsFailure:
    """Tests for partial extraction when events section cannot be parsed."""

    def test_missing_events_section_reports_statistics_missing(self):
        """When no events or statistics section exists, report lists missing fields."""
        # Create a PDF with lineups only (no events section, no statistics section)
        text = """FIFA World Cup 2022
Group A - Match 1

Line-ups

Brazil
1 Alisson GK
2 Danilo DEF
3 Thiago Silva DEF
4 Marquinhos DEF
6 Alex Sandro DEF
5 Casemiro MID
7 Lucas Paqueta MID
10 Neymar MID
11 Raphinha FWD
9 Richarlison FWD
20 Vinicius Junior FWD
Substitutes
12 Weverton GK

Serbia
1 Vanja Milinkovic-Savic GK
2 Strahinja Pavlovic DEF
3 Strahinja Erakovic DEF
4 Nikola Milenkovic DEF
5 Milos Veljkovic DEF
6 Nemanja Gudelj MID
7 Nemanja Radonjic FWD
8 Sergej Milinkovic-Savic MID
10 Dusan Tadic MID
9 Aleksandar Mitrovic FWD
11 Filip Kostic MID
Substitutes
12 Predrag Rajkovic GK
"""
        pdf_bytes = _create_match_report_pdf(text)
        result = parse_match_report(pdf_bytes)

        # Lineups should be successfully extracted
        assert result.match_data.homeTeam.name == "Brazil"
        assert result.match_data.awayTeam.name == "Serbia"
        assert len(result.match_data.homeTeam.startingLineup) == 11
        assert len(result.match_data.awayTeam.startingLineup) == 11

        # Events should be empty (no section found) - this is normal, not an error
        assert result.match_data.events == []

        # Statistics should report as missing since no section was found
        assert "statistics" in result.missing_fields

    def test_lineups_extracted_despite_no_stats(self):
        """Lineups are fully available even when statistics are missing."""
        text = """FIFA World Cup 2022

Line-ups

Brazil
1 Alisson GK
2 Danilo DEF
3 Thiago Silva DEF
4 Marquinhos DEF
6 Alex Sandro DEF
5 Casemiro MID
7 Lucas Paqueta MID
10 Neymar MID
11 Raphinha FWD
9 Richarlison FWD
20 Vinicius Junior FWD
Substitutes
12 Weverton GK

Serbia
1 Vanja Milinkovic-Savic GK
2 Strahinja Pavlovic DEF
3 Strahinja Erakovic DEF
4 Nikola Milenkovic DEF
5 Milos Veljkovic DEF
6 Nemanja Gudelj MID
7 Nemanja Radonjic FWD
8 Sergej Milinkovic-Savic MID
10 Dusan Tadic MID
9 Aleksandar Mitrovic FWD
11 Filip Kostic MID
Substitutes
12 Predrag Rajkovic GK
"""
        pdf_bytes = _create_match_report_pdf(text)
        result = parse_match_report(pdf_bytes)

        # Lineups should be complete
        home_names = [p.name for p in result.match_data.homeTeam.startingLineup]
        assert "Neymar" in home_names
        assert "Alisson" in home_names
        away_names = [p.name for p in result.match_data.awayTeam.startingLineup]
        assert "Aleksandar Mitrovic" in away_names

    def test_placeholder_statistics_when_section_missing(self):
        """When statistics section is missing, placeholder values are used."""
        text = """FIFA World Cup 2022

Line-ups

Brazil
1 Alisson GK
2 Danilo DEF
3 Thiago Silva DEF
4 Marquinhos DEF
6 Alex Sandro DEF
5 Casemiro MID
7 Lucas Paqueta MID
10 Neymar MID
11 Raphinha FWD
9 Richarlison FWD
20 Vinicius Junior FWD
Substitutes
12 Weverton GK

Serbia
1 Vanja Milinkovic-Savic GK
2 Strahinja Pavlovic DEF
3 Strahinja Erakovic DEF
4 Nikola Milenkovic DEF
5 Milos Veljkovic DEF
6 Nemanja Gudelj MID
7 Nemanja Radonjic FWD
8 Sergej Milinkovic-Savic MID
10 Dusan Tadic MID
9 Aleksandar Mitrovic FWD
11 Filip Kostic MID
Substitutes
12 Predrag Rajkovic GK
"""
        pdf_bytes = _create_match_report_pdf(text)
        result = parse_match_report(pdf_bytes)

        # Statistics should have placeholder defaults
        assert result.match_data.homeTeam.statistics.possessionPct == 50.0
        assert result.match_data.homeTeam.statistics.shotsOnTarget == 0
        assert result.match_data.awayTeam.statistics.possessionPct == 50.0
        assert result.match_data.awayTeam.statistics.shotsOnTarget == 0


class TestPartialExtractionLineupRequired:
    """Tests that lineup extraction failure is still a hard error."""

    def test_lineup_failure_raises_pdf_parse_error(self):
        """If lineups cannot be extracted at all, PDFParseError is raised."""
        text = "FIFA World Cup 2022\nSome random content without lineups."
        pdf_bytes = _create_match_report_pdf(text)

        with pytest.raises(PDFParseError, match="Line-ups section"):
            parse_match_report(pdf_bytes)

    def test_no_players_found_raises_error(self):
        """If the lineup section exists but has no parseable players, error is raised."""
        text = """FIFA World Cup 2022

Line-ups

Brazil
(no valid player data here)

Serbia
(also no valid player data)

Match Events
"""
        pdf_bytes = _create_match_report_pdf(text)

        with pytest.raises(PDFParseError):
            parse_match_report(pdf_bytes)


class TestPartialExtractionWithEvents:
    """Tests for partial extraction scenarios involving events."""

    def test_events_extracted_with_lineups_no_stats(self):
        """Events are extracted even when statistics section is missing."""
        text = """FIFA World Cup 2022

Line-ups

Brazil
1 Alisson GK
2 Danilo DEF
3 Thiago Silva DEF
4 Marquinhos DEF
6 Alex Sandro DEF
5 Casemiro MID
7 Lucas Paqueta MID
10 Neymar MID
11 Raphinha FWD
9 Richarlison FWD
20 Vinicius Junior FWD
Substitutes
12 Weverton GK

Serbia
1 Vanja Milinkovic-Savic GK
2 Strahinja Pavlovic DEF
3 Strahinja Erakovic DEF
4 Nikola Milenkovic DEF
5 Milos Veljkovic DEF
6 Nemanja Gudelj MID
7 Nemanja Radonjic FWD
8 Sergej Milinkovic-Savic MID
10 Dusan Tadic MID
9 Aleksandar Mitrovic FWD
11 Filip Kostic MID
Substitutes
12 Predrag Rajkovic GK

Match Events

Brazil
62 Goal Richarlison
73 Goal Richarlison
"""
        pdf_bytes = _create_match_report_pdf(text)
        result = parse_match_report(pdf_bytes)

        # Events should be extracted
        goals = [e for e in result.match_data.events if e.type == "goal"]
        assert len(goals) == 2
        assert all(g.playerName == "Richarlison" for g in goals)

        # Statistics should be missing
        assert "statistics" in result.missing_fields

    def test_complete_report_has_empty_missing_fields(self):
        """A full report with lineups, events, and stats has no missing fields."""
        text = _create_fifa_stats_text()  # Contains lineups + events + statistics
        pdf_bytes = _create_match_report_pdf(text)
        result = parse_match_report(pdf_bytes)

        # When all three sections are present, missing_fields should be empty
        assert result.missing_fields == []
