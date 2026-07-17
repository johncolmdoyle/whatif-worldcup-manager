"""PDF parser for FIFA World Cup match report PDFs.

Uses pdfplumber to extract structured match data including lineups,
match events, and statistics from official FIFA report layouts.
"""

import io
import re
import uuid
from dataclasses import dataclass, field

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect

from app.models import (
    MatchData,
    MatchEvent,
    MatchStatistics,
    Player,
    PlayerStats,
    Score,
    TeamData,
)


@dataclass
class ParseResult:
    """Result of parsing a FIFA match report PDF.

    Attributes:
        match_data: The extracted MatchData object (may contain placeholder
            values for sections that could not be extracted).
        missing_fields: List of field names that could not be extracted
            from the PDF. Empty if all fields were successfully extracted.
    """

    match_data: MatchData
    missing_fields: list[str] = field(default_factory=list)


class PDFParseError(Exception):
    """Raised when the PDF parser cannot extract required data.

    Attributes:
        missing_fields: List of field names that could not be extracted
            from the PDF document.
    """

    def __init__(self, message: str, missing_fields: list[str] | None = None) -> None:
        self.missing_fields = missing_fields or []
        super().__init__(message)


def _validate_pdf(file_bytes: bytes) -> pdfplumber.PDF:
    """Validate that the PDF file is non-empty, readable, not password-protected,
    and has at least one page.

    Args:
        file_bytes: Raw bytes of the uploaded PDF file.

    Returns:
        An opened pdfplumber.PDF object that has passed all validation checks.

    Raises:
        PDFParseError: If the file is empty, unreadable, password-protected,
            or has no pages.
    """
    # Check 1: File must be greater than 0 bytes
    if not file_bytes or len(file_bytes) == 0:
        raise PDFParseError("PDF file is empty (0 bytes)")

    # Check 2: File must be openable as a valid PDF
    try:
        pdf = pdfplumber.open(io.BytesIO(file_bytes))
    except PDFPasswordIncorrect as e:
        raise PDFParseError("PDF is password-protected") from e
    except Exception as e:
        raise PDFParseError(f"Unable to open PDF: {e}") from e

    # Check 3: PDF must contain at least one page
    if not pdf.pages or len(pdf.pages) == 0:
        pdf.close()
        raise PDFParseError("PDF contains no pages")

    # Check 4: Verify content is accessible (detects encrypted PDFs that open
    # but cannot have their content extracted)
    try:
        pdf.pages[0].extract_text()
    except PDFPasswordIncorrect as e:
        pdf.close()
        raise PDFParseError("PDF is password-protected") from e
    except Exception as e:
        pdf.close()
        raise PDFParseError(f"Unable to read PDF content: {e}") from e

    return pdf


# Position abbreviation mapping for FIFA match reports.
# FIFA reports use various abbreviations; we normalize them to our enum values.
_POSITION_MAP: dict[str, str] = {
    "GK": "GK",
    "G": "GK",
    "GOALKEEPER": "GK",
    "DF": "DEF",
    "DEF": "DEF",
    "D": "DEF",
    "DEFENDER": "DEF",
    "CB": "DEF",
    "LB": "DEF",
    "RB": "DEF",
    "MF": "MID",
    "MID": "MID",
    "M": "MID",
    "MIDFIELDER": "MID",
    "CM": "MID",
    "DM": "MID",
    "AM": "MID",
    "LM": "MID",
    "RM": "MID",
    "FW": "FWD",
    "FWD": "FWD",
    "F": "FWD",
    "FORWARD": "FWD",
    "ST": "FWD",
    "CF": "FWD",
    "LW": "FWD",
    "RW": "FWD",
    "ATT": "FWD",
    "ATTACKER": "FWD",
}


def _normalize_position(raw_position: str) -> str:
    """Normalize a position abbreviation to the canonical enum value.

    Args:
        raw_position: The position string found in the PDF (e.g., "DF", "MF", "FW").

    Returns:
        One of "GK", "DEF", "MID", "FWD".

    Raises:
        PDFParseError: If the position cannot be mapped.
    """
    normalized = raw_position.strip().upper()
    if normalized in _POSITION_MAP:
        return _POSITION_MAP[normalized]
    raise PDFParseError(
        f"Unknown position abbreviation: '{raw_position}'",
        missing_fields=["position"],
    )


def _parse_player_line(line: str) -> Player | None:
    """Attempt to parse a single player entry from a line of text.

    Supports common FIFA report formats:
    - "2 John DOE DEF" (number name position)
    - "2 John DOE (DEF)" (number name position in parens)
    - "[2] John DOE DEF"
    - "2. John DOE - DEF"

    Args:
        line: A single line of text that might contain player data.

    Returns:
        A Player object if the line matches a known player format, else None.
    """
    line = line.strip()
    if not line:
        return None

    # Pattern 1: squad_number name position
    # e.g., "2 John DOE DEF" or "23 Player Name GK"
    pattern1 = re.compile(
        r"^\[?(\d{1,2})\]?[\.\)\-\s]+\s*"  # squad number with optional brackets/separators
        r"(.+?)\s+"  # player name (non-greedy)
        r"[\(\-\s]*([A-Za-z]{1,10})[\)\s]*$"  # position abbreviation
    )

    # Pattern 2: position name squad_number (less common)
    pattern2 = re.compile(
        r"^([A-Z]{1,3})\s+"  # position abbreviation
        r"(\d{1,2})\s+"  # squad number
        r"(.+)$"  # player name
    )

    # Pattern 3: number name (C) position - with captain marker
    pattern3 = re.compile(
        r"^\[?(\d{1,2})\]?[\.\)\-\s]+\s*"  # squad number
        r"(.+?)\s*"  # player name
        r"\([Cc]\)\s*"  # captain marker
        r"[\(\-\s]*([A-Za-z]{1,10})[\)\s]*$"  # position
    )

    for pattern in [pattern3, pattern1]:
        match = pattern.match(line)
        if match:
            squad_num_str = match.group(1)
            name = match.group(2).strip()
            pos_raw = match.group(3).strip()

            squad_num = int(squad_num_str)
            if squad_num < 1 or squad_num > 99:
                continue

            # Clean up name: remove trailing dashes or special chars
            name = re.sub(r"[\-\s]+$", "", name).strip()
            if not name or len(name) > 100:
                continue

            try:
                position = _normalize_position(pos_raw)
            except PDFParseError:
                continue

            return Player(name=name, squadNumber=squad_num, position=position)

    # Try pattern2
    match = pattern2.match(line)
    if match:
        pos_raw = match.group(1).strip()
        squad_num_str = match.group(2)
        name = match.group(3).strip()

        squad_num = int(squad_num_str)
        if squad_num < 1 or squad_num > 99:
            return None

        name = re.sub(r"[\-\s]+$", "", name).strip()
        if not name or len(name) > 100:
            return None

        try:
            position = _normalize_position(pos_raw)
        except PDFParseError:
            return None

        return Player(name=name, squadNumber=squad_num, position=position)

    return None


