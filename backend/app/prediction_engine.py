"""Prediction Engine for the FIFA Match Predictor.

Provides a weighted scoring model that estimates match outcomes based on
original match data and modified lineups. Uses per-player statistics when
available to produce more accurate swap impact predictions.
"""

import math

from app.models import (
    ContributingFactor,
    MatchData,
    Player,
    PlayerStats,
    PredictedOutcome,
    Score,
)

# Default shot conversion factor used when shotsOnTarget is 0
# Derived from typical football statistics (~0.1 goals per shot)
_DEFAULT_SHOT_CONVERSION_FACTOR = 0.1

# Phase 2 Lineup Delta calibration constants
_POSSESSION_PENALTY_PER_MISSING_MID = 0.95  # multiplier per missing midfielder
_ATTACK_PENALTY_PER_MISSING_FWD = 0.90  # multiplier per missing forward
_ATTACK_BONUS_PER_EXTRA_FWD = 1.05  # multiplier per extra forward
_GOAL_SCORER_REMOVAL_PENALTY = 0.85  # multiplier per goal scored by removed player
_SUBSTITUTE_CONTRIBUTION_BONUS = 1.03  # small positive factor for known substitute with events

# Per-player contribution weights for the enhanced model
_WEIGHT_GOALS = 0.30  # goals scored contribute 30% of impact
_WEIGHT_SHOTS = 0.15  # attempts at goal contribute 15%
_WEIGHT_PASSES = 0.20  # passing volume contributes 20%
_WEIGHT_LINE_BREAKS = 0.20  # line breaks contribute 20%
_WEIGHT_TAKE_ONS = 0.15  # take-ons contribute 15%


def _compute_player_contribution(
    player_stats: PlayerStats | None, team_stats_list: list[PlayerStats]
) -> float:
    """Compute a normalized contribution score for a player (0.0 to 1.0).

    The score is computed relative to the team's total output in each category.
    A player who contributed heavily to the team's attack gets a higher score.

    Returns 0.0 if no stats are available.
    """
    if not player_stats or not team_stats_list:
        return 0.0

    # Compute team totals
    team_goals = max(1, sum(ps.goals for ps in team_stats_list))
    team_shots = max(1, sum(ps.attemptsAtGoal for ps in team_stats_list))
    team_passes = max(1, sum(ps.passesCompleted for ps in team_stats_list))
    team_lb = max(1, sum(ps.lineBreaksCompleted for ps in team_stats_list))
    team_take_ons = max(1, sum(ps.takeOns for ps in team_stats_list))

    # Compute player's share of each category
    goal_share = player_stats.goals / team_goals
    shot_share = player_stats.attemptsAtGoal / team_shots
    pass_share = player_stats.passesCompleted / team_passes
    lb_share = player_stats.lineBreaksCompleted / team_lb
    take_on_share = player_stats.takeOns / team_take_ons

    # Weighted contribution score
    contribution = (
        _WEIGHT_GOALS * goal_share
        + _WEIGHT_SHOTS * shot_share
        + _WEIGHT_PASSES * pass_share
        + _WEIGHT_LINE_BREAKS * lb_share
        + _WEIGHT_TAKE_ONS * take_on_share
    )

    return min(1.0, contribution)


def _get_player_stats(
    player_name: str, squad_number: int, stats_list: list[PlayerStats]
) -> PlayerStats | None:
    """Look up a player's stats by name and squad number."""
    for ps in stats_list:
        if ps.squadNumber == squad_number and ps.playerName == player_name:
            return ps
    # Fallback: match by name only (names might have slight variations)
    for ps in stats_list:
        if ps.playerName == player_name:
            return ps
    return None


