"""Unit tests for the Prediction Engine."""

import uuid

import pytest

from app.models import (
    MatchData,
    MatchEvent,
    MatchStatistics,
    Player,
    Score,
    TeamData,
)
from app.prediction_engine import (
    _compute_baseline_xg,
    _compute_confidence,
    _compute_contributing_factors,
    _compute_labeled_deltas,
    _compute_lineup_deltas,
    _count_positions,
    predict,
)


# --- Helpers ---


def _make_statistics(
    possession: float = 55.0,
    shots_on_target: int = 5,
    total_shots: int = 12,
) -> MatchStatistics:
    return MatchStatistics(
        possessionPct=possession,
        shotsOnTarget=shots_on_target,
        totalShots=total_shots,
        passes=400,
        fouls=10,
    )


def _make_players(count: int, prefix: str = "Player") -> list[Player]:
    positions = ["GK"] + ["DEF"] * 4 + ["MID"] * 3 + ["FWD"] * 3
    return [
        Player(name=f"{prefix} {i+1}", squadNumber=i + 1, position=positions[i % len(positions)])
        for i in range(count)
    ]


def _make_match_data(
    home_score: int = 2,
    away_score: int = 1,
    home_shots_on_target: int = 5,
    away_shots_on_target: int = 5,
    home_total_shots: int = 12,
    away_total_shots: int = 12,
) -> MatchData:
    home_stats = _make_statistics(
        shots_on_target=home_shots_on_target,
        total_shots=home_total_shots,
    )
    away_stats = _make_statistics(
        shots_on_target=away_shots_on_target,
        total_shots=away_total_shots,
    )
    home_team = TeamData(
        name="Argentina",
        startingLineup=_make_players(11, "Home"),
        substitutes=_make_players(5, "HomeSub"),
        statistics=home_stats,
    )
    away_team = TeamData(
        name="France",
        startingLineup=_make_players(11, "Away"),
        substitutes=_make_players(3, "AwaySub"),
        statistics=away_stats,
    )
    return MatchData(
        matchId=str(uuid.uuid4()),
        homeTeam=home_team,
        awayTeam=away_team,
        events=[
            MatchEvent(type="goal", minute=23, playerName="Home 1", teamName="Argentina"),
        ],
        actualScore=Score(home=home_score, away=away_score),
    )


# --- Tests ---


class TestPredictFunctionSignature:
    """Verify the predict function accepts correct inputs and returns PredictedOutcome."""

    def test_returns_predicted_outcome_with_unchanged_lineups(self):
        """predict returns a valid PredictedOutcome when lineups are unchanged."""
        match_data = _make_match_data()
        home_lineup = match_data.homeTeam.startingLineup
        away_lineup = match_data.awayTeam.startingLineup

        result = predict(match_data, home_lineup, away_lineup)

        assert result.predictedScore.home == match_data.actualScore.home
        assert result.predictedScore.away == match_data.actualScore.away
        assert result.confidencePct == 100.0
        assert len(result.contributingFactors) >= 3
        assert len(result.contributingFactors) <= 5
        assert result.modifiedHomeLineup == home_lineup
        assert result.modifiedAwayLineup == away_lineup

    def test_confidence_decreases_with_lineup_changes(self):
        """Confidence should be less than 100% when players are changed."""
        match_data = _make_match_data()
        home_lineup = list(match_data.homeTeam.startingLineup)
        away_lineup = match_data.awayTeam.startingLineup

        # Swap one home player
        home_lineup[0] = Player(name="New Player", squadNumber=99, position="GK")

        result = predict(match_data, home_lineup, away_lineup)

        assert result.confidencePct < 100.0

    def test_unchanged_lineups_give_actual_score(self):
        """When lineups are unchanged, predicted score equals actual score."""
        match_data = _make_match_data()

        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )

        assert result.predictedScore.home == 2
        assert result.predictedScore.away == 1


class TestPredictInputValidation:
    """Verify input validation raises ValueError for invalid lineups."""

    def test_home_lineup_too_few_players_raises(self):
        """ValueError raised when home lineup has fewer than 11 players."""
        match_data = _make_match_data()
        home_lineup = _make_players(10, "Home")
        away_lineup = match_data.awayTeam.startingLineup

        with pytest.raises(ValueError, match="Home lineup must have exactly 11 players"):
            predict(match_data, home_lineup, away_lineup)

    def test_home_lineup_too_many_players_raises(self):
        """ValueError raised when home lineup has more than 11 players."""
        match_data = _make_match_data()
        home_lineup = _make_players(12, "Home")
        away_lineup = match_data.awayTeam.startingLineup

        with pytest.raises(ValueError, match="Home lineup must have exactly 11 players"):
            predict(match_data, home_lineup, away_lineup)

    def test_away_lineup_too_few_players_raises(self):
        """ValueError raised when away lineup has fewer than 11 players."""
        match_data = _make_match_data()
        home_lineup = match_data.homeTeam.startingLineup
        away_lineup = _make_players(9, "Away")

        with pytest.raises(ValueError, match="Away lineup must have exactly 11 players"):
            predict(match_data, home_lineup, away_lineup)

    def test_away_lineup_too_many_players_raises(self):
        """ValueError raised when away lineup has more than 11 players."""
        match_data = _make_match_data()
        home_lineup = match_data.homeTeam.startingLineup
        away_lineup = _make_players(13, "Away")

        with pytest.raises(ValueError, match="Away lineup must have exactly 11 players"):
            predict(match_data, home_lineup, away_lineup)

    def test_empty_home_lineup_raises(self):
        """ValueError raised for empty home lineup."""
        match_data = _make_match_data()

        with pytest.raises(ValueError, match="Home lineup must have exactly 11 players"):
            predict(match_data, [], match_data.awayTeam.startingLineup)

    def test_empty_away_lineup_raises(self):
        """ValueError raised for empty away lineup."""
        match_data = _make_match_data()

        with pytest.raises(ValueError, match="Away lineup must have exactly 11 players"):
            predict(match_data, match_data.homeTeam.startingLineup, [])


class TestPredictContributingFactors:
    """Verify contributing factors meet model constraints."""

    def test_factors_have_valid_directions(self):
        """All contributing factors have 'positive' or 'negative' direction."""
        match_data = _make_match_data()

        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )

        for factor in result.contributingFactors:
            assert factor.direction in ("positive", "negative")

    def test_factors_magnitude_in_range(self):
        """All contributing factors have magnitudePct between 1 and 100."""
        match_data = _make_match_data()

        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )

        for factor in result.contributingFactors:
            assert 1 <= factor.magnitudePct <= 100

    def test_factors_have_non_empty_attributes(self):
        """All contributing factors have a non-empty attribute string."""
        match_data = _make_match_data()

        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )

        for factor in result.contributingFactors:
            assert len(factor.attribute) > 0


