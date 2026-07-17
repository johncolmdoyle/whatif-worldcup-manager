import { useEffect, useRef } from "react";
import { useAppContext } from "../context/AppContext";
import { getSession, SessionExpiredError } from "../api/client";

/**
 * Hook that attempts to restore session data on page load/refresh.
 * Calls GET /api/session on mount:
 * - If successful, dispatches EXTRACTION_COMPLETE to restore state
 * - If 401, dispatches SESSION_EXPIRED to show notification and display upload view
 */
export function useSessionRestore() {
  const { dispatch } = useAppContext();
  const hasAttempted = useRef(false);

  useEffect(() => {
    if (hasAttempted.current) return;
    hasAttempted.current = true;

    async function restoreSession() {
      try {
        const result = await getSession();
        dispatch({
          type: "EXTRACTION_COMPLETE",
          payload: { matchData: result.matchData },
        });
      } catch (error) {
        if (error instanceof SessionExpiredError) {
          // Session doesn't exist or expired — show notification
          dispatch({ type: "SESSION_EXPIRED" });
        }
        // Other errors (network, etc.) — silently stay on upload view
      }
    }

    restoreSession();
  }, [dispatch]);
}