def _compute_baseline_xg(match_data: MatchData) -> tuple[float, float]:
    """Compute the baseline expected goals (xG) for home and away teams.

    The baseline xG is calibrated so that when the original lineup is
    submitted unchanged, the predicted score exactly matches the actual score.

    For each team:
        shotConversionFactor = actualGoals / shotsOnTarget
        xG = shotsOnTarget * shotConversionFactor = actualGoals

    Edge cases:
        - If shotsOnTarget is 0 but goals > 0: use actualGoals directly
          (e.g., own goals or deflections not counted as shots on target).
        - If shotsOnTarget is 0 and goals are 0: xG = 0.0
          (shotConversionFactor defaults to _DEFAULT_SHOT_CONVERSION_FACTOR
           but produces 0 since shotsOnTarget is 0).

    Args:
        match_data: The extracted MatchData including actual score and statistics.

    Returns:
        A tuple (home_xg, away_xg) where each value equals the actual goals
        scored by that team (satisfying the unchanged-lineup invariant).
    """
    home_stats = match_data.homeTeam.statistics
    away_stats = match_data.awayTeam.statistics
    actual_home = match_data.actualScore.home
    actual_away = match_data.actualScore.away

    # Compute home xG
    if home_stats.shotsOnTarget > 0:
        home_shot_conversion_factor = actual_home / home_stats.shotsOnTarget
        home_xg = home_stats.shotsOnTarget * home_shot_conversion_factor
    else:
        # Edge case: no shots on target
        # If goals were scored anyway (own goals, etc.), use actual goals directly
        # Otherwise xG is 0
        home_xg = float(actual_home)

    # Compute away xG
    if away_stats.shotsOnTarget > 0:
        away_shot_conversion_factor = actual_away / away_stats.shotsOnTarget
        away_xg = away_stats.shotsOnTarget * away_shot_conversion_factor
    else:
        away_xg = float(actual_away)

    return (home_xg, away_xg)


def _count_positions(lineup: list[Player]) -> dict[str, int]:
    """Count players by position in a lineup.

    Args:
        lineup: A list of Player objects.

    Returns:
        A dict mapping position string (GK, DEF, MID, FWD) to count.
    """
    counts: dict[str, int] = {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0}
    for player in lineup:
        counts[player.position] += 1
    return counts