def _find_lineup_section(full_text: str) -> str | None:
    """Locate the Line-ups section in the extracted PDF text.

    Looks for common section headings used in FIFA match reports:
    - "Line-ups"
    - "Lineups"
    - "LINE-UPS"
    - "Starting Line-ups"

    Args:
        full_text: The complete extracted text from the PDF.

    Returns:
        The text from the lineup section heading to the next major section,
        or None if no lineup section is found.
    """
    # Common patterns for the lineup section heading
    lineup_heading_pattern = re.compile(
        r"(?:^|\n)\s*((?:Starting\s+)?Line[\-\s]?ups?)\s*(?:\n|$)",
        re.IGNORECASE,
    )

    match = lineup_heading_pattern.search(full_text)
    if not match:
        return None

    # Extract text from the lineup heading onward
    start_pos = match.start()
    lineup_text = full_text[start_pos:]

    # Find the end of the lineup section (next major section heading)
    # Common section headings that follow lineups in FIFA reports:
    # "Match Events", "Goals", "Disciplinary", "Statistics", "Officials"
    end_pattern = re.compile(
        r"\n\s*(?:Match\s+Events?|Goals?\s+(?:Scored|&)|Disciplinary|"
        r"Statistics|Officials?|Referee|Match\s+Officials|"
        r"Substitutions?\s+Summary|Additional\s+Time|"
        r"Coaches?|Technical\s+Staff)\s*(?:\n|$)",
        re.IGNORECASE,
    )

    end_match = end_pattern.search(lineup_text)
    if end_match:
        lineup_text = lineup_text[: end_match.start()]

    return lineup_text


def _split_teams_lineup(lineup_text: str) -> tuple[str, str] | None:
    """Split the lineup section text into home team and away team sections.

    FIFA reports typically separate teams with a clear heading or divider.
    The first team listed is the home team, the second is the away team.

    Args:
        lineup_text: The text of the lineup section.

    Returns:
        A tuple of (home_team_text, away_team_text), or None if
        the teams cannot be separated.
    """
    lines = lineup_text.split("\n")

    # Strategy: Find the "Substitutes" headers to delineate sections.
    # Typical structure:
    #   [Team A Name]
    #   [Starting XI players...]
    #   Substitutes
    #   [Substitute players...]
    #   [Team B Name]
    #   [Starting XI players...]
    #   Substitutes
    #   [Substitute players...]

    # Find lines that look like team name headers (not player lines)
    # Team names are typically uppercase or title-case, no numbers at start
    team_header_indices: list[int] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Skip the section heading itself
        if re.match(r"(?:Starting\s+)?Line[\-\s]?ups?", stripped, re.IGNORECASE):
            continue
        # Skip lines that look like player entries (start with a digit)
        if re.match(r"^\[?\d", stripped):
            continue
        # Skip "Substitutes" header
        if re.match(r"^Substitutes?", stripped, re.IGNORECASE):
            continue
        # Skip position abbreviation lines
        if stripped.upper() in _POSITION_MAP:
            continue
        # A team header is typically a short line without numbers
        # that doesn't match player patterns
        if (
            len(stripped) > 2
            and len(stripped) < 50
            and not re.search(r"\d", stripped)
            and not _parse_player_line(stripped)
        ):
            team_header_indices.append(i)

    if len(team_header_indices) >= 2:
        # Split at the second team header
        split_idx = team_header_indices[1]
        home_text = "\n".join(lines[:split_idx])
        away_text = "\n".join(lines[split_idx:])
        return (home_text, away_text)

    # Fallback: try splitting at "Substitutes" markers
    sub_indices = [
        i
        for i, line in enumerate(lines)
        if re.match(r"^\s*Substitutes?\s*$", line, re.IGNORECASE)
    ]

    if len(sub_indices) >= 2:
        # The second "Substitutes" header belongs to the away team
        # Look for a team name header between the two substitute sections
        # The away team section starts a few lines before the second substitutes header
        # where there's a team name
        search_start = sub_indices[0] + 1
        search_end = sub_indices[1]
        for i in range(search_start, search_end):
            stripped = lines[i].strip()
            if (
                stripped
                and not re.match(r"^\[?\d", stripped)
                and len(stripped) > 2
                and len(stripped) < 50
                and not re.search(r"\d", stripped)
                and not _parse_player_line(stripped)
                and not re.match(r"^Substitutes?", stripped, re.IGNORECASE)
            ):
                home_text = "\n".join(lines[:i])
                away_text = "\n".join(lines[i:])
                return (home_text, away_text)

    # Last fallback: split roughly in half based on content
    # Find the midpoint of player entries
    player_lines_indices = [
        i for i, line in enumerate(lines) if _parse_player_line(line.strip())
    ]
    if len(player_lines_indices) >= 2:
        mid_idx = len(player_lines_indices) // 2
        split_line = player_lines_indices[mid_idx]
        # Walk back to find a non-player line for the split
        for i in range(split_line, max(0, split_line - 5), -1):
            if not _parse_player_line(lines[i].strip()):
                home_text = "\n".join(lines[:i])
                away_text = "\n".join(lines[i:])
                return (home_text, away_text)

    return None


