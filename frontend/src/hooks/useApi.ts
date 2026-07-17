import { useCallback } from "react";
import { useAppContext } from "../context/AppContext";
import { SessionExpiredError } from "../api/client";

/**
 * Hook that wraps API calls with session expiry interception.
 * Any API call that throws a SessionExpiredError (401 response)
 * will automatically dispatch SESSION_EXPIRED to reset app state.
 *
 * Usage:
 *   const { withSessionCheck } = useApi();
 *   const data = await withSessionCheck(() => uploadPdf(file));
 */
export function useApi() {
  const { dispatch } = useAppContext();

  const withSessionCheck = useCallback(
    async <T>(apiCall: () => Promise<T>): Promise<T> => {
      try {
        return await apiCall();
      } catch (error) {
        if (error instanceof SessionExpiredError) {
          dispatch({ type: "SESSION_EXPIRED" });
        }
        throw error;
      }
    },
    [dispatch]
  );

  return { withSessionCheck };
}
