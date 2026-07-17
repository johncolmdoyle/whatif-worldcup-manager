"""Generate a sample FIFA World Cup match report PDF for integration testing.

This script creates a realistic FIFA-style match report PDF that exercises
all paths of the PDF parser: lineup extraction, event extraction, and
statistics extraction.

The generated PDF simulates a 2022 FIFA World Cup Group G match:
    Brazil 2 - 0 Serbia (Lusail Stadium, 24 November 2022)

Run directly to regenerate the fixture:
    python -m tests.fixtures.generate_sample_report
"""

import io
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas


# --- Match Data Constants ---

TOURNAMENT = "FIFA World Cup Qatar 2022"
MATCH_INFO = "Group G - Match 25"
VENUE = "Lusail Stadium, Lusail"
DATE = "24 November 2022"
ATTENDANCE = "88,103"

HOME_TEAM = "Brazil"
AWAY_TEAM = "Serbia"

HOME_STARTING_XI = [
    (1, "Alisson", "GK"),
    (14, "Eder Militao", "DEF"),
    (3, "Thiago Silva", "DEF"),
    (4, "Marquinhos", "DEF"),
    (6, "Alex Sandro", "DEF"),
    (5, "Casemiro", "MID"),
    (7, "Lucas Paqueta", "MID"),
    (10, "Neymar", "MID"),
    (11, "Raphinha", "FWD"),
    (9, "Richarlison", "FWD"),
    (20, "Vinicius Junior", "FWD"),
]

HOME_SUBSTITUTES = [
    (12, "Weverton", "GK"),
    (23, "Ederson", "GK"),
    (2, "Danilo", "DEF"),
    (13, "Dani Alves", "DEF"),
    (15, "Bremer", "DEF"),
    (16, "Alex Telles", "DEF"),
    (8, "Fred", "MID"),
    (17, "Bruno Guimaraes", "MID"),
    (22, "Everton Ribeiro", "MID"),
    (18, "Antony", "FWD"),
    (19, "Rodrygo", "FWD"),
    (21, "Gabriel Jesus", "FWD"),
]

AWAY_STARTING_XI = [
    (1, "Vanja Milinkovic-Savic", "GK"),
    (2, "Strahinja Pavlovic", "DEF"),
    (4, "Nikola Milenkovic", "DEF"),
    (5, "Milos Veljkovic", "DEF"),
    (3, "Strahinja Erakovic", "DEF"),
    (6, "Nemanja Gudelj", "MID"),
    (8, "Sergej Milinkovic-Savic", "MID"),
    (10, "Dusan Tadic", "MID"),
    (11, "Filip Kostic", "MID"),
    (9, "Aleksandar Mitrovic", "FWD"),
    (7, "Nemanja Radonjic", "FWD"),
]

AWAY_SUBSTITUTES = [
    (12, "Predrag Rajkovic", "GK"),
    (23, "Marko Dmitrovic", "GK"),
    (13, "Stefan Mitrovic", "DEF"),
    (15, "Filip Mladenovic", "DEF"),
    (16, "Sasa Lukic", "MID"),
    (17, "Filip Djuricic", "MID"),
    (19, "Lazar Samardzic", "MID"),
    (20, "Marko Grujic", "MID"),
    (21, "Darko Lazovic", "MID"),
    (22, "Ivan Ilic", "MID"),
    (14, "Andrija Zivkovic", "FWD"),
    (18, "Dusan Vlahovic", "FWD"),
]

MATCH_EVENTS = [
    # (minute, event_type_label, player_name, team, related_player)
    (45, "Yellow Card", "Casemiro", "Brazil", None),
    (62, "Goal", "Richarlison", "Brazil", None),
    (69, "Substitution", "Fred", "Brazil", "Lucas Paqueta"),
    (73, "Goal", "Richarlison", "Brazil", None),
    (35, "Yellow Card", "Sergej Milinkovic-Savic", "Serbia", None),
    (77, "Substitution", "Dusan Vlahovic", "Serbia", "Aleksandar Mitrovic"),
    (84, "Yellow Card", "Nikola Milenkovic", "Serbia", None),
    (88, "Red Card", "Strahinja Pavlovic", "Serbia", None),
]