def _parse_team_section(
    team_text: str,
) -> tuple[str, list[Player], list[Player]]:
    """Parse a single team's lineup section into team name, starters, and substitutes.

    Args:
        team_text: The text block for one team from the lineup section.

    Returns:
        A tuple of (team_name, starting_xi, substitutes).
    """
    lines = team_text.split("\n")
    team_name = ""
    starting_xi: list[Player] = []
    substitutes: list[Player] = []
    in_substitutes = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Skip the main section heading
        if re.match(r"(?:Starting\s+)?Line[\-\s]?ups?", stripped, re.IGNORECASE):
            continue

        # Check for substitutes header
        if re.match(r"^Substitutes?\s*$", stripped, re.IGNORECASE):
            in_substitutes = True
            continue

        # Try to parse as a player line
        player = _parse_player_line(stripped)
        if player:
            if in_substitutes:
                substitutes.append(player)
            else:
                starting_xi.append(player)
            continue

        # If it's not a player line and we haven't found the team name yet,
        # treat it as the team name
        if (
            not team_name
            and len(stripped) > 1
            and len(stripped) < 50
            and not re.match(r"^\[?\d", stripped)
            and not stripped.upper() in _POSITION_MAP
        ):
            team_name = stripped

    return (team_name, starting_xi, substitutes)


def _extract_lineups_pmsr(
    pdf: pdfplumber.PDF,
) -> tuple[list[Player], list[Player], list[Player], list[Player], str, str] | None:
    """Try to extract lineups from 2026 FIFA PMSR (Post Match Summary Report) format.

    This format has:
    - Page 1: "TeamA N - M TeamB" scoreline
    - Page 2: Side-by-side lineup with "STARTING" and "SUBSTITUTES" headings
    - Each line contains BOTH teams: home on left, away on right
    - Home format: "number position name [noise]"
    - Away format: "[noise] name position number"

    Returns:
        A tuple of (home_xi, home_subs, away_xi, away_subs, home_name, away_name)
        or None if this PDF is not in PMSR format.
    """
    # Check first few pages for PMSR format indicators
    full_text = ""
    for i in range(min(3, len(pdf.pages))):
        page_text = pdf.pages[i].extract_text()
        if page_text:
            full_text += page_text + "\n"

    # Detect PMSR format: look for "STARTING" heading (not "Line-ups")
    if "STARTING" not in full_text:
        return None

    # Extract team names and score from page 1
    score_pattern = re.compile(
        r"^(.+?)\s+(\d+)\s*[-–]\s*(\d+)\s+(.+?)$", re.MULTILINE
    )
    home_name = ""
    away_name = ""

    score_match = score_pattern.search(full_text)
    if score_match:
        home_name = score_match.group(1).strip()
        away_name = score_match.group(4).strip()

    # Find the page with "STARTING" heading for lineup extraction
    lineup_page_text = ""
    for i in range(min(5, len(pdf.pages))):
        page_text = pdf.pages[i].extract_text()
        if page_text and "STARTING" in page_text:
            lineup_page_text = page_text
            break

    if not lineup_page_text:
        return None

    lines = lineup_page_text.split("\n")

    home_xi: list[Player] = []
    home_subs: list[Player] = []
    away_xi: list[Player] = []
    away_subs: list[Player] = []

    in_starting = False
    in_substitutes = False

    # Home player pattern at START of line: "number position name"
    # Handles "9 FWRaul JIMENEZ" (no space) and "1 GK Raul RANGEL"
    # The name must be typical name format: words starting with caps
    # We limit capture by stopping before another "Name POSITION number" pattern
    home_player_pattern = re.compile(
        r"^\s*(\d{1,2})\s+(GK|DF|MF|FW)\s*([A-Za-z][A-Za-z\s\-']+)"
    )

    # Away player pattern at END of line: "name position number"
    # Handles "Ronwen WILLIAMS GK 1" and "Teboho MOKOENA MF 4" and "Sphephelo SITHOLE MF13"
    # Also handles single-word names like "PEDRI MF 26" or "LAPORTE DF 14"
    # Name is one or more words (any casing) before the position abbreviation
    away_player_pattern = re.compile(
        r"(?:^|[\s'])([A-Z][A-Za-z\-']+(?:\s+[A-Za-z][A-Za-z\-']+)*)\s+(GK|DF|MF|FW)\s*(\d{1,2})\s*$"
    )

    for line in lines:
        stripped = line.strip()

        # Detect section transitions
        if re.match(r".*STARTING.*STARTING", stripped):
            in_starting = True
            in_substitutes = False
            continue
        if re.match(r".*SUBSTITUTES?.*SUBSTITUTES?", stripped) or re.match(r"^SUBSTITUTES?", stripped):
            in_substitutes = True
            in_starting = False
            continue

        if not (in_starting or in_substitutes):
            continue

        # Skip noise lines (single chars, numbers only, formation diagrams)
        if len(stripped) <= 2:
            continue
        if re.match(r"^[\d\s\.\-]+$", stripped):
            continue
        if stripped in ("O", "M", "A", "I", "N", "F", "R", "T"):
            continue

        # Try to extract home player (left side of line)
        home_match = home_player_pattern.match(stripped)
        if home_match:
            squad_num = int(home_match.group(1))
            pos_raw = home_match.group(2)
            name_raw = home_match.group(3).strip()
            # Clean name: The raw capture includes everything to the right.
            # The home player name ends before the away player name starts.
            # Away player names are "Firstname LASTNAME" — look for where 
            # a new capitalized firstname begins after an ALL-CAPS word.
            # Strategy: take text up to the first minute marker OR 
            # before a sequence that looks like "AwayFirstname AWAYLASTNAME"
            # which would be: space + Capitalized + space + ALLCAPS
            
            # First, strip trailing minute markers
            name = re.split(r"\s+\d+'", name_raw)[0].strip()
            # Remove trailing single chars (formation noise like F, R, O, T)
            name = re.sub(r"\s+[A-Z]$", "", name).strip()
            # If the name contains what looks like TWO player names (e.g., "Raul RANGEL Ronwen WILLIAMS GK"),
            # detect by finding pattern: ALLCAPS + space + Capitalized (start of away name)
            # Split at the boundary between home lastname and away firstname
            two_names = re.match(
                r"([A-Za-z]+\s+[A-Z][A-Z\-']+)(?:\s+[A-Z][a-z])", name
            )
            if two_names:
                name = two_names.group(1).strip()
            # Also handle noise like "ALVARADO O Ime" → stop at single letter + capitalized word
            name = re.sub(r"\s+[A-Z]\s+[A-Z][a-z].*$", "", name).strip()
            # Remove any remaining position abbreviations that leaked in
            name = re.sub(r"\s+(GK|DF|MF|FW)\s*$", "", name).strip()
            # Remove trailing numbers and special chars
            name = re.sub(r"\s*\d+['']?\s*$", "", name).strip()
            if name and 1 <= squad_num <= 99 and len(name) > 1:
                try:
                    pos = _normalize_position(pos_raw)
                    player = Player(name=name, squadNumber=squad_num, position=pos)
                    if in_starting:
                        home_xi.append(player)
                    else:
                        home_subs.append(player)
                except PDFParseError:
                    pass

        # Try to extract away player (right side of line)
        away_match = away_player_pattern.search(stripped)
        if away_match:
            name_raw = away_match.group(1).strip()
            pos_raw = away_match.group(2)
            squad_num = int(away_match.group(3))
            # Clean name: remove any leading minute markers
            name = re.sub(r"^\d+'?\s*", "", name_raw).strip()
            if name and 1 <= squad_num <= 99 and len(name) > 1:
                try:
                    pos = _normalize_position(pos_raw)
                    player = Player(name=name, squadNumber=squad_num, position=pos)
                    if in_starting:
                        away_xi.append(player)
                    else:
                        away_subs.append(player)
                except PDFParseError:
                    pass

    # Validate we got reasonable results
    if len(home_xi) < 7 or len(away_xi) < 7:
        return None

    if not home_name:
        home_name = "Home Team"
    if not away_name:
        away_name = "Away Team"

    return (home_xi, home_subs, away_xi, away_subs, home_name, away_name)


