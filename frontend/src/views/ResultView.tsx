import { useCallback } from "react";
import { useAppContext } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { predictOutcome, ApiError } from "../api/client";
import type { Player, ContributingFactor } from "../types";

function isPlayerChanged(current: Player, original: Player): boolean {
  return (
    current.name !== original.name ||
    current.squadNumber !== original.squadNumber ||
    current.position !== original.position
  );
}

function formatFactor(factor: ContributingFactor): string {
  return `${factor.attribute} had a ${factor.direction} influence of ${factor.magnitudePct}%`;
}

export function ResultView() {
  const { state, dispatch } = useAppContext();
  const { withSessionCheck } = useApi();

  const { matchData, predictedOutcome, modifiedHomeLineup, modifiedAwayLineup, error } = state;

  const handleEditLineup = useCallback(() => {
    dispatch({ type: "START_EDITING" });
  }, [dispatch]);

  const handleRetry = useCallback(async () => {
    if (!modifiedHomeLineup || !modifiedAwayLineup) return;

    dispatch({ type: "PREDICT_START" });

    try {
      const result = await withSessionCheck(() =>
        predictOutcome(modifiedHomeLineup, modifiedAwayLineup)
      );
      dispatch({ type: "PREDICT_SUCCESS", payload: result.predictedOutcome });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "An unexpected error occurred during prediction.";
      dispatch({ type: "PREDICT_ERROR", payload: message });
    }
  }, [modifiedHomeLineup, modifiedAwayLineup, dispatch, withSessionCheck]);

  if (!matchData) {
    return null;
  }

  // Error state: show error message with retry control
  if (error && state.phase === "result") {
    return (
      <div className="w-full max-w-4xl mx-auto px-4 py-8">
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-6 text-center">
          <h2 className="text-xl font-semibold text-red-800 mb-2">Prediction Error</h2>
          <p className="text-red-700 mb-4">{error}</p>
          <div className="flex justify-center gap-4">
            <button
              type="button"
              onClick={handleRetry}
              className="inline-flex items-center rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
            >
              Retry
            </button>
            <button
              type="button"
              onClick={handleEditLineup}
              className="inline-flex items-center rounded-md bg-gray-100 px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-200 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2"
            >
              Edit Lineup
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!predictedOutcome) {
    return null;
  }

  const { predictedScore, confidencePct, contributingFactors, modifiedHomeLineup: resultHome, modifiedAwayLineup: resultAway } = predictedOutcome;

  return (
    <div className="w-full max-w-4xl mx-auto px-4 py-8">
      {/* Predicted Scoreline Section */}
      <section aria-label="Predicted result" className="text-center mb-8">
        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wide mb-2">
          Predicted Result
        </h2>
        <div className="flex items-center justify-center gap-3">
          <span className="text-3xl md:text-4xl font-bold text-gray-900">
            {matchData.homeTeam.name} {predictedScore.home} – {predictedScore.away} {matchData.awayTeam.name}
          </span>
          {/* Confidence Score Badge */}
          <span
            className="inline-flex items-center rounded-full bg-green-100 px-3 py-1 text-sm font-semibold text-green-800"
            aria-label={`Confidence: ${confidencePct}%`}
          >
            {confidencePct}%
          </span>
        </div>
      </section>

      {/* Actual Result Section */}
      <section aria-label="Actual result" className="text-center mb-8">
        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wide mb-1">
          Actual Result
        </h2>
        <p className="text-xl text-gray-600">
          {matchData.homeTeam.name} {matchData.actualScore.home} – {matchData.actualScore.away} {matchData.awayTeam.name}
        </p>
      </section>

      {/* Contributing Factors Section */}
      <section aria-label="Contributing factors" className="mb-8">
        <h3 className="text-lg font-semibold text-gray-800 mb-3">Contributing Factors</h3>
        <ul className="space-y-2">
          {contributingFactors.map((factor, index) => (
            <li
              key={index}
              className={`flex items-start gap-2 rounded-md px-3 py-2 text-sm ${
                factor.direction === "positive"
                  ? "bg-green-50 text-green-800"
                  : "bg-red-50 text-red-800"
              }`}
            >
              <span aria-hidden="true" className="mt-0.5">
                {factor.direction === "positive" ? "▲" : "▼"}
              </span>
              <span>{formatFactor(factor)}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* Modified Lineup Section */}
      <section aria-label="Modified lineups" className="mb-8">
        <h3 className="text-lg font-semibold text-gray-800 mb-3">Modified Lineups</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Home Team */}
          <div className="bg-white rounded-lg shadow p-4">
            <h4 className="text-md font-semibold text-gray-800 mb-3">{matchData.homeTeam.name}</h4>
            <ul aria-label={`${matchData.homeTeam.name} modified lineup`} className="space-y-1">
              {resultHome.map((player, index) => {
                const original = matchData.homeTeam.startingLineup[index];
                const changed = original ? isPlayerChanged(player, original) : false;
                return (
                  <li
                    key={index}
                    className={`px-3 py-2 rounded-md text-sm ${
                      changed ? "border-l-4 border-blue-500 bg-blue-50" : "border-l-4 border-transparent"
                    }`}
                  >
                    <span className="inline-block w-8 font-mono text-gray-500">
                      #{player.squadNumber}
                    </span>
                    <span className="font-medium text-gray-800">{player.name}</span>
                    <span className="ml-2 text-xs text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">
                      {player.position}
                    </span>
                    {changed && (
                      <span className="ml-2 text-xs text-blue-600 font-medium" aria-label="modified">
                        ★ modified
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>

          {/* Away Team */}
          <div className="bg-white rounded-lg shadow p-4">
            <h4 className="text-md font-semibold text-gray-800 mb-3">{matchData.awayTeam.name}</h4>
            <ul aria-label={`${matchData.awayTeam.name} modified lineup`} className="space-y-1">
              {resultAway.map((player, index) => {
                const original = matchData.awayTeam.startingLineup[index];
                const changed = original ? isPlayerChanged(player, original) : false;
                return (
                  <li
                    key={index}
                    className={`px-3 py-2 rounded-md text-sm ${
                      changed ? "border-l-4 border-blue-500 bg-blue-50" : "border-l-4 border-transparent"
                    }`}
                  >
                    <span className="inline-block w-8 font-mono text-gray-500">
                      #{player.squadNumber}
                    </span>
                    <span className="font-medium text-gray-800">{player.name}</span>
                    <span className="ml-2 text-xs text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">
                      {player.position}
                    </span>
                    {changed && (
                      <span className="ml-2 text-xs text-blue-600 font-medium" aria-label="modified">
                        ★ modified
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      </section>

      {/* Action Buttons */}
      <div className="flex justify-center gap-4">
        <button
          type="button"
          onClick={handleEditLineup}
          className="inline-flex items-center rounded-md bg-blue-600 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          Edit Lineup
        </button>
      </div>
    </div>
  );
}