def _compute_lineup_deltas(
    match_data: MatchData,
    original_lineup: list[Player],
    modified_lineup: list[Player],
    team_name: str,
) -> list[float]:
    """Compute multiplicative delta factors for lineup changes (Phase 2).

    For each substituted player, evaluates three dimensions:
    1. Positional coverage changes (MID/FWD balance)
    2. Removed goal-scorer impact
    3. Introduced substitute contributions

    Args:
        match_data: The full match data including events and team info.
        original_lineup: The original starting eleven for this team.
        modified_lineup: The modified starting eleven for this team.
        team_name: The name of the team (used to look up events).

    Returns:
        A list of multiplicative delta factors. Each factor represents
        one dimension of change. 1.0 means no change, <1.0 is a penalty,
        >1.0 is a bonus. When no players are changed, returns [1.0].
    """
    original_names = {p.name for p in original_lineup}
    modified_names = {p.name for p in modified_lineup}

    removed_names = original_names - modified_names
    added_names = modified_names - original_names

    # If no changes, return a single 1.0 factor (no effect)
    if not removed_names and not added_names:
        return [1.0]

    deltas: list[float] = []

    # --- 1. Positional coverage delta ---
    original_positions = _count_positions(original_lineup)
    modified_positions = _count_positions(modified_lineup)

    mid_diff = modified_positions["MID"] - original_positions["MID"]
    fwd_diff = modified_positions["FWD"] - original_positions["FWD"]

    if mid_diff < 0:
        # Fewer midfielders: possession penalty
        deltas.append(_POSSESSION_PENALTY_PER_MISSING_MID ** abs(mid_diff))

    if fwd_diff < 0:
        # Fewer forwards: attack penalty
        deltas.append(_ATTACK_PENALTY_PER_MISSING_FWD ** abs(fwd_diff))
    elif fwd_diff > 0:
        # More forwards: small attack bonus
        deltas.append(_ATTACK_BONUS_PER_EXTRA_FWD ** fwd_diff)

    # --- 2. Goal-scorer removal impact ---
    # Find goals scored by removed players in match events OR in player stats
    if team_name == match_data.homeTeam.name:
        team_player_stats = match_data.homeTeam.playerStats
    elif team_name == match_data.awayTeam.name:
        team_player_stats = match_data.awayTeam.playerStats
    else:
        team_player_stats = []

    for removed_player_name in removed_names:
        # Check events first
        goals_by_player = sum(
            1
            for event in match_data.events
            if event.type == "goal"
            and event.playerName == removed_player_name
            and event.teamName == team_name
        )
        # Also check player stats for goals (PMSR format may not have events)
        if goals_by_player == 0 and team_player_stats:
            removed_player_obj = next(
                (p for p in original_lineup if p.name == removed_player_name), None
            )
            if removed_player_obj:
                ps = _get_player_stats(
                    removed_player_name, removed_player_obj.squadNumber, team_player_stats
                )
                if ps and ps.goals > 0:
                    goals_by_player = ps.goals

        if goals_by_player > 0:
            deltas.append(_GOAL_SCORER_REMOVAL_PENALTY ** goals_by_player)

    # --- 3. Player contribution-based impact (enhanced model) ---
    # When per-player stats are available, compute the contribution of removed
    # players and apply a proportional penalty
    if team_player_stats:
        for removed_player_name in removed_names:
            removed_player_obj = next(
                (p for p in original_lineup if p.name == removed_player_name), None
            )
            if removed_player_obj:
                ps = _get_player_stats(
                    removed_player_name, removed_player_obj.squadNumber, team_player_stats
                )
                contribution = _compute_player_contribution(ps, team_player_stats)
                if contribution > 0.05:  # Only apply if player had meaningful contribution
                    # Higher contribution → bigger penalty for removal
                    # A player contributing 20% of team output → 0.80 multiplier
                    penalty = 1.0 - contribution
                    deltas.append(max(0.5, penalty))  # Floor at 0.5 to avoid extreme values

    # --- 4. Introduced substitute contributions ---
    # Check if added player is from the team's original substitutes list
    # and has events (goals, assists implied by substitution events, etc.)
    # Find the team's substitutes list
    if team_name == match_data.homeTeam.name:
        team_substitutes = match_data.homeTeam.substitutes
    elif team_name == match_data.awayTeam.name:
        team_substitutes = match_data.awayTeam.substitutes
    else:
        team_substitutes = []

    substitute_names = {p.name for p in team_substitutes}

    for added_player_name in added_names:
        if added_player_name in substitute_names:
            # Check if this substitute has any events in the match
            has_events = any(
                event.playerName == added_player_name
                and event.teamName == team_name
                for event in match_data.events
            )
            if has_events:
                deltas.append(_SUBSTITUTE_CONTRIBUTION_BONUS)

    # If no specific deltas were generated (e.g., swapped same-position
    # players with no goals), return [1.0]
    if not deltas:
        return [1.0]

    return deltas


