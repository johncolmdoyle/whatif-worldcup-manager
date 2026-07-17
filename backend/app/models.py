"""Pydantic v2 data models for the FIFA Match Predictor."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator


class MatchDataValidationError(Exception):
    """Raised when deserialization of MatchData fails validation.

    Attributes:
        failing_fields: List of dotted field paths that failed validation
            (e.g., "homeTeam.startingLineup", "awayTeam.statistics.possessionPct").
        original_error: The underlying Pydantic ValidationError.
    """

    def __init__(self, failing_fields: list[str], original_error: ValidationError) -> None:
        self.failing_fields = failing_fields
        self.original_error = original_error
        fields_str = ", ".join(failing_fields)
        super().__init__(
            f"Match data validation failed on field(s): {fields_str}"
        )

    @staticmethod
    def _extract_field_paths(error: ValidationError) -> list[str]:
        """Extract dotted field paths from a Pydantic ValidationError."""
        field_paths: list[str] = []
        for err in error.errors():
            loc = err.get("loc", ())
            # Build a dotted path from the location tuple, skipping integer indices
            # to keep field names readable (e.g., "homeTeam.startingLineup" not
            # "homeTeam.startingLineup.0.squadNumber")
            parts: list[str] = []
            for part in loc:
                if isinstance(part, int):
                    continue
                parts.append(str(part))
            if parts:
                path = ".".join(parts)
                if path not in field_paths:
                    field_paths.append(path)
        return field_paths


class Player(BaseModel):
    """A footballer identified by name, position, and squad number."""

    name: str = Field(..., min_length=1, max_length=100)
    squadNumber: int = Field(..., ge=1, le=99)
    position: Literal["GK", "DEF", "MID", "FWD"]


class MatchEvent(BaseModel):
    """A discrete occurrence during a match."""

    type: Literal["goal", "yellow_card", "red_card", "substitution"]
    minute: int = Field(..., ge=1, le=120)
    playerName: str
    teamName: str
    relatedPlayerName: Optional[str] = None


class MatchStatistics(BaseModel):
    """Aggregated numerical data from a match."""

    possessionPct: float = Field(..., ge=0, le=100)
    shotsOnTarget: int = Field(..., ge=0)
    totalShots: int = Field(..., ge=0)
    passes: int = Field(..., ge=0)
    fouls: int = Field(..., ge=0)


class PlayerStats(BaseModel):
    """Per-player performance statistics extracted from the match report."""

    playerName: str
    squadNumber: int = Field(..., ge=1, le=99)
    passesAttempted: int = Field(default=0, ge=0)
    passesCompleted: int = Field(default=0, ge=0)
    crossesAttempted: int = Field(default=0, ge=0)
    crossesCompleted: int = Field(default=0, ge=0)
    lineBreaksAttempted: int = Field(default=0, ge=0)
    lineBreaksCompleted: int = Field(default=0, ge=0)
    ballProgressions: int = Field(default=0, ge=0)
    takeOns: int = Field(default=0, ge=0)
    goals: int = Field(default=0, ge=0)
    attemptsAtGoal: int = Field(default=0, ge=0)


class TeamData(BaseModel):
    """Full team information including lineup, substitutes, and statistics."""

    name: str = Field(..., min_length=1)
    startingLineup: list[Player] = Field(..., min_length=1, max_length=11)
    substitutes: list[Player]
    statistics: MatchStatistics
    playerStats: list[PlayerStats] = Field(default_factory=list)


class Score(BaseModel):
    """A scoreline with home and away goals."""

    home: int = Field(..., ge=0)
    away: int = Field(..., ge=0)


class MatchData(BaseModel):
    """The structured representation of a FIFA match report."""

    matchId: str = Field(..., description="UUID identifying this match")
    homeTeam: TeamData
    awayTeam: TeamData
    events: list[MatchEvent]
    actualScore: Score

    @field_validator("matchId")
    @classmethod
    def validate_match_id(cls, v: str) -> str:
        """Validate matchId is a valid UUID format."""
        import uuid

        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("matchId must be a valid UUID")
        return v

    def serialize(self) -> str:
        """Serialize the MatchData instance to a JSON string."""
        return self.model_dump_json()

    @classmethod
    def deserialize(cls, json_str: str) -> "MatchData":
        """Deserialize a JSON string into a MatchData instance.

        Raises:
            MatchDataValidationError: If the JSON data fails validation.
                The exception includes a `failing_fields` attribute listing
                the dotted field paths that failed (e.g., "homeTeam.startingLineup").
                No partial MatchData object is produced on failure.
        """
        try:
            return cls.model_validate_json(json_str)
        except ValidationError as e:
            failing_fields = MatchDataValidationError._extract_field_paths(e)
            raise MatchDataValidationError(failing_fields, e) from e


class ContributingFactor(BaseModel):
    """A factor that contributed to the predicted outcome."""

    attribute: str
    direction: Literal["positive", "negative"]
    magnitudePct: float = Field(..., ge=1, le=100)


class PredictedOutcome(BaseModel):
    """The simulated match result produced by the Prediction Engine."""

    predictedScore: Score
    confidencePct: float = Field(..., ge=0, le=100)
    contributingFactors: list[ContributingFactor] = Field(
        ..., min_length=3, max_length=5
    )
    modifiedHomeLineup: list[Player]
    modifiedAwayLineup: list[Player]
