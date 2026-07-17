import { useCallback, useState } from "react";
import { useAppContext } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { predictOutcome, ApiError } from "../api/client";
import { TeamLineup } from "../components/TeamLineup";
import type { Player } from "../types";

export function LineupEditorView() {
  const { state, dispatch } = useAppContext();
  const { withSessionCheck } = useApi();
  const [validationError, setValidationError] = useState<string | null>(null);
  const [isPredicting, setIsPredicting] = useState(false);

  const { matchData, modifiedHomeLineup, modifiedAwayLineup } = state;

  const handleHomePlayerSwap = useCallback(
    (index: number, newPlayer: Player) => {
      if (!modifiedHomeLineup) return;
      const updated = [...modifiedHomeLineup];
      updated[index] = newPlayer;
      dispatch({ type: "UPDATE_HOME_LINEUP", payload: updated });
    },
    [modifiedHomeLineup, dispatch]
  );

  const handleAwayPlayerSwap = useCallback(
    (index: number, newPlayer: Player) => {
      if (!modifiedAwayLineup) return;
      const updated = [...modifiedAwayLineup];
      updated[index] = newPlayer;
      dispatch({ type: "UPDATE_AWAY_LINEUP", payload: updated });
    },
    [modifiedAwayLineup, dispatch]
  );

  const handleReset = useCallback(() => {
    dispatch({ type: "RESET_LINEUPS" });
    setValidationError(null);
  }, [dispatch]);

  const handlePredict = useCallback(async () => {
    setValidationError(null);

    if (!modifiedHomeLineup || modifiedHomeLineup.length !== 11) {
      setValidationError("Home team must have exactly 11 players.");
      return;
    }
    if (!modifiedAwayLineup || modifiedAwayLineup.length !== 11) {
      setValidationError("Away team must have exactly 11 players.");
      return;
    }

    dispatch({ type: "PREDICT_START" });
    setIsPredicting(true);

    try {
      const result = await withSessionCheck(() =>
        predictOutcome(modifiedHomeLineup, modifiedAwayLineup)
      );
      dispatch({ type: "PREDICT_SUCCESS", payload: result.predictedOutcome });
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : "An unexpected error occurred during prediction.";
      dispatch({ type: "PREDICT_ERROR", payload: message });
    } finally {
      setIsPredicting(false);
    }
  }, [modifiedHomeLineup, modifiedAwayLineup, dispatch, withSessionCheck]);

  if (!matchData || !modifiedHomeLineup || !modifiedAwayLineup) {
    return null;
  }

  return (
    <div className="w-full max-w-4xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-gray-800">Edit Lineups</h2>
        <button
          type="button"
          onClick={handleReset}
          className="inline-flex items-center rounded-md bg-gray-100 px-3 py-2 text-sm font-medium text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-200 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2"
        >
          Reset Lineups
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <TeamLineup
          teamName={matchData.homeTeam.name}
          lineup={modifiedHomeLineup}
          originalLineup={matchData.homeTeam.startingLineup}
          substitutes={matchData.homeTeam.substitutes}
          onPlayerSwap={handleHomePlayerSwap}
        />
        <TeamLineup
          teamName={matchData.awayTeam.name}
          lineup={modifiedAwayLineup}
          originalLineup={matchData.awayTeam.startingLineup}
          substitutes={matchData.awayTeam.substitutes}
          onPlayerSwap={handleAwayPlayerSwap}
        />
      </div>

      {(validationError || state.error) && (
        <div role="alert" className="mt-4 p-3 rounded-md bg-red-50 border border-red-200 text-red-700 text-sm">
          {validationError || state.error}
        </div>
      )}

      <div className="mt-6 flex justify-center">
        <button
          type="button"
          onClick={handlePredict}
          disabled={isPredicting}
          className="inline-flex items-center rounded-md bg-blue-600 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isPredicting ? (
            <>
              <svg
                className="animate-spin -ml-1 mr-2 h-4 w-4 text-white"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Predicting...
            </>
          ) : (
            "Predict Outcome"
          )}
        </button>
      </div>
    </div>
  );
}