def _extract_statistics_pmsr(
    pdf: pdfplumber.PDF,
) -> tuple[MatchStatistics, MatchStatistics] | None:
    """Try to extract statistics from 2026 FIFA PMSR format.

    The PMSR format has "Match Summary - Key Statistics" page with format:
    "homeValue  StatName  awayValue" (e.g., "16 (4) Attempts at Goal (On Target) 3 (2)")

    Returns (home_stats, away_stats) or None if not in PMSR format.
    """
    # Find the key statistics page
    stats_text = ""
    for i in range(min(5, len(pdf.pages))):
        page_text = pdf.pages[i].extract_text()
        if page_text and "Key Statistics" in page_text:
            stats_text = page_text
            break

    if not stats_text:
        return None

    home_possession = 50.0
    away_possession = 50.0
    home_shots_on_target = 0
    away_shots_on_target = 0
    home_total_shots = 0
    away_total_shots = 0
    home_passes = 0
    away_passes = 0
    home_fouls = 0
    away_fouls = 0

    lines = stats_text.split("\n")

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()

        # Possession: Look for "Possession" heading and then percentages on next line
        # PMSR format: "Possession" on one line, "Total 57.1% 6.8% 36.1% Total" on next
        if "possession" in lower and "%" not in stripped:
            # This is just the heading; the values are on a subsequent line
            # We'll catch the values when we process the next line with percentages
            continue
        
        # Line with possession percentages: "Total 57.1% 6.8% 36.1% Total"
        if "total" in lower and "%" in stripped and home_possession == 50.0:
            all_pct = re.findall(r"(\d+\.?\d*)%", stripped)
            if len(all_pct) >= 2:
                pcts = [float(p) for p in all_pct if 20 < float(p) < 80]
                if len(pcts) >= 2:
                    home_possession = pcts[0]
                    away_possession = pcts[-1]
                elif len(pcts) == 1:
                    home_possession = pcts[0]
                    away_possession = 100 - pcts[0]

        # Attempts at Goal: "16 (4) Attempts at Goal (On Target) 3 (2)"
        if "attempts at goal" in lower:
            attempts_match = re.match(
                r"\s*(\d+)\s*\((\d+)\)\s*Attempts at Goal\s*\(On Target\)\s*(\d+)\s*\((\d+)\)",
                stripped, re.IGNORECASE
            )
            if attempts_match:
                home_total_shots = int(attempts_match.group(1))
                home_shots_on_target = int(attempts_match.group(2))
                away_total_shots = int(attempts_match.group(3))
                away_shots_on_target = int(attempts_match.group(4))

        # Total Passes: "547 (495) Total Passes (Complete) 351 (290)"
        if "total passes" in lower:
            passes_match = re.match(
                r"\s*(\d+)\s*\(\d+\)\s*Total Passes",
                stripped, re.IGNORECASE
            )
            if passes_match:
                home_passes = int(passes_match.group(1))
            away_passes_match = re.search(
                r"Total Passes\s*\(Complete\)\s*(\d+)",
                stripped, re.IGNORECASE
            )
            if away_passes_match:
                away_passes = int(away_passes_match.group(1))

        # Forced Turnovers (proxy for fouls): "31 Forced Turnovers 32"
        if "forced turnover" in lower:
            ft_match = re.match(
                r"\s*(\d+)\s+Forced Turnovers\s+(\d+)",
                stripped, re.IGNORECASE
            )
            if ft_match:
                home_fouls = int(ft_match.group(1))
                away_fouls = int(ft_match.group(2))

    home_stats = MatchStatistics(
        possessionPct=home_possession,
        shotsOnTarget=home_shots_on_target,
        totalShots=home_total_shots,
        passes=home_passes,
        fouls=home_fouls,
    )
    away_stats = MatchStatistics(
        possessionPct=away_possession,
        shotsOnTarget=away_shots_on_target,
        totalShots=away_total_shots,
        passes=away_passes,
        fouls=away_fouls,
    )

    return (home_stats, away_stats)


def _extract_score_pmsr(pdf: pdfplumber.PDF) -> tuple[int, int]:
    """Extract the match score from a PMSR format PDF (page 1).

    Returns (home_goals, away_goals).
    """
    page1_text = pdf.pages[0].extract_text() or ""
    # Pattern: "Mexico 2 - 0 South Africa"
    score_match = re.search(r"(\d+)\s*[-–]\s*(\d+)", page1_text)
    if score_match:
        return int(score_match.group(1)), int(score_match.group(2))
    return 0, 0