class TestComputeBaselineXG:
    """Verify the baseline xG computation and calibration."""

    def test_baseline_xg_equals_actual_score_standard_case(self):
        """Baseline xG equals the actual goals when shotsOnTarget > 0."""
        match_data = _make_match_data(home_score=3, away_score=1,
                                      home_shots_on_target=8, away_shots_on_target=4)
        home_xg, away_xg = _compute_baseline_xg(match_data)

        assert home_xg == 3.0
        assert away_xg == 1.0

    def test_baseline_xg_equals_actual_score_zero_zero(self):
        """Baseline xG is 0 for a 0-0 draw."""
        match_data = _make_match_data(home_score=0, away_score=0,
                                      home_shots_on_target=3, away_shots_on_target=5)
        home_xg, away_xg = _compute_baseline_xg(match_data)

        assert home_xg == 0.0
        assert away_xg == 0.0

    def test_baseline_xg_with_zero_shots_on_target_and_zero_goals(self):
        """When shotsOnTarget is 0 and goals are 0, xG is 0."""
        match_data = _make_match_data(home_score=0, away_score=0,
                                      home_shots_on_target=0, away_shots_on_target=0,
                                      home_total_shots=5, away_total_shots=3)
        home_xg, away_xg = _compute_baseline_xg(match_data)

        assert home_xg == 0.0
        assert away_xg == 0.0

    def test_baseline_xg_with_zero_shots_on_target_but_goals(self):
        """When shotsOnTarget is 0 but goals > 0 (e.g. own goals), xG equals actual goals."""
        match_data = _make_match_data(home_score=1, away_score=0,
                                      home_shots_on_target=0, away_shots_on_target=0,
                                      home_total_shots=3, away_total_shots=2)
        home_xg, away_xg = _compute_baseline_xg(match_data)

        assert home_xg == 1.0
        assert away_xg == 0.0

    def test_baseline_xg_high_scoring_match(self):
        """Baseline xG handles high-scoring matches correctly."""
        match_data = _make_match_data(home_score=5, away_score=4,
                                      home_shots_on_target=10, away_shots_on_target=8)
        home_xg, away_xg = _compute_baseline_xg(match_data)

        assert home_xg == 5.0
        assert away_xg == 4.0

    def test_shot_conversion_factor_calibration(self):
        """The shotConversionFactor correctly calibrates xG to actual goals.

        shotConversionFactor = actualGoals / shotsOnTarget
        xG = shotsOnTarget * shotConversionFactor = actualGoals
        """
        match_data = _make_match_data(home_score=2, away_score=3,
                                      home_shots_on_target=6, away_shots_on_target=9)
        home_xg, away_xg = _compute_baseline_xg(match_data)

        # Verify: factor = 2/6 = 0.333..., xG = 6 * 0.333... = 2.0
        assert home_xg == 2.0
        # Verify: factor = 3/9 = 0.333..., xG = 9 * 0.333... = 3.0
        assert away_xg == 3.0

    def test_predict_unchanged_lineups_match_actual_score_various(self):
        """The key invariant: unchanged lineup produces predicted == actual for various scores."""
        for home_score, away_score in [(0, 0), (1, 0), (0, 3), (2, 2), (4, 1), (7, 0)]:
            match_data = _make_match_data(
                home_score=home_score,
                away_score=away_score,
                home_shots_on_target=max(1, home_score * 2),
                away_shots_on_target=max(1, away_score * 2),
                home_total_shots=max(5, home_score * 4),
                away_total_shots=max(5, away_score * 4),
            )
            result = predict(
                match_data,
                match_data.homeTeam.startingLineup,
                match_data.awayTeam.startingLineup,
            )
            assert result.predictedScore.home == home_score, (
                f"Expected home={home_score}, got {result.predictedScore.home}"
            )
            assert result.predictedScore.away == away_score, (
                f"Expected away={away_score}, got {result.predictedScore.away}"
            )


# --- Lineup Delta Tests ---


def _make_match_data_with_events(
    home_score: int = 2,
    away_score: int = 1,
    events: list[MatchEvent] | None = None,
    home_substitutes: list[Player] | None = None,
    away_substitutes: list[Player] | None = None,
) -> MatchData:
    """Create a MatchData with configurable events and substitutes."""
    home_stats = _make_statistics(shots_on_target=5, total_shots=12)
    away_stats = _make_statistics(shots_on_target=5, total_shots=12)

    home_subs = home_substitutes if home_substitutes is not None else _make_players(5, "HomeSub")
    away_subs = away_substitutes if away_substitutes is not None else _make_players(3, "AwaySub")

    home_team = TeamData(
        name="Argentina",
        startingLineup=_make_players(11, "Home"),
        substitutes=home_subs,
        statistics=home_stats,
    )
    away_team = TeamData(
        name="France",
        startingLineup=_make_players(11, "Away"),
        substitutes=away_subs,
        statistics=away_stats,
    )
    return MatchData(
        matchId=str(uuid.uuid4()),
        homeTeam=home_team,
        awayTeam=away_team,
        events=events or [],
        actualScore=Score(home=home_score, away=away_score),
    )


class TestCountPositions:
    """Tests for the _count_positions helper."""

    def test_standard_lineup(self):
        """A standard 4-3-3 lineup is counted correctly."""
        lineup = _make_players(11, "Test")
        counts = _count_positions(lineup)
        # _make_players generates: GK, DEF, DEF, DEF, DEF, MID, MID, MID, FWD, FWD, FWD
        assert counts["GK"] == 1
        assert counts["DEF"] == 4
        assert counts["MID"] == 3
        assert counts["FWD"] == 3

    def test_all_same_position(self):
        """A lineup of all midfielders is counted correctly."""
        lineup = [
            Player(name=f"P{i}", squadNumber=i + 1, position="MID")
            for i in range(11)
        ]
        counts = _count_positions(lineup)
        assert counts["MID"] == 11
        assert counts["GK"] == 0
        assert counts["DEF"] == 0
        assert counts["FWD"] == 0


