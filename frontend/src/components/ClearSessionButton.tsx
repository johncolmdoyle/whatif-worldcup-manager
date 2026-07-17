import { useCallback, useState } from "react";
import { useAppContext } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { deleteSession } from "../api/client";

/**
 * Clear Session button visible when a session is active (extracted/editing/result phases).
 * Shows a confirmation dialog before clearing. On confirm, calls DELETE /api/session
 * and dispatches SESSION_EXPIRED to reset to upload phase.
 */
export function ClearSessionButton() {
  const { state, dispatch } = useAppContext();
  const { withSessionCheck } = useApi();
  const [isClearing, setIsClearing] = useState(false);

  const isSessionActive = ["extracted", "editing", "predicting", "result"].includes(state.phase);

  const handleClearSession = useCallback(async () => {
    const confirmed = window.confirm(
      "Are you sure you want to clear your session? All extracted data and lineup changes will be lost."
    );

    if (!confirmed) return;

    setIsClearing(true);
    try {
      await withSessionCheck(() => deleteSession());
    } catch {
      // Even if the DELETE fails (e.g., session already expired), we still reset locally
    } finally {
      dispatch({ type: "SESSION_EXPIRED" });
      setIsClearing(false);
    }
  }, [dispatch, withSessionCheck]);

  if (!isSessionActive) {
    return null;
  }

  return (
    <button
      type="button"
      onClick={handleClearSession}
      disabled={isClearing}
      className="text-sm text-gray-500 hover:text-red-600 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 rounded px-2 py-1 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      aria-label="Clear session and start over"
    >
      {isClearing ? "Clearing..." : "Clear Session"}
    </button>
  );
}