def _compute_labeled_deltas(
    match_data: MatchData,
    original_lineup: list[Player],
    modified_lineup: list[Player],
    team_name: str,
) -> list[tuple[str, float]]:
    """Compute labeled delta factors for contributing factor generation.

    Same logic as _compute_lineup_deltas but returns (label, delta) pairs
    so that contributing factors can be named meaningfully.

    Args:
        match_data: The full match data including events and team info.
        original_lineup: The original starting eleven for this team.
        modified_lineup: The modified starting eleven for this team.
        team_name: The name of the team (used to look up events).

    Returns:
        A list of (label, delta) tuples. Labels are human-readable descriptions
        of each factor. When no players are changed, returns [].
    """
    original_names = {p.name for p in original_lineup}
    modified_names = {p.name for p in modified_lineup}

    removed_names = original_names - modified_names
    added_names = modified_names - original_names

    if not removed_names and not added_names:
        return []

    labeled_deltas: list[tuple[str, float]] = []

    # --- 1. Positional coverage delta ---
    original_positions = _count_positions(original_lineup)
    modified_positions = _count_positions(modified_lineup)

    mid_diff = modified_positions["MID"] - original_positions["MID"]
    fwd_diff = modified_positions["FWD"] - original_positions["FWD"]

    if mid_diff < 0:
        labeled_deltas.append(
            ("midfield coverage reduced", _POSSESSION_PENALTY_PER_MISSING_MID ** abs(mid_diff))
        )

    if fwd_diff < 0:
        labeled_deltas.append(
            ("attacking strength reduced", _ATTACK_PENALTY_PER_MISSING_FWD ** abs(fwd_diff))
        )
    elif fwd_diff > 0:
        labeled_deltas.append(
            ("attacking strength increased", _ATTACK_BONUS_PER_EXTRA_FWD ** fwd_diff)
        )

    # --- 2. Goal-scorer removal impact ---
    if team_name == match_data.homeTeam.name:
        team_player_stats = match_data.homeTeam.playerStats
    elif team_name == match_data.awayTeam.name:
        team_player_stats = match_data.awayTeam.playerStats
    else:
        team_player_stats = []

    for removed_player_name in sorted(removed_names):
        goals_by_player = sum(
            1
            for event in match_data.events
            if event.type == "goal"
            and event.playerName == removed_player_name
            and event.teamName == team_name
        )
        # Also check player stats
        if goals_by_player == 0 and team_player_stats:
            removed_player_obj = next(
                (p for p in original_lineup if p.name == removed_player_name), None
            )
            if removed_player_obj:
                ps = _get_player_stats(
                    removed_player_name, removed_player_obj.squadNumber, team_player_stats
                )
                if ps and ps.goals > 0:
                    goals_by_player = ps.goals

        if goals_by_player > 0:
            labeled_deltas.append(
                (f"goal-scorer {removed_player_name} removed", _GOAL_SCORER_REMOVAL_PENALTY ** goals_by_player)
            )

    # --- 3. Player contribution-based impact ---
    if team_player_stats:
        for removed_player_name in sorted(removed_names):
            removed_player_obj = next(
                (p for p in original_lineup if p.name == removed_player_name), None
            )
            if removed_player_obj:
                ps = _get_player_stats(
                    removed_player_name, removed_player_obj.squadNumber, team_player_stats
                )
                contribution = _compute_player_contribution(ps, team_player_stats)
                if contribution > 0.05:
                    penalty = max(0.5, 1.0 - contribution)
                    # Generate a descriptive label based on what the player contributed most
                    if ps and ps.goals > 0:
                        pass  # Already covered by goal-scorer removal
                    elif ps and ps.attemptsAtGoal >= 3:
                        labeled_deltas.append(
                            (f"key attacker {removed_player_name} removed ({ps.attemptsAtGoal} shots)", penalty)
                        )
                    elif ps and ps.passesCompleted >= 40:
                        labeled_deltas.append(
                            (f"key passer {removed_player_name} removed ({ps.passesCompleted} passes)", penalty)
                        )
                    elif ps and ps.lineBreaksCompleted >= 5:
                        labeled_deltas.append(
                            (f"creative player {removed_player_name} removed ({ps.lineBreaksCompleted} line breaks)", penalty)
                        )
                    else:
                        labeled_deltas.append(
                            (f"contributor {removed_player_name} removed", penalty)
                        )

    # --- 4. Introduced substitute contributions ---
    if team_name == match_data.homeTeam.name:
        team_substitutes = match_data.homeTeam.substitutes
    elif team_name == match_data.awayTeam.name:
        team_substitutes = match_data.awayTeam.substitutes
    else:
        team_substitutes = []

    substitute_names = {p.name for p in team_substitutes}

    for added_player_name in sorted(added_names):
        if added_player_name in substitute_names:
            has_events = any(
                event.playerName == added_player_name
                and event.teamName == team_name
                for event in match_data.events
            )
            if has_events:
                labeled_deltas.append(
                    ("proven substitute introduced", _SUBSTITUTE_CONTRIBUTION_BONUS)
                )

    return labeled_deltas


# --- Statistics-based filler factors (used to pad to minimum of 3) ---
_FILLER_FACTORS = [
    ("possession advantage", "positive"),
    ("shot accuracy", "positive"),
    ("defensive solidity", "positive"),
]


