"""Property-based tests for FIFA Match Predictor data models using Hypothesis."""

import uuid

from hypothesis import given, settings
from hypothesis import strategies as st

from app.models import (
    ContributingFactor,
    MatchData,
    MatchDataValidationError,
    MatchEvent,
    MatchStatistics,
    Player,
    PredictedOutcome,
    Score,
    TeamData,
)

# ---------------------------------------------------------------------------
# Hypothesis Strategies for generating valid model instances
# ---------------------------------------------------------------------------

# Strategy for valid Player
@st.composite
def player_strategy(draw):
    name = draw(
        st.text(
            min_size=1,
            max_size=100,
            alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
        )
    )
    squad_number = draw(st.integers(min_value=1, max_value=99))
    position = draw(st.sampled_from(["GK", "DEF", "MID", "FWD"]))
    return Player(name=name, squadNumber=squad_number, position=position)


# Strategy for valid MatchEvent
@st.composite
def match_event_strategy(draw):
    event_type = draw(st.sampled_from(["goal", "yellow_card", "red_card", "substitution"]))
    minute = draw(st.integers(min_value=1, max_value=120))
    player_name = draw(
        st.text(
            min_size=1,
            max_size=50,
            alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
        )
    )
    team_name = draw(
        st.text(
            min_size=1,
            max_size=50,
            alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
        )
    )
    related = draw(
        st.one_of(
            st.none(),
            st.text(
                min_size=1,
                max_size=50,
                alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
            ),
        )
    )
    return MatchEvent(
        type=event_type,
        minute=minute,
        playerName=player_name,
        teamName=team_name,
        relatedPlayerName=related,
    )


# Strategy for valid MatchStatistics
@st.composite
def match_statistics_strategy(draw):
    return MatchStatistics(
        possessionPct=draw(
            st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False)
        ),
        shotsOnTarget=draw(st.integers(min_value=0, max_value=30)),
        totalShots=draw(st.integers(min_value=0, max_value=50)),
        passes=draw(st.integers(min_value=0, max_value=1000)),
        fouls=draw(st.integers(min_value=0, max_value=50)),
    )


# Strategy for valid TeamData (exactly 11 starters)
@st.composite
def team_data_strategy(draw):
    name = draw(
        st.text(
            min_size=1,
            max_size=50,
            alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
        )
    )
    starting = draw(st.lists(player_strategy(), min_size=11, max_size=11))
    subs = draw(st.lists(player_strategy(), min_size=0, max_size=12))
    stats = draw(match_statistics_strategy())
    return TeamData(name=name, startingLineup=starting, substitutes=subs, statistics=stats)


# Strategy for valid MatchData
@st.composite
def match_data_strategy(draw):
    home = draw(team_data_strategy())
    away = draw(team_data_strategy())
    events = draw(st.lists(match_event_strategy(), min_size=0, max_size=20))
    score = Score(
        home=draw(st.integers(min_value=0, max_value=10)),
        away=draw(st.integers(min_value=0, max_value=10)),
    )
    return MatchData(
        matchId=str(uuid.uuid4()),
        homeTeam=home,
        awayTeam=away,
        events=events,
        actualScore=score,
    )


# ---------------------------------------------------------------------------
# Smoke test to verify strategies generate valid objects
# ---------------------------------------------------------------------------


@given(match_data=match_data_strategy())
@settings(max_examples=10)
def test_strategy_generates_valid_match_data(match_data):
    """Smoke test: strategy produces valid MatchData with correct structure."""
    assert match_data.homeTeam.name
    assert len(match_data.homeTeam.startingLineup) == 11
    assert len(match_data.awayTeam.startingLineup) == 11
    assert match_data.actualScore.home >= 0
    assert match_data.actualScore.away >= 0


# ---------------------------------------------------------------------------
# Property 5: Round-Trip Integrity
# ---------------------------------------------------------------------------


@given(match_data=match_data_strategy())
@settings(max_examples=50)
def test_round_trip_integrity(match_data):
    """Property 5: For any valid MatchData, deserialize(serialize(matchData)) == matchData.

    This verifies that serialization to JSON and back produces a type-and-content
    equal object with all list orderings preserved.

    **Validates: Requirements 3.1, 3.2**
    """
    json_str = match_data.serialize()
    restored = MatchData.deserialize(json_str)
    assert restored == match_data


# ---------------------------------------------------------------------------
# Property 6: Validation Rejection
# ---------------------------------------------------------------------------

import json

# Strategy that picks a corruption to inject into serialized MatchData JSON.
# Each corruption is a tuple of (json_path_parts, invalid_value, expected_field_substring).
# json_path_parts is a list of keys/indices to traverse into the JSON dict.
# expected_field_substring is the field name that should appear in failing_fields.