class TestComputeLineupDeltas:
    """Tests for the _compute_lineup_deltas function."""

    def test_no_changes_returns_one(self):
        """When lineups are identical, deltas should be [1.0]."""
        match_data = _make_match_data_with_events()
        original = match_data.homeTeam.startingLineup
        modified = list(original)  # same lineup

        deltas = _compute_lineup_deltas(
            match_data, original, modified, "Argentina"
        )

        assert deltas == [1.0]

    def test_positional_coverage_fewer_midfielders(self):
        """Removing a MID and adding a DEF should produce a possession penalty."""
        match_data = _make_match_data_with_events()
        original = match_data.homeTeam.startingLineup
        # Original lineup: GK, DEF, DEF, DEF, DEF, MID, MID, MID, FWD, FWD, FWD
        # Replace one MID (index 5) with a DEF
        modified = list(original)
        modified[5] = Player(name="New Defender", squadNumber=50, position="DEF")

        deltas = _compute_lineup_deltas(
            match_data, original, modified, "Argentina"
        )

        # Should contain 0.95 (one fewer MID)
        assert any(abs(d - 0.95) < 1e-9 for d in deltas)

    def test_positional_coverage_fewer_forwards(self):
        """Removing a FWD and adding a DEF should produce an attack penalty."""
        match_data = _make_match_data_with_events()
        original = match_data.homeTeam.startingLineup
        # Replace one FWD (index 8) with a DEF
        modified = list(original)
        modified[8] = Player(name="New Defender", squadNumber=50, position="DEF")

        deltas = _compute_lineup_deltas(
            match_data, original, modified, "Argentina"
        )

        # Should contain 0.90 (one fewer FWD)
        assert any(abs(d - 0.90) < 1e-9 for d in deltas)

    def test_positional_coverage_extra_forward(self):
        """Adding an extra FWD (replacing a MID) should produce an attack bonus."""
        match_data = _make_match_data_with_events()
        original = match_data.homeTeam.startingLineup
        # Replace one MID (index 5) with a FWD
        modified = list(original)
        modified[5] = Player(name="New Forward", squadNumber=50, position="FWD")

        deltas = _compute_lineup_deltas(
            match_data, original, modified, "Argentina"
        )

        # Should contain 1.05 (one extra FWD) and NOT a FWD penalty
        assert any(abs(d - 1.05) < 1e-9 for d in deltas)
        assert all(d >= 0.90 + 1e-9 or abs(d - 1.05) < 1e-9 or abs(d - 0.95) < 1e-9 for d in deltas)

    def test_goal_scorer_removal_penalty(self):
        """Removing a player who scored a goal applies 0.85 penalty."""
        events = [
            MatchEvent(type="goal", minute=23, playerName="Home 1", teamName="Argentina"),
        ]
        match_data = _make_match_data_with_events(events=events)
        original = match_data.homeTeam.startingLineup
        # Remove "Home 1" (index 0, GK) and replace with custom player of same position
        modified = list(original)
        modified[0] = Player(name="New GK", squadNumber=50, position="GK")

        deltas = _compute_lineup_deltas(
            match_data, original, modified, "Argentina"
        )

        # Should contain 0.85 (one goal by removed player)
        assert any(abs(d - 0.85) < 1e-9 for d in deltas)

    def test_goal_scorer_removal_multiple_goals(self):
        """Removing a player who scored 2 goals applies 0.85^2 penalty."""
        events = [
            MatchEvent(type="goal", minute=23, playerName="Home 1", teamName="Argentina"),
            MatchEvent(type="goal", minute=45, playerName="Home 1", teamName="Argentina"),
        ]
        match_data = _make_match_data_with_events(events=events)
        original = match_data.homeTeam.startingLineup
        modified = list(original)
        modified[0] = Player(name="New GK", squadNumber=50, position="GK")

        deltas = _compute_lineup_deltas(
            match_data, original, modified, "Argentina"
        )

        expected_penalty = 0.85 ** 2  # ~0.7225
        assert any(abs(d - expected_penalty) < 1e-9 for d in deltas)

    def test_substitute_contribution_bonus(self):
        """Adding a known substitute who has events gives 1.03 bonus."""
        # Create a substitute player who has events in the match
        sub_player = Player(name="HomeSub 1", squadNumber=12, position="MID")
        home_subs = [sub_player] + _make_players(4, "HomeSub2")
        events = [
            MatchEvent(type="goal", minute=70, playerName="HomeSub 1", teamName="Argentina"),
        ]
        match_data = _make_match_data_with_events(
            events=events, home_substitutes=home_subs
        )
        original = match_data.homeTeam.startingLineup
        # Replace a MID with the substitute who scored
        modified = list(original)
        modified[5] = Player(name="HomeSub 1", squadNumber=12, position="MID")

        deltas = _compute_lineup_deltas(
            match_data, original, modified, "Argentina"
        )

        # Should contain 1.03 (substitute contribution)
        assert any(abs(d - 1.03) < 1e-9 for d in deltas)

    def test_substitute_without_events_no_bonus(self):
        """Adding a known substitute who has no events gives no bonus."""
        sub_player = Player(name="HomeSub 1", squadNumber=12, position="MID")
        home_subs = [sub_player] + _make_players(4, "HomeSub2")
        # No events for HomeSub 1
        match_data = _make_match_data_with_events(
            events=[], home_substitutes=home_subs
        )
        original = match_data.homeTeam.startingLineup
        modified = list(original)
        modified[5] = Player(name="HomeSub 1", squadNumber=12, position="MID")

        deltas = _compute_lineup_deltas(
            match_data, original, modified, "Argentina"
        )

        # No 1.03 bonus should be present. Same position swap → [1.0]
        assert all(abs(d - 1.03) > 1e-9 for d in deltas)

    def test_custom_player_not_in_subs_no_bonus(self):
        """Adding a custom player (not in substitutes) doesn't get substitute bonus."""
        events = [
            MatchEvent(type="goal", minute=70, playerName="Custom Player", teamName="Argentina"),
        ]
        match_data = _make_match_data_with_events(events=events)
        original = match_data.homeTeam.startingLineup
        modified = list(original)
        modified[5] = Player(name="Custom Player", squadNumber=50, position="MID")

        deltas = _compute_lineup_deltas(
            match_data, original, modified, "Argentina"
        )

        # No 1.03 bonus; custom player is not in the substitutes list
        assert all(abs(d - 1.03) > 1e-9 for d in deltas)

    def test_away_team_deltas(self):
        """Deltas are correctly computed for the away team."""
        events = [
            MatchEvent(type="goal", minute=30, playerName="Away 9", teamName="France"),
        ]
        match_data = _make_match_data_with_events(events=events)
        original = match_data.awayTeam.startingLineup
        # Remove "Away 9" (index 8, FWD) who scored a goal
        modified = list(original)
        modified[8] = Player(name="New Forward", squadNumber=50, position="FWD")

        deltas = _compute_lineup_deltas(
            match_data, original, modified, "France"
        )

        # Should contain 0.85 penalty for removing goal scorer
        assert any(abs(d - 0.85) < 1e-9 for d in deltas)

    def test_predict_computes_and_applies_deltas(self):
        """predict() applies lineup deltas to baseline xG via Phase 3."""
        match_data = _make_match_data_with_events(home_score=2, away_score=1)

        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )

        # Unchanged lineup: deltas are [1.0], product is 1.0, so predicted == actual
        assert result.predictedScore.home == 2
        assert result.predictedScore.away == 1



# --- Phase 3: Score Simulation Tests ---