def _compute_contributing_factors(
    match_data: MatchData,
    home_deltas: list[float],
    away_deltas: list[float],
    modified_home_lineup: list[Player],
    modified_away_lineup: list[Player],
    total_changes: int,
) -> list[ContributingFactor]:
    """Surface the top 3-5 deltas as ContributingFactor objects.

    Derives named factors from the actual lineup deltas computed in Phase 2,
    sorts them by magnitude (abs(delta - 1.0)), and returns the top 3-5.
    If fewer than 3 real delta-based factors exist, pads with statistics-based
    filler factors.

    Args:
        match_data: The extracted MatchData including statistics.
        home_deltas: Multiplicative delta factors for the home team.
        away_deltas: Multiplicative delta factors for the away team.
        modified_home_lineup: The modified home lineup.
        modified_away_lineup: The modified away lineup.
        total_changes: Total number of player changes across both teams.

    Returns:
        A list of 3-5 ContributingFactor objects sorted by magnitude (descending).
    """
    # Get labeled deltas from both teams
    home_labeled = _compute_labeled_deltas(
        match_data,
        match_data.homeTeam.startingLineup,
        modified_home_lineup,
        match_data.homeTeam.name,
    )
    away_labeled = _compute_labeled_deltas(
        match_data,
        match_data.awayTeam.startingLineup,
        modified_away_lineup,
        match_data.awayTeam.name,
    )

    # Combine all labeled deltas
    all_labeled = home_labeled + away_labeled

    # Convert to ContributingFactor candidates
    candidates: list[tuple[float, ContributingFactor]] = []
    for label, delta in all_labeled:
        magnitude = abs(delta - 1.0)
        direction: str = "negative" if delta < 1.0 else "positive"
        # Convert magnitude to percentage (0.15 → 15%), clamped to [1, 100]
        magnitude_pct = max(1.0, min(100.0, round(magnitude * 100, 1)))
        candidates.append((
            magnitude,
            ContributingFactor(
                attribute=label,
                direction=direction,
                magnitudePct=magnitude_pct,
            ),
        ))

    # Sort by magnitude descending and take top 5
    candidates.sort(key=lambda x: x[0], reverse=True)
    factors = [cf for _, cf in candidates[:5]]

    # If fewer than 3 real factors, pad with statistics-based fillers
    if len(factors) < 3:
        home_stats = match_data.homeTeam.statistics
        filler_values = [
            # Possession advantage: use possessionPct directly, clamped
            max(1.0, min(100.0, round(home_stats.possessionPct, 1))),
            # Shot accuracy: shotsOnTarget / totalShots * 100
            max(
                1.0,
                min(
                    100.0,
                    round(
                        (home_stats.shotsOnTarget / max(1, home_stats.totalShots)) * 100,
                        1,
                    ),
                ),
            ),
            # Defensive solidity: inverse of fouls (fewer fouls = more solid)
            max(1.0, min(100.0, round(max(1.0, 100.0 - home_stats.fouls * 2), 1))),
        ]

        filler_idx = 0
        while len(factors) < 3 and filler_idx < len(_FILLER_FACTORS):
            attr, direction = _FILLER_FACTORS[filler_idx]
            # Avoid duplicate attributes
            existing_attrs = {f.attribute for f in factors}
            if attr not in existing_attrs:
                factors.append(
                    ContributingFactor(
                        attribute=attr,
                        direction=direction,
                        magnitudePct=filler_values[filler_idx],
                    )
                )
            filler_idx += 1

    # Final safety: ensure exactly 3-5 factors
    # If still fewer than 3 (shouldn't happen with 3 fillers), force-pad
    while len(factors) < 3:
        factors.append(
            ContributingFactor(
                attribute="match conditions",
                direction="positive",
                magnitudePct=1.0,
            )
        )

    return factors[:5]


# Penalty applied per unit of absolute positional delta (confidence model)
_CONFIDENCE_PENALTY_PER_SWAP = 10.0