def _extract_player_stats_pmsr(
    pdf: pdfplumber.PDF,
) -> tuple[list[PlayerStats], list[PlayerStats]]:
    """Extract per-player performance statistics from PMSR format.

    Parses "In Possession - Distributions" pages which contain columns:
    # Player | Passes Attempted | Passes Completed | ... | Take Ons | Step Ins | Goals | Attempts at Goal

    Returns (home_player_stats, away_player_stats).
    """
    home_stats: list[PlayerStats] = []
    away_stats: list[PlayerStats] = []

    # Find pages containing "In Possession - Distributions"
    home_page_found = False
    for i in range(len(pdf.pages)):
        page_text = pdf.pages[i].extract_text()
        if not page_text or "In Possession - Distributions" not in page_text:
            continue

        # Determine which team this page is for based on page content
        # The page title includes the team name: "In Possession - Distributions Mexico"
        target_list = away_stats if home_page_found else home_stats
        home_page_found = True

        lines = page_text.split("\n")

        # Parse player stat lines
        for line in lines:
            stripped = line.strip()
            # Match player stat line: number name numbers...
            stat_match = re.match(
                r"^\s*(\d{1,2})\s+([A-Za-z][A-Za-z\s\-']+?)\s+([\d\s%]+)$",
                stripped
            )
            if not stat_match:
                continue

            squad_num = int(stat_match.group(1))
            player_name = stat_match.group(2).strip()
            numbers_str = stat_match.group(3).strip()

            # Extract all numbers from the remaining part (ignore % symbols)
            numbers = [int(n) for n in re.findall(r"\d+", numbers_str.replace("%", " "))]

            if len(numbers) < 10:
                continue

            # Map numbers to stats based on column order:
            # After removing %, numbers become: 33 29 88 1 0 0 13 10 77 0 0 0 0 0
            # Indices:                           0  1  2  3 4 5  6  7  8 9 10 11 12 13
            passes_att = numbers[0] if len(numbers) > 0 else 0
            passes_comp = numbers[1] if len(numbers) > 1 else 0
            crosses_att = numbers[4] if len(numbers) > 4 else 0
            crosses_comp = numbers[5] if len(numbers) > 5 else 0
            lb_att = numbers[6] if len(numbers) > 6 else 0
            lb_comp = numbers[7] if len(numbers) > 7 else 0
            ball_prog = numbers[9] if len(numbers) > 9 else 0
            take_ons = numbers[10] if len(numbers) > 10 else 0
            attempts_at_goal = numbers[12] if len(numbers) > 12 else 0
            goals = numbers[13] if len(numbers) > 13 else 0

            ps = PlayerStats(
                playerName=player_name,
                squadNumber=squad_num,
                passesAttempted=passes_att,
                passesCompleted=passes_comp,
                crossesAttempted=crosses_att,
                crossesCompleted=crosses_comp,
                lineBreaksAttempted=lb_att,
                lineBreaksCompleted=lb_comp,
                ballProgressions=ball_prog,
                takeOns=take_ons,
                goals=goals,
                attemptsAtGoal=attempts_at_goal,
            )
            target_list.append(ps)

    return (home_stats, away_stats)


def _extract_lineups(
    pdf: pdfplumber.PDF,
) -> tuple[list[Player], list[Player], list[Player], list[Player], str, str]:
    """Extract starting lineups and substitutes for both teams from the PDF.

    Tries multiple format parsers:
    1. PMSR (2026 Post Match Summary Report) format
    2. Standard "Line-ups" section format

    Args:
        pdf: An opened pdfplumber.PDF object.

    Returns:
        A tuple of (home_starting_xi, home_substitutes,
                    away_starting_xi, away_substitutes,
                    home_team_name, away_team_name).

    Raises:
        PDFParseError: If the lineup section cannot be found or parsed.
    """
    # Try PMSR format first (2026 FIFA reports)
    pmsr_result = _extract_lineups_pmsr(pdf)
    if pmsr_result is not None:
        return pmsr_result

    # Fall back to standard "Line-ups" format
    # Extract text from all pages
    full_text = ""
    for page in pdf.pages:
        page_text = page.extract_text()
        if page_text:
            full_text += page_text + "\n"

    if not full_text.strip():
        raise PDFParseError(
            "Could not extract any text from PDF",
            missing_fields=["lineups"],
        )

    # Find the lineup section
    lineup_text = _find_lineup_section(full_text)
    if not lineup_text:
        raise PDFParseError(
            "Could not locate Line-ups section in PDF",
            missing_fields=["homeTeam.startingLineup", "awayTeam.startingLineup"],
        )

    # Split into home and away team sections
    team_sections = _split_teams_lineup(lineup_text)
    if not team_sections:
        raise PDFParseError(
            "Could not separate home and away team lineups",
            missing_fields=["homeTeam.startingLineup", "awayTeam.startingLineup"],
        )

    home_text, away_text = team_sections

    # Parse each team's section
    home_name, home_xi, home_subs = _parse_team_section(home_text)
    away_name, away_xi, away_subs = _parse_team_section(away_text)

    # Validate that we got reasonable results
    missing_fields: list[str] = []

    if not home_name:
        home_name = "Home Team"
    if not away_name:
        away_name = "Away Team"

    if len(home_xi) == 0:
        missing_fields.append("homeTeam.startingLineup")
    if len(away_xi) == 0:
        missing_fields.append("awayTeam.startingLineup")

    if missing_fields:
        raise PDFParseError(
            f"Could not extract lineup data: {', '.join(missing_fields)}",
            missing_fields=missing_fields,
        )

    return (home_xi, home_subs, away_xi, away_subs, home_name, away_name)


def _find_events_section(full_text: str) -> str | None:
    """Locate the match events section in the extracted PDF text.

    Looks for common section headings used in FIFA match reports:
    - "Match Events"
    - "Goals & Disciplinary"
    - "Goals Scored"
    - "Events"

    Args:
        full_text: The complete extracted text from the PDF.

    Returns:
        The text of the events section, or None if not found.
    """
    # Common patterns for the events section heading
    events_heading_pattern = re.compile(
        r"(?:^|\n)\s*(Match\s+Events?|Goals?\s+(?:&|and)\s+Disciplinary|"
        r"Goals?\s+Scored|Events)\s*(?:\n|$)",
        re.IGNORECASE,
    )

    match = events_heading_pattern.search(full_text)
    if not match:
        return None

    start_pos = match.end()
    events_text = full_text[start_pos:]

    # Find the end of the events section (next major section heading)
    end_pattern = re.compile(
        r"\n\s*(?:Statistics|Officials?|Referee|Match\s+Officials|"
        r"Coaches?|Technical\s+Staff|Line[\-\s]?ups?|"
        r"Additional\s+Time|Substitutions?\s+Summary)\s*(?:\n|$)",
        re.IGNORECASE,
    )

    end_match = end_pattern.search(events_text)
    if end_match:
        events_text = events_text[: end_match.start()]

    return events_text