class TestPhase3ScoreSimulation:
    """Tests for Phase 3: applying deltas to baseline xG."""

    def test_deltas_applied_modifies_predicted_score(self):
        """Removing a goal scorer changes the predicted score via delta application."""
        events = [
            MatchEvent(type="goal", minute=23, playerName="Home 1", teamName="Argentina"),
            MatchEvent(type="goal", minute=55, playerName="Home 1", teamName="Argentina"),
        ]
        match_data = _make_match_data_with_events(home_score=2, away_score=0, events=events)
        original = match_data.homeTeam.startingLineup

        # Remove goal scorer "Home 1" (scored 2 goals → penalty 0.85^2 = 0.7225)
        modified_home = list(original)
        modified_home[0] = Player(name="New GK", squadNumber=50, position="GK")

        result = predict(
            match_data,
            modified_home,
            match_data.awayTeam.startingLineup,
        )

        # baseline home xG = 2.0, adjusted = 2.0 * 0.7225 = 1.445 → round = 1
        assert result.predictedScore.home == 1
        # Away unchanged: predicted stays 0
        assert result.predictedScore.away == 0

    def test_unchanged_lineup_still_produces_actual_score(self):
        """Phase 3 invariant: unchanged lineup → deltas are [1.0] → predicted == actual."""
        for home_score, away_score in [(0, 0), (1, 0), (0, 3), (2, 2), (4, 1)]:
            match_data = _make_match_data_with_events(
                home_score=home_score,
                away_score=away_score,
                events=[],
            )
            result = predict(
                match_data,
                match_data.homeTeam.startingLineup,
                match_data.awayTeam.startingLineup,
            )
            assert result.predictedScore.home == home_score
            assert result.predictedScore.away == away_score

    def test_predicted_goals_never_negative_extreme_deltas(self):
        """Predicted goals are non-negative even with extreme penalties.

        Scenario: Remove a player who scored many goals on a 1-goal team.
        Delta = 0.85^5 ≈ 0.444, adjustedXG = 1 * 0.444 = 0.444, round = 0 (not negative).
        """
        events = [
            MatchEvent(type="goal", minute=i * 10, playerName="Home 1", teamName="Argentina")
            for i in range(1, 6)  # 5 goals by one player
        ]
        match_data = _make_match_data_with_events(home_score=1, away_score=0, events=events)
        original = match_data.homeTeam.startingLineup

        modified_home = list(original)
        modified_home[0] = Player(name="New GK", squadNumber=50, position="GK")

        result = predict(
            match_data,
            modified_home,
            match_data.awayTeam.startingLineup,
        )

        # Predicted goals must always be >= 0
        assert result.predictedScore.home >= 0
        assert result.predictedScore.away >= 0
        assert isinstance(result.predictedScore.home, int)
        assert isinstance(result.predictedScore.away, int)

    def test_predicted_goals_are_integers(self):
        """Predicted goals are always integers (not floats)."""
        events = [
            MatchEvent(type="goal", minute=30, playerName="Home 9", teamName="Argentina"),
        ]
        match_data = _make_match_data_with_events(home_score=3, away_score=2, events=events)
        original = match_data.homeTeam.startingLineup

        # Remove FWD who scored (index 8 = FWD in _make_players)
        modified_home = list(original)
        modified_home[8] = Player(name="New FWD", squadNumber=50, position="FWD")

        result = predict(
            match_data,
            modified_home,
            match_data.awayTeam.startingLineup,
        )

        assert isinstance(result.predictedScore.home, int)
        assert isinstance(result.predictedScore.away, int)

    def test_multiple_deltas_compound(self):
        """Multiple delta factors are multiplied together (product applied)."""
        # Remove a MID who scored a goal: positional penalty (no MID change since replacing
        # with MID is same) + goal penalty. Instead, remove a FWD goal scorer and replace with DEF.
        # This gives: attack penalty (0.90) AND goal scorer penalty (0.85)
        events = [
            MatchEvent(type="goal", minute=30, playerName="Home 9", teamName="Argentina"),
        ]
        match_data = _make_match_data_with_events(home_score=4, away_score=0, events=events)
        original = match_data.homeTeam.startingLineup

        # Remove FWD "Home 9" (index 8) who scored, replace with DEF
        modified_home = list(original)
        modified_home[8] = Player(name="New Defender", squadNumber=50, position="DEF")

        result = predict(
            match_data,
            modified_home,
            match_data.awayTeam.startingLineup,
        )

        # baseline = 4.0
        # deltas: 0.90 (fewer FWD) * 0.85 (goal scorer removal) = 0.765
        # adjusted = 4.0 * 0.765 = 3.06 → round = 3
        assert result.predictedScore.home == 3

    def test_zero_baseline_xg_stays_zero_regardless_of_deltas(self):
        """When baseline xG is 0, any delta product still gives 0."""
        match_data = _make_match_data_with_events(home_score=0, away_score=0, events=[])
        original = match_data.homeTeam.startingLineup

        # Make a lineup change to produce non-trivial deltas
        modified_home = list(original)
        modified_home[8] = Player(name="New Defender", squadNumber=50, position="DEF")

        result = predict(
            match_data,
            modified_home,
            match_data.awayTeam.startingLineup,
        )

        # 0 * anything = 0, rounded = 0
        assert result.predictedScore.home == 0
        assert result.predictedScore.away == 0


# --- Confidence Score Calculation Tests ---