@st.composite
def corruption_strategy(draw, match_data):
    """Choose a random corruption to inject into serialized MatchData JSON.

    Returns (json_path_parts, invalid_value, expected_field_fragment) where
    expected_field_fragment is a substring expected in the failing_fields list.
    """
    corruptions = [
        # squadNumber = 0 (below minimum of 1)
        (
            ["homeTeam", "startingLineup", 0, "squadNumber"],
            0,
            "squadNumber",
        ),
        # squadNumber = 100 (above maximum of 99)
        (
            ["awayTeam", "startingLineup", 0, "squadNumber"],
            100,
            "squadNumber",
        ),
        # position = "INVALID" (not in enum)
        (
            ["homeTeam", "startingLineup", 0, "position"],
            "INVALID",
            "position",
        ),
        # possessionPct = -5 (below minimum of 0)
        (
            ["homeTeam", "statistics", "possessionPct"],
            -5,
            "possessionPct",
        ),
        # possessionPct = 200 (above maximum of 100)
        (
            ["awayTeam", "statistics", "possessionPct"],
            200,
            "possessionPct",
        ),
        # shotsOnTarget = -1 (negative, below minimum of 0)
        (
            ["homeTeam", "statistics", "shotsOnTarget"],
            -1,
            "shotsOnTarget",
        ),
        # player name = "" (below minimum length of 1)
        (
            ["awayTeam", "startingLineup", 0, "name"],
            "",
            "name",
        ),
        # matchId = "not-a-uuid"
        (
            ["matchId"],
            "not-a-uuid",
            "matchId",
        ),
    ]

    # Add event corruption only if events exist
    data_dict = json.loads(match_data.serialize())
    if data_dict.get("events") and len(data_dict["events"]) > 0:
        corruptions.append(
            (
                ["events", 0, "minute"],
                999,
                "minute",
            )
        )
        corruptions.append(
            (
                ["events", 0, "type"],
                "INVALID_EVENT",
                "type",
            )
        )

    return draw(st.sampled_from(corruptions))


@given(match_data=match_data_strategy())
@settings(max_examples=50)
def test_validation_rejection_invalid_field(match_data):
    """Property 6: Injecting an invalid field into serialized JSON causes deserialization
    to raise a validation error naming that field.

    For any valid MatchData with an injected invalid field, deserialize() raises
    a MatchDataValidationError whose failing_fields attribute mentions the corrupted
    field name.

    **Validates: Requirements 3.3, 3.4**
    """
    # Serialize to JSON and parse into a dict
    json_str = match_data.serialize()
    data_dict = json.loads(json_str)

    # Build available corruptions based on this specific instance
    corruptions = [
        (["homeTeam", "startingLineup", 0, "squadNumber"], 0, "squadNumber"),
        (["awayTeam", "startingLineup", 0, "squadNumber"], 100, "squadNumber"),
        (["homeTeam", "startingLineup", 0, "position"], "INVALID", "position"),
        (["homeTeam", "statistics", "possessionPct"], -5, "possessionPct"),
        (["awayTeam", "statistics", "possessionPct"], 200, "possessionPct"),
        (["homeTeam", "statistics", "shotsOnTarget"], -1, "shotsOnTarget"),
        (["awayTeam", "startingLineup", 0, "name"], "", "name"),
        (["matchId"], "not-a-uuid", "matchId"),
    ]

    # Add event-based corruptions if events exist
    if data_dict.get("events") and len(data_dict["events"]) > 0:
        corruptions.append((["events", 0, "minute"], 999, "minute"))
        corruptions.append((["events", 0, "type"], "INVALID_EVENT", "type"))

    # Use Hypothesis to pick which corruption to apply
    # Since we're already inside @given, we use a deterministic choice based on the data
    # to still exercise all corruption paths across multiple examples.
    import hashlib
    hash_val = int(hashlib.md5(json_str.encode()).hexdigest(), 16)
    corruption_idx = hash_val % len(corruptions)
    path_parts, invalid_value, expected_field = corruptions[corruption_idx]

    # Inject the corruption
    target = data_dict
    for part in path_parts[:-1]:
        target = target[part]
    target[path_parts[-1]] = invalid_value

    # Re-serialize the corrupted dict
    corrupted_json = json.dumps(data_dict)

    # Attempt to deserialize — should raise MatchDataValidationError
    import pytest

    with pytest.raises(MatchDataValidationError) as exc_info:
        MatchData.deserialize(corrupted_json)

    # Verify that the failing_fields mentions the corrupted field name
    error = exc_info.value
    assert any(
        expected_field in field for field in error.failing_fields
    ), (
        f"Expected '{expected_field}' to be mentioned in failing_fields "
        f"{error.failing_fields} after injecting invalid value {invalid_value!r} "
        f"at path {path_parts}"
    )
