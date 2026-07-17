"""Property-based tests for the FIFA Match Predictor Prediction Engine using Hypothesis.

Tests the four correctness properties defined in the design document:
- Property 1: Scoreline Consistency (unchanged lineup → goals within ±1 of actual)
- Property 2: Non-Negative Scores (predicted goals always non-negative integers)
- Property 3: Confidence Bounds (confidencePct always in [0, 100])
- Property 4: Factor Count (contributingFactors always 3-5 items)
"""

import uuid
from copy import deepcopy

from hypothesis import given, settings
from hypothesis import strategies as st

from app.models import (
    MatchData,
    MatchEvent,
    MatchStatistics,
    Player,
    Score,
    TeamData,
)
from app.prediction_engine import predict


# ---------------------------------------------------------------------------
# Hypothesis Strategies for generating valid prediction engine inputs
# ---------------------------------------------------------------------------


@st.composite
def valid_match_statistics_strategy(draw):
    """Generate valid MatchStatistics with realistic constraints.

    - possessionPct: 0-100 (float)
    - shotsOnTarget: 0-30 (non-negative int, bounded for realism)
    - totalShots: >= shotsOnTarget (non-negative int)
    - passes: 0-1000 (non-negative int)
    - fouls: 0-50 (non-negative int)
    """
    shots_on_target = draw(st.integers(min_value=0, max_value=30))
    total_shots = draw(st.integers(min_value=shots_on_target, max_value=50))
    return MatchStatistics(
        possessionPct=draw(
            st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)
        ),
        shotsOnTarget=shots_on_target,
        totalShots=total_shots,
        passes=draw(st.integers(min_value=0, max_value=1000)),
        fouls=draw(st.integers(min_value=0, max_value=50)),
    )


@st.composite
def valid_player_strategy(draw, position=None):
    """Generate a valid Player with name, squad number, and position.

    Args:
        position: If provided, forces the player to have this position.
                  Otherwise randomly selects from GK/DEF/MID/FWD.
    """
    name = draw(
        st.text(
            min_size=1,
            max_size=50,
            alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
        )
    )
    squad_number = draw(st.integers(min_value=1, max_value=99))
    if position is None:
        position = draw(st.sampled_from(["GK", "DEF", "MID", "FWD"]))
    return Player(name=name, squadNumber=squad_number, position=position)


@st.composite
def valid_lineup_strategy(draw):
    """Generate a valid starting lineup of exactly 11 players.

    Uses a realistic formation: 1 GK, 4 DEF, 3-5 MID, 1-3 FWD
    ensuring exactly 11 players total.
    """
    # Generate 1 goalkeeper
    gk = draw(valid_player_strategy(position="GK"))

    # Generate 4 defenders
    defenders = [draw(valid_player_strategy(position="DEF")) for _ in range(4)]

    # Randomly choose number of midfielders (3-5) and fill remaining with forwards
    num_midfielders = draw(st.integers(min_value=3, max_value=5))
    num_forwards = 11 - 1 - 4 - num_midfielders  # remaining spots for FWD

    midfielders = [draw(valid_player_strategy(position="MID")) for _ in range(num_midfielders)]
    forwards = [draw(valid_player_strategy(position="FWD")) for _ in range(num_forwards)]

    lineup = [gk] + defenders + midfielders + forwards
    assert len(lineup) == 11
    return lineup


@st.composite
def valid_match_event_strategy(draw, home_team_name, away_team_name, home_lineup, away_lineup):
    """Generate a valid MatchEvent referencing real players from the lineups.

    Args:
        home_team_name: Name of the home team.
        away_team_name: Name of the away team.
        home_lineup: List of home team players.
        away_lineup: List of away team players.
    """
    event_type = draw(st.sampled_from(["goal", "yellow_card", "red_card", "substitution"]))
    minute = draw(st.integers(min_value=1, max_value=120))

    # Pick a team and a player from that team
    is_home = draw(st.booleans())
    team_name = home_team_name if is_home else away_team_name
    lineup = home_lineup if is_home else away_lineup
    player = draw(st.sampled_from(lineup))

    related = None
    if event_type == "substitution":
        # Related player is someone else from the same lineup
        other_players = [p for p in lineup if p.name != player.name]
        if other_players:
            related_player = draw(st.sampled_from(other_players))
            related = related_player.name

    return MatchEvent(
        type=event_type,
        minute=minute,
        playerName=player.name,
        teamName=team_name,
        relatedPlayerName=related,
    )