class TestComputeConfidence:
    """Tests for the _compute_confidence function (Task 6.5)."""

    def test_unchanged_lineup_returns_100(self):
        """When no changes are made, confidence is 100.0."""
        confidence = _compute_confidence([1.0], [1.0], 0)
        assert confidence == 100.0

    def test_single_delta_deviation_reduces_confidence(self):
        """A single delta deviation from 1.0 reduces confidence."""
        # One delta of 0.85 → abs(0.85 - 1.0) = 0.15, penalty = 0.15 * 100 = 15
        confidence = _compute_confidence([0.85], [1.0], 1)
        assert confidence == 85.0

    def test_multiple_deltas_accumulate(self):
        """Multiple delta deviations accumulate to reduce confidence further."""
        # Two deltas: 0.90 and 0.85
        # abs(0.90 - 1.0) + abs(0.85 - 1.0) = 0.10 + 0.15 = 0.25
        # confidence = 100 - 0.25 * 100 = 75.0
        confidence = _compute_confidence([0.90, 0.85], [1.0], 2)
        assert confidence == 75.0

    def test_bonus_deltas_also_reduce_confidence(self):
        """Deltas above 1.0 (bonuses) also reduce confidence (more uncertainty)."""
        # Delta of 1.05 → abs(1.05 - 1.0) = 0.05, penalty = 0.05 * 100 = 5
        confidence = _compute_confidence([1.05], [1.0], 1)
        assert confidence == 95.0

    def test_clamped_to_zero_floor(self):
        """Confidence never goes below 0, even with extreme deltas."""
        # Many large deviations that would push confidence negative
        extreme_deltas = [0.5, 0.5, 0.5]  # 3 * abs(0.5 - 1.0) = 1.5, penalty = 150
        confidence = _compute_confidence(extreme_deltas, extreme_deltas, 6)
        assert confidence == 0.0

    def test_clamped_to_100_ceiling(self):
        """Confidence never goes above 100, even with all-1.0 deltas."""
        confidence = _compute_confidence([1.0, 1.0, 1.0], [1.0, 1.0], 0)
        assert confidence == 100.0

    def test_fallback_with_no_delta_deviation_but_changes(self):
        """When deltas are all 1.0 but changes exist, uses fallback penalty."""
        # Same-position swaps produce deltas of [1.0] but total_changes > 0
        confidence = _compute_confidence([1.0], [1.0], 2)
        # Fallback: 100 - 2 * 10 = 80.0
        assert confidence == 80.0

    def test_fallback_with_max_changes(self):
        """With 11 changes per team (22 total) and no delta deviation, clamps to 0."""
        # 22 changes * 10 penalty = 220, clamped to 0
        confidence = _compute_confidence([1.0], [1.0], 22)
        assert confidence == 0.0

    def test_both_teams_deltas_combined(self):
        """Deltas from both home and away teams are combined."""
        # Home: 0.90 → deviation 0.10
        # Away: 0.85 → deviation 0.15
        # Total deviation = 0.25, penalty = 25
        confidence = _compute_confidence([0.90], [0.85], 2)
        assert confidence == 75.0

    def test_with_22_changes_extreme_deltas(self):
        """Even with 11 changes per team (22 total), confidence stays >= 0."""
        # Simulate 11 home + 11 away changes with large penalties
        home_deltas = [0.85] * 11  # 11 * 0.15 = 1.65
        away_deltas = [0.85] * 11  # 11 * 0.15 = 1.65
        # Total deviation = 3.3, penalty = 330, clamped to 0
        confidence = _compute_confidence(home_deltas, away_deltas, 22)
        assert confidence == 0.0

    def test_confidence_always_float(self):
        """Confidence is always a float value."""
        confidence = _compute_confidence([1.0], [1.0], 0)
        assert isinstance(confidence, float)

    def test_moderate_changes_produce_intermediate_confidence(self):
        """A moderate number of changes produces a value between 0 and 100."""
        # 3 changes: deltas of 0.95, 0.90, 0.85
        # Deviations: 0.05 + 0.10 + 0.15 = 0.30
        # Confidence: 100 - 30 = 70
        confidence = _compute_confidence([0.95, 0.90], [0.85], 3)
        assert confidence == 70.0
        assert 0.0 <= confidence <= 100.0


class TestConfidenceIntegration:
    """Integration tests: confidence via predict() function."""

    def test_predict_unchanged_lineup_confidence_100(self):
        """Unchanged lineups produce confidence of exactly 100."""
        match_data = _make_match_data()
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )
        assert result.confidencePct == 100.0

    def test_predict_one_change_confidence_less_than_100(self):
        """A single player swap produces confidence < 100."""
        match_data = _make_match_data()
        home_lineup = list(match_data.homeTeam.startingLineup)
        home_lineup[0] = Player(name="New GK", squadNumber=99, position="GK")

        result = predict(match_data, home_lineup, match_data.awayTeam.startingLineup)
        assert result.confidencePct < 100.0
        assert result.confidencePct >= 0.0

    def test_predict_many_changes_confidence_still_valid(self):
        """Many player swaps still produce confidence in [0, 100]."""
        match_data = _make_match_data()
        # Replace all 11 home players
        home_lineup = [
            Player(name=f"New Player {i}", squadNumber=i + 50, position="MID")
            for i in range(11)
        ]
        # Replace all 11 away players
        away_lineup = [
            Player(name=f"New Away {i}", squadNumber=i + 60, position="DEF")
            for i in range(11)
        ]

        result = predict(match_data, home_lineup, away_lineup)
        assert 0.0 <= result.confidencePct <= 100.0

    def test_predict_more_changes_lower_confidence(self):
        """More changes result in lower (or equal) confidence."""
        match_data = _make_match_data()

        # One change
        home_lineup_1 = list(match_data.homeTeam.startingLineup)
        home_lineup_1[0] = Player(name="New GK", squadNumber=99, position="GK")
        result_1 = predict(match_data, home_lineup_1, match_data.awayTeam.startingLineup)

        # Two changes
        home_lineup_2 = list(match_data.homeTeam.startingLineup)
        home_lineup_2[0] = Player(name="New GK", squadNumber=99, position="GK")
        home_lineup_2[1] = Player(name="New DEF", squadNumber=98, position="DEF")
        result_2 = predict(match_data, home_lineup_2, match_data.awayTeam.startingLineup)

        assert result_2.confidencePct <= result_1.confidencePct


# --- Contributing Factors Tests ---


class TestComputeLabeledDeltas:
    """Tests for _compute_labeled_deltas which provides factor labels."""

    def test_no_changes_returns_empty(self):
        """When lineups are identical, no labeled deltas are returned."""
        match_data = _make_match_data_with_events()
        original = match_data.homeTeam.startingLineup

        result = _compute_labeled_deltas(match_data, original, list(original), "Argentina")
        assert result == []

    def test_fewer_midfielders_labeled(self):
        """Reducing midfielders produces a 'midfield coverage reduced' label."""
        match_data = _make_match_data_with_events()
        original = match_data.homeTeam.startingLineup
        modified = list(original)
        modified[5] = Player(name="New Defender", squadNumber=50, position="DEF")

        result = _compute_labeled_deltas(match_data, original, modified, "Argentina")
        labels = [label for label, _ in result]
        assert "midfield coverage reduced" in labels

    def test_fewer_forwards_labeled(self):
        """Reducing forwards produces an 'attacking strength reduced' label."""
        match_data = _make_match_data_with_events()
        original = match_data.homeTeam.startingLineup
        modified = list(original)
        modified[8] = Player(name="New Defender", squadNumber=50, position="DEF")

        result = _compute_labeled_deltas(match_data, original, modified, "Argentina")
        labels = [label for label, _ in result]
        assert "attacking strength reduced" in labels

    def test_extra_forward_labeled(self):
        """Adding an extra forward produces an 'attacking strength increased' label."""
        match_data = _make_match_data_with_events()
        original = match_data.homeTeam.startingLineup
        modified = list(original)
        modified[5] = Player(name="New Forward", squadNumber=50, position="FWD")

        result = _compute_labeled_deltas(match_data, original, modified, "Argentina")
        labels = [label for label, _ in result]
        assert "attacking strength increased" in labels

    def test_goal_scorer_removal_labeled(self):
        """Removing a goal scorer produces a 'key goal-scorer removed' label."""
        events = [
            MatchEvent(type="goal", minute=23, playerName="Home 1", teamName="Argentina"),
        ]
        match_data = _make_match_data_with_events(events=events)
        original = match_data.homeTeam.startingLineup
        modified = list(original)
        modified[0] = Player(name="New GK", squadNumber=50, position="GK")

        result = _compute_labeled_deltas(match_data, original, modified, "Argentina")
        labels = [label for label, _ in result]
        assert "key goal-scorer removed" in labels

    def test_substitute_contribution_labeled(self):
        """Adding a proven substitute produces a 'proven substitute introduced' label."""
        sub_player = Player(name="HomeSub 1", squadNumber=12, position="MID")
        home_subs = [sub_player] + _make_players(4, "HomeSub2")
        events = [
            MatchEvent(type="goal", minute=70, playerName="HomeSub 1", teamName="Argentina"),
        ]
        match_data = _make_match_data_with_events(events=events, home_substitutes=home_subs)
        original = match_data.homeTeam.startingLineup
        modified = list(original)
        modified[5] = Player(name="HomeSub 1", squadNumber=12, position="MID")

        result = _compute_labeled_deltas(match_data, original, modified, "Argentina")
        labels = [label for label, _ in result]
        assert "proven substitute introduced" in labels