def _classify_event_type(event_text: str) -> str | None:
    """Classify an event type from its textual representation.

    Handles common FIFA report notations including Unicode symbols and text labels.

    Args:
        event_text: The event type indicator text (e.g., "Goal", "⚽", "Yellow Card").

    Returns:
        One of "goal", "yellow_card", "red_card", "substitution", or None if unrecognized.
    """
    text_lower = event_text.strip().lower()

    # Goal indicators
    if any(
        indicator in text_lower
        for indicator in ["goal", "⚽", "\u26bd", "scored"]
    ):
        return "goal"

    # Yellow card indicators
    if any(
        indicator in text_lower
        for indicator in [
            "yellow card",
            "yellow",
            "🟡",
            "\U0001f7e1",
            "caution",
            "booking",
            "yc",
        ]
    ):
        return "yellow_card"

    # Red card indicators
    if any(
        indicator in text_lower
        for indicator in [
            "red card",
            "red",
            "🔴",
            "\U0001f534",
            "sent off",
            "sending off",
            "dismissal",
            "rc",
        ]
    ):
        return "red_card"

    # Substitution indicators
    if any(
        indicator in text_lower
        for indicator in [
            "substitution",
            "sub",
            "🔄",
            "\U0001f504",
            "replaced",
            "in/out",
            "↔",
            "↕",
        ]
    ):
        return "substitution"

    return None


def _extract_events(
    pdf: pdfplumber.PDF, home_team_name: str, away_team_name: str
) -> list[MatchEvent]:
    """Extract match events (goals, cards, substitutions) from the PDF.

    Locates the "Match Events" or similar section and parses each event entry
    to identify the event type, minute, player name, team name, and optionally
    a related player name (for substitutions).

    Args:
        pdf: An opened pdfplumber.PDF object.
        home_team_name: Name of the home team (for team assignment).
        away_team_name: Name of the away team (for team assignment).

    Returns:
        A list of MatchEvent objects extracted from the PDF.
        Returns an empty list if no events section is found.
    """
    # Extract text from all pages
    full_text = ""
    for page in pdf.pages:
        page_text = page.extract_text()
        if page_text:
            full_text += page_text + "\n"

    if not full_text.strip():
        return []

    events_text = _find_events_section(full_text)
    if not events_text:
        return []

    events: list[MatchEvent] = []
    current_team = home_team_name  # Default to home team

    # Pattern for event lines: [minute'] [event_type] [player_name] [optional: for/by related_player]
    # Variations:
    #   "23' Goal Richarlison (Brazil)"
    #   "23  ⚽  Richarlison  Brazil"
    #   "62' Substitution: Fred for Paqueta (Brazil)"
    #   "Brazil - 23' Goal - Richarlison"

    # Check for team header lines to track which team events belong to
    team_header_pattern = re.compile(
        r"^\s*(?:(" + re.escape(home_team_name) + r"|" + re.escape(away_team_name) + r"))\s*$",
        re.IGNORECASE,
    )

    # Main event patterns
    # Pattern A: minute' event_type player_name (team)
    pattern_a = re.compile(
        r"(\d{1,3})['\u2019\+]?\s+"  # minute with optional ' or +
        r"(.+?)\s+"  # event type
        r"([A-Z][A-Za-z\s\-']+?)(?:\s*\(([^)]+)\))?\s*$"  # player name with optional (team)
    )

    # Pattern B: minute' event_type player_name for/by related_player (team)
    pattern_b = re.compile(
        r"(\d{1,3})['\u2019\+]?\s+"  # minute
        r"(.+?)\s+"  # event type
        r"([A-Z][A-Za-z\s\-']+?)\s+"  # player name
        r"(?:for|replaced\s+by|in\s+for|on\s+for)\s+"  # substitution connector
        r"([A-Z][A-Za-z\s\-']+?)(?:\s*\(([^)]+)\))?\s*$"  # related player with optional (team)
    )

    # Pattern C: team - minute' event_type - player_name
    pattern_c = re.compile(
        r"([A-Za-z\s]+?)\s*[-–]\s*"  # team name
        r"(\d{1,3})['\u2019\+]?\s*[-–]?\s*"  # minute
        r"(.+?)\s*[-–]\s*"  # event type
        r"([A-Z][A-Za-z\s\-']+?)(?:\s+(?:for|replaced\s+by)\s+"  # player name, optional sub
        r"([A-Z][A-Za-z\s\-']+?))?\s*$"  # related player
    )

    # Pattern D: simple - minute event_type player_name
    # Handles: "23 Goal Richarlison" or "45+2 Yellow Card Casemiro"
    pattern_d = re.compile(
        r"^\s*(\d{1,3})(?:\+\d{1,2})?['\u2019]?\s+"  # minute (with optional stoppage)
        r"(Goal|Yellow\s*Card|Red\s*Card|Substitution|⚽|🟡|🔴|🔄)\s+"  # event type keyword
        r"([A-Z][A-Za-z\s\-']+?)(?:\s+(?:for|replaced\s+by|on\s+for)\s+"  # player name
        r"([A-Z][A-Za-z\s\-']+?))?\s*$",  # optional related player
        re.IGNORECASE,
    )

    lines = events_text.split("\n")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Check for team header
        team_match = team_header_pattern.match(stripped)
        if team_match:
            matched_team = team_match.group(1)
            if matched_team.lower() == home_team_name.lower():
                current_team = home_team_name
            else:
                current_team = away_team_name
            continue

        # Also detect inline team references in the line
        line_team = current_team
        if home_team_name.lower() in stripped.lower():
            line_team = home_team_name
        elif away_team_name.lower() in stripped.lower():
            line_team = away_team_name

        # Try Pattern D first (most structured)
        match = pattern_d.match(stripped)
        if match:
            minute_str = match.group(1)
            event_type_raw = match.group(2)
            player_name = match.group(3).strip()
            related_player = match.group(4)

            minute = int(minute_str)
            if minute < 1 or minute > 120:
                continue

            event_type = _classify_event_type(event_type_raw)
            if not event_type:
                continue

            event = MatchEvent(
                type=event_type,
                minute=minute,
                playerName=player_name,
                teamName=line_team,
                relatedPlayerName=related_player.strip() if related_player else None,
            )
            events.append(event)
            continue

        # Try Pattern B (substitution with related player)
        match = pattern_b.match(stripped)
        if match:
            minute_str = match.group(1)
            event_type_raw = match.group(2)
            player_name = match.group(3).strip()
            related_player = match.group(4).strip()
            team_in_parens = match.group(5)

            minute = int(minute_str)
            if minute < 1 or minute > 120:
                continue

            event_type = _classify_event_type(event_type_raw)
            if not event_type:
                continue

            team = line_team
            if team_in_parens:
                if team_in_parens.strip().lower() == home_team_name.lower():
                    team = home_team_name
                elif team_in_parens.strip().lower() == away_team_name.lower():
                    team = away_team_name

            event = MatchEvent(
                type=event_type,
                minute=minute,
                playerName=player_name,
                teamName=team,
                relatedPlayerName=related_player,
            )
            events.append(event)
            continue

        # Try Pattern C (team prefix)
        match = pattern_c.match(stripped)
        if match:
            team_raw = match.group(1).strip()
            minute_str = match.group(2)
            event_type_raw = match.group(3)
            player_name = match.group(4).strip()
            related_player = match.group(5)

            minute = int(minute_str)
            if minute < 1 or minute > 120:
                continue

            event_type = _classify_event_type(event_type_raw)
            if not event_type:
                continue

            team = line_team
            if team_raw.lower() == home_team_name.lower():
                team = home_team_name
            elif team_raw.lower() == away_team_name.lower():
                team = away_team_name

            event = MatchEvent(
                type=event_type,
                minute=minute,
                playerName=player_name,
                teamName=team,
                relatedPlayerName=related_player.strip() if related_player else None,
            )
            events.append(event)
            continue

        # Try Pattern A (general)
        match = pattern_a.match(stripped)
        if match:
            minute_str = match.group(1)
            event_type_raw = match.group(2)
            player_name = match.group(3).strip()
            team_in_parens = match.group(4)

            minute = int(minute_str)
            if minute < 1 or minute > 120:
                continue

            event_type = _classify_event_type(event_type_raw)
            if not event_type:
                continue

            team = line_team
            if team_in_parens:
                if team_in_parens.strip().lower() == home_team_name.lower():
                    team = home_team_name
                elif team_in_parens.strip().lower() == away_team_name.lower():
                    team = away_team_name

            event = MatchEvent(
                type=event_type,
                minute=minute,
                playerName=player_name,
                teamName=team,
                relatedPlayerName=None,
            )
            events.append(event)
            continue

    return events