@st.composite
def valid_match_data_strategy(draw):
    """Generate a complete valid MatchData object suitable for the prediction engine.

    Produces:
    - Two teams with valid 11-player lineups and substitutes
    - Valid match statistics for each team
    - A realistic set of match events referencing actual players
    - An actual score consistent with goals in events (0-10 range)
    """
    # Generate team names
    home_name = draw(
        st.text(
            min_size=1,
            max_size=30,
            alphabet=st.characters(whitelist_categories=("L",)),
        )
    )
    away_name = draw(
        st.text(
            min_size=1,
            max_size=30,
            alphabet=st.characters(whitelist_categories=("L",)),
        ).filter(lambda n: n != home_name)
    )

    # Generate lineups
    home_lineup = draw(valid_lineup_strategy())
    away_lineup = draw(valid_lineup_strategy())

    # Generate substitutes (3-5 per team)
    home_subs = draw(st.lists(valid_player_strategy(), min_size=3, max_size=5))
    away_subs = draw(st.lists(valid_player_strategy(), min_size=3, max_size=5))

    # Generate statistics
    home_stats = draw(valid_match_statistics_strategy())
    away_stats = draw(valid_match_statistics_strategy())

    # Generate actual score
    home_goals = draw(st.integers(min_value=0, max_value=10))
    away_goals = draw(st.integers(min_value=0, max_value=10))

    # Generate events (may include goals matching the score)
    events = draw(
        st.lists(
            valid_match_event_strategy(home_name, away_name, home_lineup, away_lineup),
            min_size=0,
            max_size=15,
        )
    )

    home_team = TeamData(
        name=home_name,
        startingLineup=home_lineup,
        substitutes=home_subs,
        statistics=home_stats,
    )
    away_team = TeamData(
        name=away_name,
        startingLineup=away_lineup,
        substitutes=away_subs,
        statistics=away_stats,
    )

    return MatchData(
        matchId=str(uuid.uuid4()),
        homeTeam=home_team,
        awayTeam=away_team,
        events=events,
        actualScore=Score(home=home_goals, away=away_goals),
    )


@st.composite
def modified_lineup_strategy(draw, original_lineup, substitutes):
    """Generate a modified lineup by randomly swapping 0-11 players from the original.

    For each position in the original lineup, either keep the original player
    or replace them with a randomly generated player (simulating a swap from
    the bench or a custom player entry).

    Args:
        original_lineup: The original 11-player starting lineup.
        substitutes: The team's available substitutes.

    Returns:
        A modified lineup with exactly 11 players.
    """
    # Decide how many players to swap (0-11)
    num_swaps = draw(st.integers(min_value=0, max_value=11))

    if num_swaps == 0:
        return list(original_lineup)

    # Choose which positions to swap
    indices_to_swap = draw(
        st.lists(
            st.integers(min_value=0, max_value=10),
            min_size=num_swaps,
            max_size=num_swaps,
            unique=True,
        )
    )

    modified = list(original_lineup)
    for idx in indices_to_swap:
        # Either use a substitute or generate a fresh player
        if substitutes and draw(st.booleans()):
            replacement = draw(st.sampled_from(substitutes))
        else:
            replacement = draw(valid_player_strategy())
        modified[idx] = replacement

    assert len(modified) == 11
    return modified


# ---------------------------------------------------------------------------
# Property Test Placeholders (implementations in tasks 7.2-7.5)
# ---------------------------------------------------------------------------