class TestComputeContributingFactors:
    """Tests for the _compute_contributing_factors function."""

    def test_unchanged_lineup_returns_3_filler_factors(self):
        """Unchanged lineups produce exactly 3 statistics-based filler factors."""
        match_data = _make_match_data()
        factors = _compute_contributing_factors(
            match_data,
            [1.0], [1.0],
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
            0,
        )
        assert len(factors) == 3
        attrs = {f.attribute for f in factors}
        assert "possession advantage" in attrs
        assert "shot accuracy" in attrs
        assert "defensive solidity" in attrs

    def test_returns_between_3_and_5_factors(self):
        """Result always contains between 3 and 5 factors regardless of scenario."""
        match_data = _make_match_data()
        # No changes scenario
        factors = _compute_contributing_factors(
            match_data, [1.0], [1.0],
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
            0,
        )
        assert 3 <= len(factors) <= 5

    def test_real_deltas_surface_as_factors(self):
        """When lineup changes produce real deltas, they appear as factors."""
        events = [
            MatchEvent(type="goal", minute=23, playerName="Home 1", teamName="Argentina"),
        ]
        match_data = _make_match_data_with_events(events=events)
        original = match_data.homeTeam.startingLineup
        # Remove goal scorer and replace with DEF (causing positional + goal scorer deltas)
        modified_home = list(original)
        modified_home[0] = Player(name="New GK", squadNumber=50, position="GK")

        factors = _compute_contributing_factors(
            match_data,
            [0.85], [1.0],
            modified_home,
            match_data.awayTeam.startingLineup,
            1,
        )

        assert 3 <= len(factors) <= 5
        attrs = {f.attribute for f in factors}
        assert "key goal-scorer removed" in attrs

    def test_factors_sorted_by_magnitude_descending(self):
        """Factors are sorted with highest magnitude first."""
        events = [
            MatchEvent(type="goal", minute=23, playerName="Home 1", teamName="Argentina"),
            MatchEvent(type="goal", minute=45, playerName="Home 1", teamName="Argentina"),
        ]
        match_data = _make_match_data_with_events(events=events)
        original = match_data.homeTeam.startingLineup
        # Remove goal scorer (2 goals) and change position (FWD→DEF swap)
        modified_home = list(original)
        modified_home[0] = Player(name="New GK", squadNumber=50, position="GK")
        modified_home[8] = Player(name="New Defender", squadNumber=51, position="DEF")

        factors = _compute_contributing_factors(
            match_data,
            [0.85**2, 0.90], [1.0],
            modified_home,
            match_data.awayTeam.startingLineup,
            2,
        )

        # First factor should have highest magnitude
        magnitudes = [f.magnitudePct for f in factors]
        # The real factors (from labeled deltas) should be at the front
        # Goal scorer removal: abs(0.7225 - 1.0) = 0.2775 → 28%
        # Attack penalty: abs(0.90 - 1.0) = 0.10 → 10%
        assert magnitudes[0] >= magnitudes[1]

    def test_caps_at_5_factors_maximum(self):
        """Never returns more than 5 factors, even with many deltas."""
        # Create a scenario with many different events generating lots of deltas
        events = [
            MatchEvent(type="goal", minute=10, playerName="Home 1", teamName="Argentina"),
            MatchEvent(type="goal", minute=20, playerName="Home 2", teamName="Argentina"),
            MatchEvent(type="goal", minute=30, playerName="Home 3", teamName="Argentina"),
            MatchEvent(type="goal", minute=40, playerName="Away 1", teamName="France"),
            MatchEvent(type="goal", minute=50, playerName="Away 2", teamName="France"),
            MatchEvent(type="goal", minute=60, playerName="Away 3", teamName="France"),
        ]
        match_data = _make_match_data_with_events(home_score=3, away_score=3, events=events)
        original_home = match_data.homeTeam.startingLineup
        original_away = match_data.awayTeam.startingLineup

        # Remove multiple goal scorers from both teams + positional changes
        modified_home = list(original_home)
        modified_home[0] = Player(name="NewH1", squadNumber=50, position="DEF")
        modified_home[1] = Player(name="NewH2", squadNumber=51, position="DEF")
        modified_home[2] = Player(name="NewH3", squadNumber=52, position="FWD")

        modified_away = list(original_away)
        modified_away[0] = Player(name="NewA1", squadNumber=60, position="DEF")
        modified_away[1] = Player(name="NewA2", squadNumber=61, position="DEF")
        modified_away[2] = Player(name="NewA3", squadNumber=62, position="FWD")

        factors = _compute_contributing_factors(
            match_data,
            [0.85, 0.85, 0.85, 0.95], [0.85, 0.85, 0.85, 0.95],
            modified_home,
            modified_away,
            6,
        )

        assert len(factors) <= 5

    def test_magnitude_pct_always_clamped_1_to_100(self):
        """All factors have magnitudePct clamped between 1 and 100."""
        match_data = _make_match_data()
        # Test with unchanged lineups (fillers)
        factors = _compute_contributing_factors(
            match_data, [1.0], [1.0],
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
            0,
        )
        for factor in factors:
            assert 1 <= factor.magnitudePct <= 100

    def test_direction_is_positive_or_negative(self):
        """All factors have direction set to 'positive' or 'negative'."""
        events = [
            MatchEvent(type="goal", minute=23, playerName="Home 1", teamName="Argentina"),
        ]
        match_data = _make_match_data_with_events(events=events)
        original = match_data.homeTeam.startingLineup
        modified_home = list(original)
        modified_home[0] = Player(name="New GK", squadNumber=50, position="GK")

        factors = _compute_contributing_factors(
            match_data,
            [0.85], [1.0],
            modified_home,
            match_data.awayTeam.startingLineup,
            1,
        )
        for factor in factors:
            assert factor.direction in ("positive", "negative")

    def test_negative_delta_produces_negative_direction(self):
        """Deltas below 1.0 produce factors with 'negative' direction."""
        events = [
            MatchEvent(type="goal", minute=23, playerName="Home 1", teamName="Argentina"),
        ]
        match_data = _make_match_data_with_events(events=events)
        original = match_data.homeTeam.startingLineup
        modified_home = list(original)
        modified_home[0] = Player(name="New GK", squadNumber=50, position="GK")

        factors = _compute_contributing_factors(
            match_data,
            [0.85], [1.0],
            modified_home,
            match_data.awayTeam.startingLineup,
            1,
        )
        # The goal-scorer removal factor should be negative
        goal_scorer_factor = next(
            f for f in factors if f.attribute == "key goal-scorer removed"
        )
        assert goal_scorer_factor.direction == "negative"

    def test_positive_delta_produces_positive_direction(self):
        """Deltas above 1.0 produce factors with 'positive' direction."""
        sub_player = Player(name="HomeSub 1", squadNumber=12, position="FWD")
        home_subs = [sub_player] + _make_players(4, "HomeSub2")
        events = [
            MatchEvent(type="goal", minute=70, playerName="HomeSub 1", teamName="Argentina"),
        ]
        match_data = _make_match_data_with_events(events=events, home_substitutes=home_subs)
        original = match_data.homeTeam.startingLineup
        # Replace a FWD with the proven substitute FWD (same position, no positional delta)
        modified_home = list(original)
        modified_home[8] = Player(name="HomeSub 1", squadNumber=12, position="FWD")

        factors = _compute_contributing_factors(
            match_data,
            [1.03], [1.0],
            modified_home,
            match_data.awayTeam.startingLineup,
            1,
        )
        sub_factor = next(
            f for f in factors if f.attribute == "proven substitute introduced"
        )
        assert sub_factor.direction == "positive"

    def test_pads_with_fillers_when_fewer_than_3_real_factors(self):
        """When only 1 real delta exists, pads to 3 with filler factors."""
        events = [
            MatchEvent(type="goal", minute=23, playerName="Home 1", teamName="Argentina"),
        ]
        match_data = _make_match_data_with_events(events=events)
        original = match_data.homeTeam.startingLineup
        # Only one delta (goal scorer removal, same position)
        modified_home = list(original)
        modified_home[0] = Player(name="New GK", squadNumber=50, position="GK")

        factors = _compute_contributing_factors(
            match_data,
            [0.85], [1.0],
            modified_home,
            match_data.awayTeam.startingLineup,
            1,
        )
        assert len(factors) >= 3
        attrs = {f.attribute for f in factors}
        # Should have the real factor plus fillers
        assert "key goal-scorer removed" in attrs

    def test_integration_with_predict_returns_valid_factors(self):
        """predict() uses _compute_contributing_factors and returns valid output."""
        events = [
            MatchEvent(type="goal", minute=23, playerName="Home 1", teamName="Argentina"),
        ]
        match_data = _make_match_data_with_events(home_score=2, away_score=1, events=events)
        modified_home = list(match_data.homeTeam.startingLineup)
        modified_home[0] = Player(name="New GK", squadNumber=50, position="GK")
        modified_home[8] = Player(name="New Defender", squadNumber=51, position="DEF")

        result = predict(match_data, modified_home, match_data.awayTeam.startingLineup)

        assert 3 <= len(result.contributingFactors) <= 5
        for factor in result.contributingFactors:
            assert factor.direction in ("positive", "negative")
            assert 1 <= factor.magnitudePct <= 100
            assert len(factor.attribute) > 0


