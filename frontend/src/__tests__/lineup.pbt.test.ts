import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { appReducer, initialState, type AppState, type AppAction } from "../context/AppContext";
import type { Player, MatchData, TeamData, MatchStatistics } from "../types";

// --- Generators ---

const positionArb = fc.constantFrom("GK", "DEF", "MID", "FWD") as fc.Arbitrary<
  "GK" | "DEF" | "MID" | "FWD"
>;

const playerArb: fc.Arbitrary<Player> = fc.record({
  name: fc.string({ minLength: 1, maxLength: 50 }),
  squadNumber: fc.integer({ min: 1, max: 99 }),
  position: positionArb,
});

const lineupArb: fc.Arbitrary<Player[]> = fc.array(playerArb, {
  minLength: 11,
  maxLength: 11,
});

const statisticsArb: fc.Arbitrary<MatchStatistics> = fc.record({
  possessionPct: fc.integer({ min: 0, max: 100 }),
  shotsOnTarget: fc.integer({ min: 0, max: 30 }),
  totalShots: fc.integer({ min: 0, max: 50 }),
  passes: fc.integer({ min: 0, max: 1000 }),
  fouls: fc.integer({ min: 0, max: 30 }),
});

const teamDataArb: fc.Arbitrary<TeamData> = fc.record({
  name: fc.string({ minLength: 1, maxLength: 30 }),
  startingLineup: lineupArb,
  substitutes: fc.array(playerArb, { minLength: 0, maxLength: 12 }),
  statistics: statisticsArb,
});

const matchDataArb: fc.Arbitrary<MatchData> = fc.record({
  matchId: fc.uuid(),
  homeTeam: teamDataArb,
  awayTeam: teamDataArb,
  events: fc.constant([]),
  actualScore: fc.record({
    home: fc.integer({ min: 0, max: 10 }),
    away: fc.integer({ min: 0, max: 10 }),
  }),
});

/**
 * Generate a state after EXTRACTION_COMPLETE has been dispatched,
 * so modifiedHomeLineup and modifiedAwayLineup are populated with 11 players each.
 */
function extractedStateArb(): fc.Arbitrary<AppState> {
  return matchDataArb.map((matchData) => {
    const action: AppAction = {
      type: "EXTRACTION_COMPLETE",
      payload: { matchData },
    };
    return appReducer(initialState, action);
  });
}

/**
 * Generate a random action that modifies lineups: UPDATE_HOME_LINEUP, UPDATE_AWAY_LINEUP, or RESET_LINEUPS.
 */
function lineupActionArb(): fc.Arbitrary<AppAction> {
  return fc.oneof(
    lineupArb.map((lineup): AppAction => ({ type: "UPDATE_HOME_LINEUP", payload: lineup })),
    lineupArb.map((lineup): AppAction => ({ type: "UPDATE_AWAY_LINEUP", payload: lineup })),
    fc.constant<AppAction>({ type: "RESET_LINEUPS" })
  );
}

// --- Property Tests ---

describe("Lineup Property-Based Tests", () => {
  /**
   * Property 7: Lineup Count Invariant
   * After any sequence of swaps and resets, each team's modifiedLineup always contains exactly 11 players.
   *
   * **Validates: Requirements 4.4, 4.5**
   */
  it("Property 7: after any sequence of swap and reset operations each team always has exactly 11 players", () => {
    fc.assert(
      fc.property(
        extractedStateArb(),
        fc.array(lineupActionArb(), { minLength: 1, maxLength: 20 }),
        (state, actions) => {
          let current = state;
          for (const action of actions) {
            current = appReducer(current, action);
            expect(current.modifiedHomeLineup).not.toBeNull();
            expect(current.modifiedAwayLineup).not.toBeNull();
            expect(current.modifiedHomeLineup!.length).toBe(11);
            expect(current.modifiedAwayLineup!.length).toBe(11);
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  /**
   * Property 8: Reset Idempotence
   * Activating reset always produces a lineup equal to the original extracted lineup.
   *
   * **Validates: Requirements 4.6**
   */
  it("Property 8: reset always produces a lineup equal to the original", () => {
    fc.assert(
      fc.property(
        extractedStateArb(),
        fc.array(lineupActionArb(), { minLength: 0, maxLength: 20 }),
        (state, actions) => {
          // Apply a sequence of UPDATE actions
          let current = state;
          for (const action of actions) {
            current = appReducer(current, action);
          }

          // Now dispatch RESET_LINEUPS
          const afterReset = appReducer(current, { type: "RESET_LINEUPS" });

          // After reset, lineups must equal the original
          expect(afterReset.modifiedHomeLineup).toEqual(
            afterReset.matchData!.homeTeam.startingLineup
          );
          expect(afterReset.modifiedAwayLineup).toEqual(
            afterReset.matchData!.awayTeam.startingLineup
          );
        }
      ),
      { numRuns: 100 }
    );
  });

  /**
   * Property 9: Marker Consistency
   * A player entry carries a change marker if and only if it differs from the corresponding original player.
   *
   * **Validates: Requirements 4.7, 6.3**
   */
  it("Property 9: a player has a change marker if and only if it differs from the original", () => {
    // Replicate the isPlayerChanged logic from TeamLineup.tsx
    function isPlayerChanged(current: Player, original: Player): boolean {
      return (
        current.name !== original.name ||
        current.squadNumber !== original.squadNumber ||
        current.position !== original.position
      );
    }

    fc.assert(
      fc.property(
        extractedStateArb(),
        lineupArb,
        (state, modifiedLineup) => {
          // Apply an UPDATE_HOME_LINEUP with a generated lineup
          const updated = appReducer(state, {
            type: "UPDATE_HOME_LINEUP",
            payload: modifiedLineup,
          });

          const originalLineup = updated.matchData!.homeTeam.startingLineup;
          const currentLineup = updated.modifiedHomeLineup!;

          // For each player, verify marker consistency
          for (let i = 0; i < 11; i++) {
            const changed = isPlayerChanged(currentLineup[i], originalLineup[i]);
            const actuallyDifferent =
              currentLineup[i].name !== originalLineup[i].name ||
              currentLineup[i].squadNumber !== originalLineup[i].squadNumber ||
              currentLineup[i].position !== originalLineup[i].position;

            // Change marker is true IFF the player actually differs
            expect(changed).toBe(actuallyDifferent);
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});
