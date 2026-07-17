import { useCallback } from "react";
import { useAppContext } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { deleteSession } from "../api/client";

const STATS_FIELDS = [
  "possessionPct",
  "shotsOnTarget",
  "totalShots",
  "passes",
  "fouls",
] as const;

const STATS_LABELS: Record<(typeof STATS_FIELDS)[number], string> = {
  possessionPct: "Possession %",
  shotsOnTarget: "Shots on Target",
  totalShots: "Total Shots",
  passes: "Passes",
  fouls: "Fouls",
};

export function ExtractionSummary() {
  const { state, dispatch } = useAppContext();
  const { withSessionCheck } = useApi();
  const { matchData, error } = state;

  const hasMissingFields = error?.startsWith("Missing fields:");
  const missingFieldNames = hasMissingFields
    ? error!.replace("Missing fields: ", "").split(", ")
    : [];

  const handleAcknowledge = useCallback(() => {
    dispatch({ type: "CLEAR_ERROR" });
  }, [dispatch]);

  const handleEditLineups = useCallback(() => {
    dispatch({ type: "START_EDITING" });
  }, [dispatch]);

  const handleUploadDifferent = useCallback(async () => {
    try {
      await withSessionCheck(() => deleteSession());
    } catch {
      // If session is already expired, SESSION_EXPIRED is dispatched by withSessionCheck
    }
    dispatch({ type: "SESSION_EXPIRED" });
  }, [dispatch, withSessionCheck]);

  if (!matchData) {
    return null;
  }

  const { homeTeam, awayTeam, events } = matchData;

  return (
    <div className="w-full max-w-2xl mx-auto px-4 py-8">
      <h2 className="text-2xl font-bold text-gray-800 mb-6">
        Extraction Summary
      </h2>

      {/* Missing fields warning banner */}
      {hasMissingFields && (
        <div
          role="alert"
          className="mb-6 p-4 rounded-md bg-yellow-50 border border-yellow-300"
        >
          <div className="flex items-start">
            <svg
              className="h-5 w-5 text-yellow-600 mt-0.5 mr-3 shrink-0"
              fill="currentColor"
              viewBox="0 0 20 20"
              aria-hidden="true"
            >
              <path
                fillRule="evenodd"
                d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.168 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 9a1 1 0 100-2 1 1 0 000 2z"
                clipRule="evenodd"
              />
            </svg>
            <div>
              <h3 className="text-sm font-semibold text-yellow-800">
                Missing Fields Detected
              </h3>
              <p className="mt-1 text-sm text-yellow-700">
                The following fields could not be extracted:{" "}
                <span className="font-medium">
                  {missingFieldNames.join(", ")}
                </span>
              </p>
              <button
                type="button"
                onClick={handleAcknowledge}
                className="mt-3 inline-flex items-center rounded-md bg-yellow-100 px-3 py-1.5 text-sm font-medium text-yellow-800 hover:bg-yellow-200 focus:outline-none focus:ring-2 focus:ring-yellow-500 focus:ring-offset-2"
              >
                Acknowledge
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Team names */}
      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <h3 className="text-lg font-semibold text-gray-700 mb-4">Teams</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="text-center">
            <p className="text-sm text-gray-500">Home</p>
            <p className="text-lg font-bold text-gray-800">{homeTeam.name}</p>
          </div>
          <div className="text-center">
            <p className="text-sm text-gray-500">Away</p>
            <p className="text-lg font-bold text-gray-800">{awayTeam.name}</p>
          </div>
        </div>
      </div>

      {/* Player counts */}
      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <h3 className="text-lg font-semibold text-gray-700 mb-4">Squads</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-sm font-medium text-gray-600">{homeTeam.name}</p>
            <ul className="mt-2 space-y-1 text-sm text-gray-700">
              <li>
                Starting lineup:{" "}
                <span className="font-semibold">
                  {homeTeam.startingLineup.length} players
                </span>
              </li>
              <li>
                Substitutes:{" "}
                <span className="font-semibold">
                  {homeTeam.substitutes.length} players
                </span>
              </li>
            </ul>
          </div>
          <div>
            <p className="text-sm font-medium text-gray-600">{awayTeam.name}</p>
            <ul className="mt-2 space-y-1 text-sm text-gray-700">
              <li>
                Starting lineup:{" "}
                <span className="font-semibold">
                  {awayTeam.startingLineup.length} players
                </span>
              </li>
              <li>
                Substitutes:{" "}
                <span className="font-semibold">
                  {awayTeam.substitutes.length} players
                </span>
              </li>
            </ul>
          </div>
        </div>
      </div>

      {/* Events count */}
      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <h3 className="text-lg font-semibold text-gray-700 mb-2">
          Match Events
        </h3>
        <p className="text-sm text-gray-700">
          Total events extracted:{" "}
          <span className="font-semibold">{events.length}</span>
        </p>
      </div>

      {/* Statistics presence */}
      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <h3 className="text-lg font-semibold text-gray-700 mb-4">
          Match Statistics
        </h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-sm font-medium text-gray-600 mb-2">
              {homeTeam.name}
            </p>
            <ul className="space-y-1">
              {STATS_FIELDS.map((field) => {
                const present =
                  homeTeam.statistics[field] !== undefined &&
                  homeTeam.statistics[field] !== null;
                return (
                  <li key={field} className="text-sm text-gray-700 flex items-center gap-2">
                    <span
                      className={present ? "text-green-600" : "text-red-500"}
                      aria-label={present ? "Present" : "Missing"}
                    >
                      {present ? "✓" : "✗"}
                    </span>
                    {STATS_LABELS[field]}
                  </li>
                );
              })}
            </ul>
          </div>
          <div>
            <p className="text-sm font-medium text-gray-600 mb-2">
              {awayTeam.name}
            </p>
            <ul className="space-y-1">
              {STATS_FIELDS.map((field) => {
                const present =
                  awayTeam.statistics[field] !== undefined &&
                  awayTeam.statistics[field] !== null;
                return (
                  <li key={field} className="text-sm text-gray-700 flex items-center gap-2">
                    <span
                      className={present ? "text-green-600" : "text-red-500"}
                      aria-label={present ? "Present" : "Missing"}
                    >
                      {present ? "✓" : "✗"}
                    </span>
                    {STATS_LABELS[field]}
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex flex-col sm:flex-row gap-3">
        <button
          type="button"
          onClick={handleEditLineups}
          disabled={hasMissingFields}
          className="flex-1 inline-flex justify-center items-center rounded-md bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Edit Lineups
        </button>
        <button
          type="button"
          onClick={handleUploadDifferent}
          className="flex-1 inline-flex justify-center items-center rounded-md bg-gray-100 px-4 py-2.5 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-200 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2"
        >
          Upload Different PDF
        </button>
      </div>
    </div>
  );
}