# --- Task 6.7: Unchanged Lineup Produces Matching Result ---


def _determine_result(home_goals: int, away_goals: int) -> str:
    """Determine win/draw/loss result from a scoreline."""
    if home_goals > away_goals:
        return "home_win"
    elif home_goals < away_goals:
        return "away_win"
    else:
        return "draw"


class TestUnchangedLineupMatchesActualResult:
    """Task 6.7: Verify that unchanged lineups produce predictions matching the actual result.

    Validates Requirement 5.4: When the original Starting_Lineup is submitted without
    modification, the Prediction_Engine SHALL produce a Predicted_Outcome where:
    - The win/draw/loss result matches the actual match result
    - The predicted goals per team are each within ±1 of the actual goals scored
    - A confidence score expressed as a percentage between 0% and 100%

    Note: Due to the baseline xG calibration (xG = actual goals when unchanged),
    the prediction actually produces an EXACT match which is stricter than ±1.
    """

    # --- Win/Draw/Loss Determination ---

    def test_home_win_result_preserved(self):
        """Unchanged lineup with home win produces predicted home win."""
        match_data = _make_match_data(home_score=2, away_score=1)
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )
        assert _determine_result(result.predictedScore.home, result.predictedScore.away) == "home_win"

    def test_away_win_result_preserved(self):
        """Unchanged lineup with away win produces predicted away win."""
        match_data = _make_match_data(home_score=0, away_score=2)
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )
        assert _determine_result(result.predictedScore.home, result.predictedScore.away) == "away_win"

    def test_draw_result_preserved(self):
        """Unchanged lineup with draw produces predicted draw."""
        match_data = _make_match_data(home_score=1, away_score=1)
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )
        assert _determine_result(result.predictedScore.home, result.predictedScore.away) == "draw"

    def test_nil_nil_draw_preserved(self):
        """Unchanged lineup with 0-0 draw produces predicted 0-0 draw."""
        match_data = _make_match_data(home_score=0, away_score=0)
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )
        assert result.predictedScore.home == 0
        assert result.predictedScore.away == 0
        assert _determine_result(result.predictedScore.home, result.predictedScore.away) == "draw"

    def test_high_scoring_home_win_preserved(self):
        """Unchanged lineup with 5-1 home win produces matching result."""
        match_data = _make_match_data(
            home_score=5, away_score=1,
            home_shots_on_target=10, away_shots_on_target=3,
            home_total_shots=20, away_total_shots=8,
        )
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )
        assert _determine_result(result.predictedScore.home, result.predictedScore.away) == "home_win"
        assert result.predictedScore.home == 5
        assert result.predictedScore.away == 1

    def test_high_scoring_draw_preserved(self):
        """Unchanged lineup with 3-3 draw produces matching result."""
        match_data = _make_match_data(
            home_score=3, away_score=3,
            home_shots_on_target=8, away_shots_on_target=8,
            home_total_shots=15, away_total_shots=15,
        )
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )
        assert result.predictedScore.home == 3
        assert result.predictedScore.away == 3
        assert _determine_result(result.predictedScore.home, result.predictedScore.away) == "draw"

    def test_shutout_away_win_preserved(self):
        """Unchanged lineup with 0-2 away win produces matching result."""
        match_data = _make_match_data(
            home_score=0, away_score=2,
            home_shots_on_target=2, away_shots_on_target=6,
            home_total_shots=8, away_total_shots=14,
        )
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )
        assert result.predictedScore.home == 0
        assert result.predictedScore.away == 2
        assert _determine_result(result.predictedScore.home, result.predictedScore.away) == "away_win"

    def test_extreme_scoreline_7_0_preserved(self):
        """Unchanged lineup with 7-0 produces exact match."""
        match_data = _make_match_data(
            home_score=7, away_score=0,
            home_shots_on_target=14, away_shots_on_target=1,
            home_total_shots=25, away_total_shots=5,
        )
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )
        assert result.predictedScore.home == 7
        assert result.predictedScore.away == 0

    # --- Goals Within ±1 (Exact Match Due to Calibration) ---

    @pytest.mark.parametrize(
        "home_score,away_score",
        [
            (0, 0),
            (1, 0),
            (0, 1),
            (0, 2),
            (2, 0),
            (1, 1),
            (2, 1),
            (1, 2),
            (2, 2),
            (3, 0),
            (0, 3),
            (3, 1),
            (3, 3),
            (4, 1),
            (5, 1),
            (5, 2),
            (7, 0),
            (4, 4),
        ],
    )
    def test_goals_within_plus_minus_1_of_actual(self, home_score, away_score):
        """Predicted goals per team are within ±1 of actual (Requirement 5.4).

        Due to the calibration approach, they should actually be exact.
        """
        match_data = _make_match_data(
            home_score=home_score,
            away_score=away_score,
            home_shots_on_target=max(1, home_score * 2),
            away_shots_on_target=max(1, away_score * 2),
            home_total_shots=max(5, home_score * 4),
            away_total_shots=max(5, away_score * 4),
        )
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )

        # Requirement: within ±1
        assert abs(result.predictedScore.home - home_score) <= 1, (
            f"Home: predicted {result.predictedScore.home} vs actual {home_score}, "
            f"difference {abs(result.predictedScore.home - home_score)} > 1"
        )
        assert abs(result.predictedScore.away - away_score) <= 1, (
            f"Away: predicted {result.predictedScore.away} vs actual {away_score}, "
            f"difference {abs(result.predictedScore.away - away_score)} > 1"
        )

        # Stricter invariant: exact match due to calibration
        assert result.predictedScore.home == home_score
        assert result.predictedScore.away == away_score

    @pytest.mark.parametrize(
        "home_score,away_score",
        [
            (0, 0),
            (1, 0),
            (0, 1),
            (2, 2),
            (3, 1),
            (5, 1),
            (7, 0),
        ],
    )
    def test_win_draw_loss_matches_actual_parametrized(self, home_score, away_score):
        """Win/draw/loss determination matches the actual result for various scorelines."""
        match_data = _make_match_data(
            home_score=home_score,
            away_score=away_score,
            home_shots_on_target=max(1, home_score * 2),
            away_shots_on_target=max(1, away_score * 2),
            home_total_shots=max(5, home_score * 4),
            away_total_shots=max(5, away_score * 4),
        )
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )

        actual_result = _determine_result(home_score, away_score)
        predicted_result = _determine_result(
            result.predictedScore.home, result.predictedScore.away
        )
        assert predicted_result == actual_result, (
            f"Score {home_score}-{away_score}: expected {actual_result}, "
            f"got {predicted_result} (predicted {result.predictedScore.home}-{result.predictedScore.away})"
        )

    # --- Confidence Score ---

    def test_confidence_is_100_for_unchanged_lineup(self):
        """Unchanged lineup produces confidence of exactly 100%."""
        match_data = _make_match_data(home_score=2, away_score=1)
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )
        assert result.confidencePct == 100.0

    @pytest.mark.parametrize(
        "home_score,away_score",
        [(0, 0), (1, 0), (3, 3), (5, 1), (7, 0)],
    )
    def test_confidence_100_for_various_unchanged_scorelines(self, home_score, away_score):
        """Confidence is 100% for unchanged lineups regardless of scoreline."""
        match_data = _make_match_data(
            home_score=home_score,
            away_score=away_score,
            home_shots_on_target=max(1, home_score * 2),
            away_shots_on_target=max(1, away_score * 2),
            home_total_shots=max(5, home_score * 4),
            away_total_shots=max(5, away_score * 4),
        )
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )
        assert result.confidencePct == 100.0

    def test_confidence_between_0_and_100(self):
        """Confidence is always between 0% and 100% (inclusive) for unchanged lineup."""
        match_data = _make_match_data(home_score=4, away_score=2)
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )
        assert 0.0 <= result.confidencePct <= 100.0

    # --- Contributing Factors for Unchanged Lineups ---

    def test_unchanged_lineup_produces_filler_factors(self):
        """Unchanged lineup produces statistics-based filler factors (no labeled deltas)."""
        match_data = _make_match_data(home_score=2, away_score=1)
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )

        # Should have exactly 3 filler factors
        assert len(result.contributingFactors) == 3
        attrs = {f.attribute for f in result.contributingFactors}
        assert "possession advantage" in attrs
        assert "shot accuracy" in attrs
        assert "defensive solidity" in attrs

    def test_unchanged_lineup_filler_factors_all_positive(self):
        """Filler factors for unchanged lineups are all positive direction."""
        match_data = _make_match_data(home_score=1, away_score=0)
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )

        for factor in result.contributingFactors:
            assert factor.direction == "positive"

    def test_unchanged_lineup_filler_factors_valid_magnitude(self):
        """Filler factors have magnitudePct in [1, 100]."""
        match_data = _make_match_data(home_score=3, away_score=2)
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )

        for factor in result.contributingFactors:
            assert 1.0 <= factor.magnitudePct <= 100.0

    # --- Edge Cases ---

    def test_zero_shots_on_target_with_goals(self):
        """When shotsOnTarget=0 but goals > 0 (own goals), still matches actual."""
        match_data = _make_match_data(
            home_score=1, away_score=0,
            home_shots_on_target=0, away_shots_on_target=0,
            home_total_shots=3, away_total_shots=2,
        )
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )
        assert result.predictedScore.home == 1
        assert result.predictedScore.away == 0
        assert result.confidencePct == 100.0

    def test_zero_shots_on_target_zero_goals(self):
        """When shotsOnTarget=0 and goals=0, predicted is 0-0."""
        match_data = _make_match_data(
            home_score=0, away_score=0,
            home_shots_on_target=0, away_shots_on_target=0,
            home_total_shots=5, away_total_shots=3,
        )
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )
        assert result.predictedScore.home == 0
        assert result.predictedScore.away == 0
        assert result.confidencePct == 100.0

    def test_one_sided_zero_shots_mixed(self):
        """One team has 0 shotsOnTarget with a goal, the other has normal stats."""
        match_data = _make_match_data(
            home_score=1, away_score=3,
            home_shots_on_target=0, away_shots_on_target=6,
            home_total_shots=2, away_total_shots=12,
        )
        result = predict(
            match_data,
            match_data.homeTeam.startingLineup,
            match_data.awayTeam.startingLineup,
        )
        assert result.predictedScore.home == 1
        assert result.predictedScore.away == 3
        assert result.confidencePct == 100.0
        assert _determine_result(result.predictedScore.home, result.predictedScore.away) == "away_win"