@given(match_data=valid_match_data_strategy())
@settings(max_examples=50)
def test_scoreline_consistency_unchanged_lineup(match_data):
    """Property 1: Scoreline Consistency — When original lineup submitted unchanged,
    predicted goals per team are each within ±1 of the actual goals scored.

    This validates that the prediction engine's baseline calibration correctly
    anchors on the actual match result when no changes are made.

    **Validates: Requirements 5.4**
    """
    # Submit the original lineups unchanged
    result = predict(
        match_data,
        list(match_data.homeTeam.startingLineup),
        list(match_data.awayTeam.startingLineup),
    )

    # Predicted goals should be within ±1 of actual
    assert abs(result.predictedScore.home - match_data.actualScore.home) <= 1, (
        f"Home predicted {result.predictedScore.home} vs actual {match_data.actualScore.home}"
    )
    assert abs(result.predictedScore.away - match_data.actualScore.away) <= 1, (
        f"Away predicted {result.predictedScore.away} vs actual {match_data.actualScore.away}"
    )


@given(data=st.data())
@settings(max_examples=50)
def test_non_negative_scores(data):
    """Property 2: Non-Negative Scores — predicted goals are always non-negative
    integers regardless of inputs (any valid match data + any modified lineup).

    This ensures the prediction engine never produces negative scores even under
    extreme lineup changes.

    **Validates: Requirements 5.2**
    """
    match_data = data.draw(valid_match_data_strategy())
    modified_home = data.draw(
        modified_lineup_strategy(
            match_data.homeTeam.startingLineup,
            match_data.homeTeam.substitutes,
        )
    )
    modified_away = data.draw(
        modified_lineup_strategy(
            match_data.awayTeam.startingLineup,
            match_data.awayTeam.substitutes,
        )
    )

    result = predict(match_data, modified_home, modified_away)

    assert isinstance(result.predictedScore.home, int), (
        f"Home score should be int, got {type(result.predictedScore.home)}"
    )
    assert isinstance(result.predictedScore.away, int), (
        f"Away score should be int, got {type(result.predictedScore.away)}"
    )
    assert result.predictedScore.home >= 0, (
        f"Home score should be non-negative, got {result.predictedScore.home}"
    )
    assert result.predictedScore.away >= 0, (
        f"Away score should be non-negative, got {result.predictedScore.away}"
    )


@given(data=st.data())
@settings(max_examples=50)
def test_confidence_bounds(data):
    """Property 3: Confidence Bounds — confidencePct is always in [0, 100]
    regardless of the inputs provided to the prediction engine.

    This ensures the confidence calculation never exceeds its defined bounds
    even when extreme lineup changes are made.

    **Validates: Requirements 5.4, 6.4**
    """
    match_data = data.draw(valid_match_data_strategy())
    modified_home = data.draw(
        modified_lineup_strategy(
            match_data.homeTeam.startingLineup,
            match_data.homeTeam.substitutes,
        )
    )
    modified_away = data.draw(
        modified_lineup_strategy(
            match_data.awayTeam.startingLineup,
            match_data.awayTeam.substitutes,
        )
    )

    result = predict(match_data, modified_home, modified_away)

    assert 0 <= result.confidencePct <= 100, (
        f"Confidence should be in [0, 100], got {result.confidencePct}"
    )


@given(data=st.data())
@settings(max_examples=50)
def test_factor_count(data):
    """Property 4: Factor Count — contributingFactors always contains between
    3 and 5 items, regardless of the inputs.

    This ensures the prediction engine always provides a meaningful set of
    explanatory factors for any prediction.

    **Validates: Requirements 5.3, 6.2**
    """
    match_data = data.draw(valid_match_data_strategy())
    modified_home = data.draw(
        modified_lineup_strategy(
            match_data.homeTeam.startingLineup,
            match_data.homeTeam.substitutes,
        )
    )
    modified_away = data.draw(
        modified_lineup_strategy(
            match_data.awayTeam.startingLineup,
            match_data.awayTeam.substitutes,
        )
    )

    result = predict(match_data, modified_home, modified_away)

    assert 3 <= len(result.contributingFactors) <= 5, (
        f"Contributing factors should be 3-5 items, got {len(result.contributingFactors)}"
    )
