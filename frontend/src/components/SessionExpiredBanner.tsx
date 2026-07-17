import { useAppContext } from "../context/AppContext";

/**
 * Dismissible banner displayed when the session has expired.
 * Shows when state.error contains "Session expired" and can be
 * dismissed by clicking the X button (dispatches CLEAR_ERROR).
 */
export function SessionExpiredBanner() {
  const { state, dispatch } = useAppContext();

  const isSessionExpired = state.error?.includes("Session expired");

  if (!isSessionExpired) {
    return null;
  }

  return (
    <div
      role="alert"
      className="w-full bg-amber-50 border border-amber-300 text-amber-800 px-4 py-3 flex items-center justify-between"
    >
      <div className="flex items-center gap-2">
        <svg
          className="h-5 w-5 text-amber-500 flex-shrink-0"
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          aria-hidden="true"
        >
          <path
            fillRule="evenodd"
            d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.168 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 9a1 1 0 100-2 1 1 0 000 2z"
            clipRule="evenodd"
          />
        </svg>
        <p className="text-sm font-medium">{state.error}</p>
      </div>
      <button
        type="button"
        onClick={() => dispatch({ type: "CLEAR_ERROR" })}
        className="text-amber-600 hover:text-amber-800 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2 rounded p-1"
        aria-label="Dismiss session expired notification"
      >
        <svg
          className="h-5 w-5"
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          aria-hidden="true"
        >
          <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
        </svg>
      </button>
    </div>
  );
}
