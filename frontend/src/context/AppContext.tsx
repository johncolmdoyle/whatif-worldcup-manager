import { createContext, useContext, useReducer, type ReactNode, type Dispatch } from "react";
import type { MatchData, Player, PredictedOutcome } from "../types";

export type AppState = {
  phase: "upload" | "extracted" | "editing" | "predicting" | "result";
  matchData: MatchData | null;
  modifiedHomeLineup: Player[] | null;
  modifiedAwayLineup: Player[] | null;
  predictedOutcome: PredictedOutcome | null;
  error: string | null;
};

export type AppAction =
  | { type: "UPLOAD_START" }
  | { type: "UPLOAD_SUCCESS" }
  | { type: "UPLOAD_ERROR"; payload: string }
  | { type: "EXTRACTION_COMPLETE"; payload: { matchData: MatchData; missingFields?: string[] } }
  | { type: "START_EDITING" }
  | { type: "UPDATE_HOME_LINEUP"; payload: Player[] }
  | { type: "UPDATE_AWAY_LINEUP"; payload: Player[] }
  | { type: "RESET_LINEUPS" }
  | { type: "PREDICT_START" }
  | { type: "PREDICT_SUCCESS"; payload: PredictedOutcome }
  | { type: "PREDICT_ERROR"; payload: string }
  | { type: "SESSION_EXPIRED" }
  | { type: "CLEAR_ERROR" };

const initialState: AppState = {
  phase: "upload",
  matchData: null,
  modifiedHomeLineup: null,
  modifiedAwayLineup: null,
  predictedOutcome: null,
  error: null,
};

function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "UPLOAD_START":
      return { ...state, error: null };
    case "UPLOAD_SUCCESS":
      return { ...state };
    case "UPLOAD_ERROR":
      return { ...state, error: action.payload };
    case "EXTRACTION_COMPLETE":
      return {
        ...state,
        phase: "extracted",
        matchData: action.payload.matchData,
        modifiedHomeLineup: action.payload.matchData.homeTeam.startingLineup,
        modifiedAwayLineup: action.payload.matchData.awayTeam.startingLineup,
        error: action.payload.missingFields
          ? `Missing fields: ${action.payload.missingFields.join(", ")}`
          : null,
      };
    case "START_EDITING":
      return { ...state, phase: "editing" };
    case "UPDATE_HOME_LINEUP":
      return { ...state, modifiedHomeLineup: action.payload };
    case "UPDATE_AWAY_LINEUP":
      return { ...state, modifiedAwayLineup: action.payload };
    case "RESET_LINEUPS":
      return {
        ...state,
        modifiedHomeLineup: state.matchData?.homeTeam.startingLineup ?? null,
        modifiedAwayLineup: state.matchData?.awayTeam.startingLineup ?? null,
      };
    case "PREDICT_START":
      return { ...state, phase: "predicting", error: null };
    case "PREDICT_SUCCESS":
      return { ...state, phase: "result", predictedOutcome: action.payload };
    case "PREDICT_ERROR":
      return { ...state, phase: "editing", error: action.payload };
    case "SESSION_EXPIRED":
      return { ...initialState, error: "Session expired. Please upload a new match report." };
    case "CLEAR_ERROR":
      return { ...state, error: null };
  }
}

type AppContextValue = {
  state: AppState;
  dispatch: Dispatch<AppAction>;
};

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(appReducer, initialState);

  return (
    <AppContext.Provider value={{ state, dispatch }}>
      {children}
    </AppContext.Provider>
  );
}

export function useAppContext(): AppContextValue {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error("useAppContext must be used within an AppProvider");
  }
  return context;
}

export { initialState, appReducer };
