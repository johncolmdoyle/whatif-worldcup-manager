"""Tests to confirm Pydantic field validators reject invalid data."""

import uuid

import pytest
from pydantic import ValidationError

from app.models import (
    MatchData,
    MatchDataValidationError,
    MatchEvent,
    MatchStatistics,
    Player,
    Score,
    TeamData,
)


# --- Helpers ---

def _make_player(name="Test Player", squad_number=10, position="MID"):
    return Player(name=name, squadNumber=squad_number, position=position)


def _make_statistics():
    return MatchStatistics(
        possessionPct=55.0,
        shotsOnTarget=5,
        totalShots=12,
        passes=400,
        fouls=10,
    )


def _make_players(count: int) -> list[Player]:
    """Create a list of valid players of the given count."""
    positions = ["GK"] + ["DEF"] * 4 + ["MID"] * 3 + ["FWD"] * 3
    return [
        Player(name=f"Player {i+1}", squadNumber=i + 1, position=positions[i % len(positions)])
        for i in range(count)
    ]


# --- Player validators ---

class TestPlayerValidation:
    def test_name_too_long_rejected(self):
        """Player with name > 100 chars is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            _make_player(name="A" * 101)
        assert "name" in str(exc_info.value)

    def test_name_empty_rejected(self):
        """Player with empty name is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            _make_player(name="")
        assert "name" in str(exc_info.value)

    def test_squad_number_zero_rejected(self):
        """Player with squadNumber 0 is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            _make_player(squad_number=0)
        assert "squadNumber" in str(exc_info.value)

    def test_squad_number_100_rejected(self):
        """Player with squadNumber 100 is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            _make_player(squad_number=100)
        assert "squadNumber" in str(exc_info.value)

    def test_invalid_position_rejected(self):
        """Player with invalid position is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            _make_player(position="STRIKER")
        assert "position" in str(exc_info.value)


# --- MatchEvent validators ---

class TestMatchEventValidation:
    def test_minute_zero_rejected(self):
        """MatchEvent with minute 0 is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MatchEvent(type="goal", minute=0, playerName="Player", teamName="Team A")
        assert "minute" in str(exc_info.value)

    def test_minute_121_rejected(self):
        """MatchEvent with minute 121 is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MatchEvent(type="goal", minute=121, playerName="Player", teamName="Team A")
        assert "minute" in str(exc_info.value)

    def test_invalid_event_type_rejected(self):
        """MatchEvent with invalid type is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MatchEvent(type="penalty", minute=45, playerName="Player", teamName="Team A")
        assert "type" in str(exc_info.value)


# --- MatchStatistics validators ---