def _find_statistics_section(full_text: str) -> str | None:
    """Locate the Statistics section in the extracted PDF text.

    Looks for common section headings used in FIFA match reports:
    - "Statistics"
    - "Match Statistics"
    - "Team Statistics"

    Args:
        full_text: The complete extracted text from the PDF.

    Returns:
        The text of the statistics section, or None if not found.
    """
    # Common patterns for the statistics section heading
    stats_heading_pattern = re.compile(
        r"(?:^|\n)\s*((?:Match\s+|Team\s+)?Statistics)\s*(?:\n|$)",
        re.IGNORECASE,
    )

    match = stats_heading_pattern.search(full_text)
    if not match:
        return None

    start_pos = match.end()
    stats_text = full_text[start_pos:]

    # Find the end of the statistics section (next major section heading)
    end_pattern = re.compile(
        r"\n\s*(?:Officials?|Referee|Match\s+Officials|"
        r"Coaches?|Technical\s+Staff|Line[\-\s]?ups?|"
        r"Match\s+Events?|Additional\s+Time)\s*(?:\n|$)",
        re.IGNORECASE,
    )

    end_match = end_pattern.search(stats_text)
    if end_match:
        stats_text = stats_text[: end_match.start()]

    return stats_text


def _extract_statistics(
    pdf: pdfplumber.PDF,
) -> tuple[MatchStatistics, MatchStatistics]:
    """Extract match statistics for both teams from the PDF.

    Parses the statistics table which typically has format:
    - "HomeValue  StatName  AwayValue" (e.g., "55%  Possession  45%")
    - "StatName: HomeValue - AwayValue"
    - "StatName  HomeValue  AwayValue"

    Args:
        pdf: An opened pdfplumber.PDF object.

    Returns:
        A tuple of (home_stats, away_stats) with extracted MatchStatistics.
        Returns default placeholder values if the statistics section
        cannot be found or parsed.
    """
    default_stats = MatchStatistics(
        possessionPct=50.0,
        shotsOnTarget=0,
        totalShots=0,
        passes=0,
        fouls=0,
    )

    # Extract text from all pages
    full_text = ""
    for page in pdf.pages:
        page_text = page.extract_text()
        if page_text:
            full_text += page_text + "\n"

    if not full_text.strip():
        return (default_stats, default_stats)

    stats_text = _find_statistics_section(full_text)
    if not stats_text:
        return (default_stats, default_stats)

    # Initialize values to extract
    home_possession: float | None = None
    away_possession: float | None = None
    home_shots_on_target: int | None = None
    away_shots_on_target: int | None = None
    home_total_shots: int | None = None
    away_total_shots: int | None = None
    home_passes: int | None = None
    away_passes: int | None = None
    home_fouls: int | None = None
    away_fouls: int | None = None

    lines = stats_text.split("\n")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Pattern A: "HomeValue  StatName  AwayValue"
        # e.g., "55%  Possession  45%" or "5  Shots on Target  3"
        pattern_a = re.compile(
            r"^(\d+)(%?)\s+(.+?)\s+(\d+)(%?)\s*$"
        )

        # Pattern B: "StatName: HomeValue - AwayValue"
        # e.g., "Possession: 55% - 45%" or "Shots on Target: 5 - 3"
        pattern_b = re.compile(
            r"^(.+?):\s*(\d+)(%?)\s*[-–]\s*(\d+)(%?)\s*$"
        )

        # Pattern C: "StatName  HomeValue  AwayValue" (stat name first)
        # e.g., "Possession  55%  45%" or "Total Shots  10  8"
        pattern_c = re.compile(
            r"^([A-Za-z][A-Za-z\s]+?)\s+(\d+)(%?)\s+(\d+)(%?)\s*$"
        )

        stat_name = None
        home_val = None
        away_val = None
        is_percentage = False

        # Try Pattern A first (home_val stat_name away_val)
        match_a = pattern_a.match(stripped)
        if match_a:
            home_val = int(match_a.group(1))
            is_percentage = bool(match_a.group(2)) or bool(match_a.group(5))
            stat_name = match_a.group(3).strip()
            away_val = int(match_a.group(4))
        else:
            # Try Pattern B (stat_name: home_val - away_val)
            match_b = pattern_b.match(stripped)
            if match_b:
                stat_name = match_b.group(1).strip()
                home_val = int(match_b.group(2))
                is_percentage = bool(match_b.group(3)) or bool(match_b.group(5))
                away_val = int(match_b.group(4))
            else:
                # Try Pattern C (stat_name home_val away_val)
                match_c = pattern_c.match(stripped)
                if match_c:
                    stat_name = match_c.group(1).strip()
                    home_val = int(match_c.group(2))
                    is_percentage = bool(match_c.group(3)) or bool(match_c.group(5))
                    away_val = int(match_c.group(4))

        if stat_name is None or home_val is None or away_val is None:
            continue

        # Normalize stat name for matching
        stat_lower = stat_name.lower().strip()

        # Match against known stat names
        if "possession" in stat_lower:
            home_possession = float(home_val)
            away_possession = float(away_val)
        elif "shots on target" in stat_lower or "shot on target" in stat_lower:
            home_shots_on_target = home_val
            away_shots_on_target = away_val
        elif (
            "total shots" in stat_lower
            or stat_lower == "shots"
            or (stat_lower.startswith("shot") and "on target" not in stat_lower and "on-target" not in stat_lower)
        ):
            home_total_shots = home_val
            away_total_shots = away_val
        elif "pass" in stat_lower:
            home_passes = home_val
            away_passes = away_val
        elif "foul" in stat_lower:
            home_fouls = home_val
            away_fouls = away_val

    # Build home statistics with defaults for any missing values
    home_stats = MatchStatistics(
        possessionPct=home_possession if home_possession is not None else 50.0,
        shotsOnTarget=home_shots_on_target if home_shots_on_target is not None else 0,
        totalShots=home_total_shots if home_total_shots is not None else 0,
        passes=home_passes if home_passes is not None else 0,
        fouls=home_fouls if home_fouls is not None else 0,
    )

    away_stats = MatchStatistics(
        possessionPct=away_possession if away_possession is not None else 50.0,
        shotsOnTarget=away_shots_on_target if away_shots_on_target is not None else 0,
        totalShots=away_total_shots if away_total_shots is not None else 0,
        passes=away_passes if away_passes is not None else 0,
        fouls=away_fouls if away_fouls is not None else 0,
    )

    return (home_stats, away_stats)