def _compute_confidence(
    home_deltas: list[float],
    away_deltas: list[float],
    total_changes: int,
) -> float:
    """Compute prediction confidence score, clamped to [0, 100].

    The confidence starts at 100% (no changes) and decreases based on the
    sum of absolute positional deltas across all swaps. More lineup changes
    result in lower confidence.

    The formula is:
        sum_of_absolute_deltas = sum(abs(d - 1.0) for d in all_deltas if d != 1.0)
        confidence = 100.0 - sum_of_absolute_deltas * penalty_multiplier

    If sum_of_absolute_deltas is 0 (e.g. same-position swaps with no goal
    scorer impact), falls back to total_changes * penalty_per_swap.

    The result is always clamped to [0, 100].

    Args:
        home_deltas: Multiplicative delta factors for the home team lineup.
        away_deltas: Multiplicative delta factors for the away team lineup.
        total_changes: Total number of player changes across both teams.

    Returns:
        A float between 0.0 and 100.0 (inclusive) representing the
        confidence percentage.
    """
    all_deltas = home_deltas + away_deltas

    # Sum of absolute deviations from 1.0 (unchanged baseline)
    sum_of_absolute_deltas = sum(
        abs(d - 1.0) for d in all_deltas if d != 1.0
    )

    if sum_of_absolute_deltas > 0:
        # Penalty scales with how far deltas deviate from no-change (1.0)
        # Use a penalty multiplier of 100 so that each 0.1 delta deviation
        # reduces confidence by 10 percentage points
        penalty_multiplier = 100.0
        confidence = 100.0 - sum_of_absolute_deltas * penalty_multiplier
    else:
        # Fallback: use raw change count (e.g. same-position swaps with no
        # event-based impact produce deltas of [1.0])
        confidence = 100.0 - total_changes * _CONFIDENCE_PENALTY_PER_SWAP

    # Clamp to [0, 100]
    return max(0.0, min(100.0, confidence))


def predict(
    match_data: MatchData,
    modified_home_lineup: list[Player],
    modified_away_lineup: list[Player],
) -> PredictedOutcome:
    """Predict a match outcome given original match data and modified lineups.

    Args:
        match_data: The extracted MatchData including actual score and statistics.
        modified_home_lineup: The modified starting eleven for the home team (exactly 11 players).
        modified_away_lineup: The modified starting eleven for the away team (exactly 11 players).

    Returns:
        A PredictedOutcome with predicted score, confidence, contributing factors,
        and the modified lineups.

    Raises:
        ValueError: If either lineup does not contain exactly 11 players.
    """
    if len(modified_home_lineup) != 11:
        raise ValueError(
            f"Home lineup must have exactly 11 players, got {len(modified_home_lineup)}"
        )
    if len(modified_away_lineup) != 11:
        raise ValueError(
            f"Away lineup must have exactly 11 players, got {len(modified_away_lineup)}"
        )

    # Phase 1: Compute baseline xG from actual statistics
    home_xg, away_xg = _compute_baseline_xg(match_data)

    # Phase 2: Compute lineup deltas (multiplicative factors)
    home_deltas = _compute_lineup_deltas(
        match_data,
        match_data.homeTeam.startingLineup,
        modified_home_lineup,
        match_data.homeTeam.name,
    )
    away_deltas = _compute_lineup_deltas(
        match_data,
        match_data.awayTeam.startingLineup,
        modified_away_lineup,
        match_data.awayTeam.name,
    )

    # Phase 3: Score Simulation — apply deltas to baseline xG
    home_delta_product = math.prod(home_deltas)
    away_delta_product = math.prod(away_deltas)

    adjusted_home_xg = home_xg * home_delta_product
    adjusted_away_xg = away_xg * away_delta_product

    # Round to integers, ensuring non-negative
    predicted_home = max(0, round(adjusted_home_xg))
    predicted_away = max(0, round(adjusted_away_xg))

    # Determine how many changes were made to each lineup
    original_home_names = {p.name for p in match_data.homeTeam.startingLineup}
    original_away_names = {p.name for p in match_data.awayTeam.startingLineup}

    home_changes = sum(
        1 for p in modified_home_lineup if p.name not in original_home_names
    )
    away_changes = sum(
        1 for p in modified_away_lineup if p.name not in original_away_names
    )
    total_changes = home_changes + away_changes

    # Confidence calculation
    confidence = _compute_confidence(home_deltas, away_deltas, total_changes)

    # Contributing factors: derived from actual lineup deltas
    contributing_factors = _compute_contributing_factors(
        match_data,
        home_deltas,
        away_deltas,
        modified_home_lineup,
        modified_away_lineup,
        total_changes,
    )

    return PredictedOutcome(
        predictedScore=Score(home=predicted_home, away=predicted_away),
        confidencePct=confidence,
        contributingFactors=contributing_factors,
        modifiedHomeLineup=modified_home_lineup,
        modifiedAwayLineup=modified_away_lineup,
    )