class TestMatchStatisticsValidation:
    def test_negative_shots_on_target_rejected(self):
        """MatchStatistics with negative shotsOnTarget is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MatchStatistics(
                possessionPct=50.0,
                shotsOnTarget=-1,
                totalShots=10,
                passes=300,
                fouls=10,
            )
        assert "shotsOnTarget" in str(exc_info.value)

    def test_negative_total_shots_rejected(self):
        """MatchStatistics with negative totalShots is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MatchStatistics(
                possessionPct=50.0,
                shotsOnTarget=5,
                totalShots=-1,
                passes=300,
                fouls=10,
            )
        assert "totalShots" in str(exc_info.value)

    def test_negative_passes_rejected(self):
        """MatchStatistics with negative passes is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MatchStatistics(
                possessionPct=50.0,
                shotsOnTarget=5,
                totalShots=10,
                passes=-1,
                fouls=10,
            )
        assert "passes" in str(exc_info.value)

    def test_negative_fouls_rejected(self):
        """MatchStatistics with negative fouls is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MatchStatistics(
                possessionPct=50.0,
                shotsOnTarget=5,
                totalShots=10,
                passes=300,
                fouls=-1,
            )
        assert "fouls" in str(exc_info.value)

    def test_negative_possession_rejected(self):
        """MatchStatistics with negative possessionPct is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MatchStatistics(
                possessionPct=-1.0,
                shotsOnTarget=5,
                totalShots=10,
                passes=300,
                fouls=10,
            )
        assert "possessionPct" in str(exc_info.value)


# --- TeamData startingLineup validators ---

class TestTeamDataValidation:
    def test_starting_lineup_0_players_rejected(self):
        """TeamData with 0 players in startingLineup is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            TeamData(
                name="Test Team",
                startingLineup=[],
                substitutes=_make_players(5),
                statistics=_make_statistics(),
            )
        assert "startingLineup" in str(exc_info.value)

    def test_starting_lineup_12_players_rejected(self):
        """TeamData with 12 players in startingLineup is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            TeamData(
                name="Test Team",
                startingLineup=_make_players(12),
                substitutes=_make_players(5),
                statistics=_make_statistics(),
            )
        assert "startingLineup" in str(exc_info.value)


# --- MatchData serialize/deserialize ---

def _make_match_data() -> MatchData:
    """Create a valid MatchData instance for testing."""
    stats = _make_statistics()
    home_team = TeamData(
        name="Argentina",
        startingLineup=_make_players(11),
        substitutes=_make_players(5),
        statistics=stats,
    )
    away_team = TeamData(
        name="France",
        startingLineup=[
            Player(name=f"Away Player {i+1}", squadNumber=i + 12, position=["GK", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "FWD", "FWD", "FWD"][i])
            for i in range(11)
        ],
        substitutes=_make_players(3),
        statistics=stats,
    )
    return MatchData(
        matchId=str(uuid.uuid4()),
        homeTeam=home_team,
        awayTeam=away_team,
        events=[
            MatchEvent(type="goal", minute=23, playerName="Player 1", teamName="Argentina"),
            MatchEvent(type="yellow_card", minute=45, playerName="Away Player 3", teamName="France"),
        ],
        actualScore=Score(home=2, away=1),
    )


class TestMatchDataSerializeDeserialize:
    def test_round_trip_produces_equal_object(self):
        """Serializing then deserializing MatchData produces an equal object."""
        original = _make_match_data()
        json_str = original.serialize()
        restored = MatchData.deserialize(json_str)
        assert restored == original

    def test_serialize_returns_string(self):
        """serialize() returns a JSON string."""
        match_data = _make_match_data()
        result = match_data.serialize()
        assert isinstance(result, str)

    def test_deserialize_invalid_json_raises_error(self):
        """Deserializing invalid JSON raises MatchDataValidationError."""
        with pytest.raises(MatchDataValidationError):
            MatchData.deserialize("not valid json")

    def test_deserialize_invalid_data_raises_error(self):
        """Deserializing JSON with invalid field values raises MatchDataValidationError."""
        match_data = _make_match_data()
        json_str = match_data.serialize()
        # Corrupt the JSON by replacing a valid squad number with an invalid one
        corrupted = json_str.replace('"squadNumber":1,', '"squadNumber":0,')
        with pytest.raises(MatchDataValidationError):
            MatchData.deserialize(corrupted)


# --- MatchDataValidationError tests ---

class TestMatchDataValidationError:
    def test_raises_match_data_validation_error_on_invalid_field(self):
        """When deserialization fails, a MatchDataValidationError is raised."""
        match_data = _make_match_data()
        json_str = match_data.serialize()
        # Make squadNumber invalid (0 is below minimum of 1)
        corrupted = json_str.replace('"squadNumber":1,', '"squadNumber":0,')
        with pytest.raises(MatchDataValidationError):
            MatchData.deserialize(corrupted)

    def test_failing_fields_lists_correct_field_names(self):
        """The failing_fields attribute lists the correct field names."""
        match_data = _make_match_data()
        json_str = match_data.serialize()
        # Corrupt squad number in homeTeam startingLineup
        corrupted = json_str.replace('"squadNumber":1,', '"squadNumber":0,')
        with pytest.raises(MatchDataValidationError) as exc_info:
            MatchData.deserialize(corrupted)
        error = exc_info.value
        assert isinstance(error.failing_fields, list)
        assert len(error.failing_fields) > 0
        # Should reference the homeTeam startingLineup squadNumber field
        assert any("squadNumber" in f for f in error.failing_fields)
        assert any("homeTeam" in f for f in error.failing_fields)

    def test_failing_fields_for_nested_statistics_field(self):
        """Failing fields correctly identifies nested statistics fields."""
        match_data = _make_match_data()
        json_str = match_data.serialize()
        # Corrupt possessionPct to be negative
        corrupted = json_str.replace('"possessionPct":55.0', '"possessionPct":-5.0')
        with pytest.raises(MatchDataValidationError) as exc_info:
            MatchData.deserialize(corrupted)
        error = exc_info.value
        assert any("possessionPct" in f for f in error.failing_fields)
        assert any("statistics" in f for f in error.failing_fields)

    def test_no_partial_match_data_on_failure(self):
        """No partial MatchData object is produced when validation fails."""
        match_data = _make_match_data()
        json_str = match_data.serialize()
        corrupted = json_str.replace('"squadNumber":1,', '"squadNumber":0,')
        result = None
        try:
            result = MatchData.deserialize(corrupted)
        except MatchDataValidationError:
            pass
        assert result is None

    def test_error_message_contains_field_names(self):
        """The error message string identifies the failing fields."""
        match_data = _make_match_data()
        json_str = match_data.serialize()
        corrupted = json_str.replace('"squadNumber":1,', '"squadNumber":0,')
        with pytest.raises(MatchDataValidationError) as exc_info:
            MatchData.deserialize(corrupted)
        error_msg = str(exc_info.value)
        assert "squadNumber" in error_msg

    def test_original_error_preserved(self):
        """The original Pydantic ValidationError is accessible."""
        match_data = _make_match_data()
        json_str = match_data.serialize()
        corrupted = json_str.replace('"squadNumber":1,', '"squadNumber":0,')
        with pytest.raises(MatchDataValidationError) as exc_info:
            MatchData.deserialize(corrupted)
        error = exc_info.value
        assert error.original_error is not None
        assert isinstance(error.original_error, ValidationError)
