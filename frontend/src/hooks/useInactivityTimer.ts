import { useEffect, useRef, useCallback } from "react";
import { useAppContext } from "../context/AppContext";

const INACTIVITY_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes

/**
 * Hook that tracks user activity (mouse move, keydown, click, scroll, touch).
 * After 30 minutes of inactivity, dispatches SESSION_EXPIRED to warn the user.
 * Only active when a session exists (phase is not "upload").
 */
export function useInactivityTimer() {
  const { state, dispatch } = useAppContext();
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isSessionActive = state.phase !== "upload";

  const resetTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }

    timerRef.current = setTimeout(() => {
      dispatch({ type: "SESSION_EXPIRED" });
    }, INACTIVITY_TIMEOUT_MS);
  }, [dispatch]);

  useEffect(() => {
    if (!isSessionActive) {
      // No active session, clear any existing timer
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      return;
    }

    // Start the timer
    resetTimer();

    // Activity events that reset the timer
    const events: (keyof WindowEventMap)[] = [
      "mousemove",
      "keydown",
      "click",
      "scroll",
      "touchstart",
    ];

    const handleActivity = () => resetTimer();

    events.forEach((event) => {
      window.addEventListener(event, handleActivity);
    });

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      events.forEach((event) => {
        window.removeEventListener(event, handleActivity);
      });
    };
  }, [isSessionActive, resetTimer]);
}