def parse_match_report(file_bytes: bytes) -> ParseResult:
    """Parse a FIFA World Cup match report PDF and return structured MatchData.

    This function attempts to extract all available data from the PDF. If
    lineup extraction succeeds but events or statistics extraction fails,
    partial data is returned along with a list of missing field names.

    Args:
        file_bytes: Raw bytes of the uploaded PDF file.

    Returns:
        A ParseResult containing the extracted MatchData and a list of
        any field names that could not be extracted. If missing_fields
        is empty, all data was successfully extracted.

    Raises:
        PDFParseError: If the file is empty, unreadable, password-protected,
            has no pages, or lineup extraction fails entirely (lineups are
            required and cannot be partially extracted).
    """
    pdf = _validate_pdf(file_bytes)
    missing_fields: list[str] = []

    try:
        # Task 5.3: Lineup extraction (starting XI + substitutes)
        # Lineups are REQUIRED - failure here is a hard error
        home_xi, home_subs, away_xi, away_subs, home_name, away_name = (
            _extract_lineups(pdf)
        )

        # Detect if this is a PMSR format PDF
        is_pmsr = _extract_lineups_pmsr(pdf) is not None

        # Task 5.4: Events extraction (goals, cards, substitutions)
        # Events are optional - if extraction fails, continue with empty list
        try:
            events = _extract_events(pdf, home_name, away_name)
        except (PDFParseError, Exception):
            events = []
            missing_fields.append("events")

        # Task 5.5: Statistics extraction (possession, shots, passes, fouls)
        # Statistics are optional - if extraction fails, use placeholders
        default_stats = MatchStatistics(
            possessionPct=50.0,
            shotsOnTarget=0,
            totalShots=0,
            passes=0,
            fouls=0,
        )
        try:
            # Try PMSR format first
            pmsr_stats = _extract_statistics_pmsr(pdf) if is_pmsr else None
            if pmsr_stats:
                home_stats, away_stats = pmsr_stats
            else:
                home_stats, away_stats = _extract_statistics(pdf)
        except (PDFParseError, Exception):
            home_stats = default_stats
            away_stats = default_stats
            missing_fields.append("homeTeam.statistics")
            missing_fields.append("awayTeam.statistics")

        # Extract score (PMSR has it on page 1, standard format might not)
        if is_pmsr:
            actual_home_score, actual_away_score = _extract_score_pmsr(pdf)
        else:
            # Try to infer from events (count goals)
            actual_home_score = sum(
                1 for e in events if e.type == "goal" and e.teamName == home_name
            )
            actual_away_score = sum(
                1 for e in events if e.type == "goal" and e.teamName == away_name
            )

        # Extract per-player stats (PMSR only)
        home_player_stats: list[PlayerStats] = []
        away_player_stats: list[PlayerStats] = []
        if is_pmsr:
            try:
                home_player_stats, away_player_stats = _extract_player_stats_pmsr(pdf)
            except Exception:
                pass  # Non-critical — prediction engine works without them

        # Check for statistics that fell back to defaults
        if (
            "homeTeam.statistics" not in missing_fields
            and "awayTeam.statistics" not in missing_fields
        ):
            full_text = ""
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n"

            if not is_pmsr:
                stats_section = _find_statistics_section(full_text)
                if stats_section is None:
                    missing_fields.append("statistics")

        # Pad starting XI to exactly 11 if we got fewer
        home_team = TeamData(
            name=home_name,
            startingLineup=home_xi[:11] if len(home_xi) >= 11 else home_xi,
            substitutes=home_subs,
            statistics=home_stats,
            playerStats=home_player_stats,
        )
        away_team = TeamData(
            name=away_name,
            startingLineup=away_xi[:11] if len(away_xi) >= 11 else away_xi,
            substitutes=away_subs,
            statistics=away_stats,
            playerStats=away_player_stats,
        )

        match_data = MatchData(
            matchId=str(uuid.uuid4()),
            homeTeam=home_team,
            awayTeam=away_team,
            events=events,
            actualScore=Score(home=actual_home_score, away=actual_away_score),
        )

        return ParseResult(match_data=match_data, missing_fields=missing_fields)
    finally:
        pdf.close()