# Statistics: (home_value, stat_name, away_value)
STATISTICS = [
    (59, "Possession", 41),
    (5, "Shots on Target", 3),
    (12, "Total Shots", 8),
    (548, "Passes", 372),
    (11, "Fouls", 14),
]


def generate_sample_match_report_pdf() -> bytes:
    """Generate a sample FIFA World Cup match report PDF.

    Returns:
        bytes: The PDF file content as bytes.
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 2 * cm

    def draw_line(text: str, font: str = "Helvetica", size: int = 10, indent: float = 2 * cm):
        nonlocal y
        if y < 3 * cm:
            c.showPage()
            y = height - 2 * cm
        c.setFont(font, size)
        c.drawString(indent, y, text)
        y -= size + 4

    def draw_blank():
        nonlocal y
        y -= 10

    # --- Header ---
    draw_line(TOURNAMENT, "Helvetica-Bold", 14)
    draw_line(MATCH_INFO, "Helvetica", 11)
    draw_line(f"{VENUE} - {DATE}", "Helvetica", 10)
    draw_line(f"Attendance: {ATTENDANCE}", "Helvetica", 9)
    draw_blank()
    draw_line(f"{HOME_TEAM}  2 - 0  {AWAY_TEAM}", "Helvetica-Bold", 13)
    draw_blank()
    draw_blank()

    # --- Line-ups Section ---
    draw_line("Line-ups", "Helvetica-Bold", 12)
    draw_blank()

    # Home team
    draw_line(HOME_TEAM, "Helvetica-Bold", 11)
    for num, name, pos in HOME_STARTING_XI:
        draw_line(f"{num} {name} {pos}")
    draw_line("Substitutes", "Helvetica-Bold", 10)
    for num, name, pos in HOME_SUBSTITUTES:
        draw_line(f"{num} {name} {pos}")
    draw_blank()

    # Away team
    draw_line(AWAY_TEAM, "Helvetica-Bold", 11)
    for num, name, pos in AWAY_STARTING_XI:
        draw_line(f"{num} {name} {pos}")
    draw_line("Substitutes", "Helvetica-Bold", 10)
    for num, name, pos in AWAY_SUBSTITUTES:
        draw_line(f"{num} {name} {pos}")
    draw_blank()
    draw_blank()

    # --- Match Events Section ---
    draw_line("Match Events", "Helvetica-Bold", 12)
    draw_blank()

    # Group events by team for the FIFA report layout
    current_team = None
    for minute, event_type, player, team, related in MATCH_EVENTS:
        if team != current_team:
            draw_line(team, "Helvetica-Bold", 10)
            current_team = team
        if related:
            draw_line(f"{minute} {event_type} {player} for {related}")
        else:
            draw_line(f"{minute} {event_type} {player}")
    draw_blank()
    draw_blank()

    # --- Statistics Section ---
    draw_line("Statistics", "Helvetica-Bold", 12)
    draw_blank()

    for home_val, stat_name, away_val in STATISTICS:
        # FIFA format: HomeValue%  StatName  AwayValue%
        if stat_name == "Possession":
            draw_line(f"{home_val}% {stat_name} {away_val}%")
        else:
            draw_line(f"{home_val} {stat_name} {away_val}")

    c.save()
    return buffer.getvalue()


def write_fixture():
    """Write the sample match report PDF to the fixtures directory."""
    fixture_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(fixture_dir, "sample_match_report.pdf")
    pdf_bytes = generate_sample_match_report_pdf()
    with open(output_path, "wb") as f:
        f.write(pdf_bytes)
    print(f"Generated fixture PDF: {output_path} ({len(pdf_bytes)} bytes)")
    return output_path


if __name__ == "__main__":
    write_fixture()
