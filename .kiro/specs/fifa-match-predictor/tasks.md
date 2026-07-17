# Implementation Plan:

## Overview

This plan implements the FIFA Match Predictor application: a FastAPI backend with pdfplumber-based PDF parsing and a React+TypeScript frontend. The implementation follows a bottom-up approach: data models first, then backend services (parser, session, prediction engine), then API endpoints, then frontend views, and finally end-to-end integration.

## Tasks

- [x] 1. Project Scaffolding
  Set up the monorepo structure with backend (FastAPI) and frontend (React+Vite) projects including all dependencies and configuration files.
  - [x] 1.1. Create `backend/` directory with `pyproject.toml` including dependencies: fastapi, uvicorn, pdfplumber, pydantic, python-multipart, redis, hypothesis, pytest
  - [x] 1.2. Create `backend/app/__init__.py` and `backend/app/main.py` with a minimal FastAPI app that returns 200 on `GET /health`
  - [x] 1.3. Create `frontend/` directory with Vite + React + TypeScript scaffold (`package.json`, `vite.config.ts`, `tsconfig.json`)
  - [x] 1.4. Add frontend dependencies: react, react-dom, tailwindcss, postcss, autoprefixer, fast-check, vitest, @testing-library/react
  - [x] 1.5. Configure TailwindCSS (`tailwind.config.js`, `postcss.config.js`, base CSS import)
  - [x] 1.6. Verify both `backend` and `frontend` start without errors

- [x] 2. Backend Data Models
  Implement Pydantic v2 models for all data structures defined in the design document.
  - [x] 2.1. Create `backend/app/models.py` with Pydantic models: Player, MatchEvent, MatchStatistics, TeamData, MatchData, ContributingFactor, PredictedOutcome
  - [x] 2.2. Add field validators: Player name 1–100 chars, squadNumber 1–99, position enum (GK/DEF/MID/FWD), MatchEvent minute 1–120, MatchEvent type enum, MatchStatistics fields non-negative, startingLineup exactly 11 players
  - [x] 2.3. Implement MatchData serialize() and deserialize(json_str) class methods with full validation on deserialization
  - [x] 2.4. Add validation error that identifies failing field(s) by name when deserialization fails

- [x] 3. Backend Data Model Property Tests
  Write Hypothesis property-based tests for the data models covering round-trip integrity and validation rejection.
  - [x] 3.1. Create `backend/tests/test_models_pbt.py`
  - [x] 3.2. Write Hypothesis strategy to generate valid MatchData objects (valid players, events, statistics)
  - [x] 3.3. Write property test: serialize then deserialize produces an equal object (Property 5)
  - [x] 3.4. Write property test: injecting an invalid field into serialized JSON causes deserialization to raise a validation error naming that field (Property 6)
  - [x] 3.5. Verify all property tests pass with `pytest backend/tests/`

- [x] 4. Session Store
  Implement the server-side session store with in-memory backend for development and TTL-based expiry.
  - [x] 4.1. Create `backend/app/session.py` with a SessionStore class using an in-memory dict
  - [x] 4.2. Implement create_session, get_session, set_session, delete_session methods
  - [x] 4.3. Implement 30-minute TTL: store timestamps, expire on access if older than 30 minutes
  - [x] 4.4. Implement session_id cookie handling as a FastAPI dependency (HTTP-only, SameSite=Strict)
  - [x] 4.5. Return 401 with error session_expired when session is missing or expired

- [x] 5. PDF Parser
  Implement the PDF parser that extracts structured match data from FIFA World Cup match report PDFs using pdfplumber.
  - [x] 5.1. Create `backend/app/pdf_parser.py` with a parse_match_report(file_bytes) function returning MatchData
  - [x] 5.2. Implement PDF validation: check file > 0 bytes, not password-protected, has at least 1 page
  - [x] 5.3. Implement lineup extraction: locate Line-ups section, parse starting XI and substitutes for both teams
  - [x] 5.4. Implement events extraction: locate match events section, parse goals, yellow cards, red cards, substitutions
  - [x] 5.5. Implement statistics extraction: locate statistics table, extract possession %, shots on target, total shots, passes, fouls
  - [x] 5.6. Implement partial extraction handling: return available fields plus list of missing field names
  - [x] 5.7. Add unit tests with a sample FIFA match report PDF in `backend/tests/fixtures/`

- [x] 6. Prediction Engine
  Implement the weighted scoring model that predicts match outcomes based on lineup changes and match statistics.
  - [x] 6.1. Create `backend/app/prediction_engine.py` with a predict function accepting MatchData and modified lineups returning PredictedOutcome
  - [x] 6.2. Implement Phase 1 Baseline Score: derive xG from actual statistics, calibrate shotConversionFactor to match actual scoreline
  - [x] 6.3. Implement Phase 2 Lineup Delta: compute positional coverage changes, removed goal-scorer impact, introduced substitute contributions
  - [x] 6.4. Implement Phase 3 Score Simulation: apply deltas to baseline xG, round to predicted goals as non-negative integers
  - [x] 6.5. Implement confidence score calculation clamped to 0-100
  - [x] 6.6. Implement contributing factors: surface top 3-5 deltas as ContributingFactor objects
  - [x] 6.7. Ensure unchanged lineup produces result matching actual win/draw/loss and goals within plus or minus 1

- [x] 7. Prediction Engine Property Tests
  Write Hypothesis property-based tests for the prediction engine covering all correctness properties.
  - [x] 7.1. Create `backend/tests/test_prediction_pbt.py`
  - [x] 7.2. Write property test: predicted goals are always non-negative integers (Property 2)
  - [x] 7.3. Write property test: confidence score is always in 0-100 range (Property 3)
  - [x] 7.4. Write property test: contributing factors always contains 3-5 items (Property 4)
  - [x] 7.5. Write property test: unchanged lineup produces matching win/draw/loss result and goals within plus or minus 1 (Property 1)
  - [x] 7.6. Verify all property tests pass

- [x] 8. API Endpoints
  Implement all REST API endpoints connecting the PDF parser, session store, and prediction engine.
  - [x] 8.1. Implement POST /api/upload: accept multipart PDF, validate type and size, parse, store in session, return MatchData
  - [x] 8.2. Implement GET /api/session: return stored MatchData or 401 if expired
  - [x] 8.3. Implement POST /api/predict: accept modified lineups, validate 11 players each, run prediction engine, return PredictedOutcome
  - [x] 8.4. Implement DELETE /api/session: clear session, return 204
  - [x] 8.5. Add error responses: 400 for validation, 413 for oversized files, 500 with operation name for internal failures
  - [x] 8.6. Add integration tests for all endpoints in `backend/tests/test_api.py`

- [x] 9. Frontend State Management
  Implement the React Context and useReducer-based state management with the AppState phase machine.
  - [x] 9.1. Create `frontend/src/context/AppContext.tsx` with AppState type and AppAction union type
  - [x] 9.2. Implement reducer handling phases: upload, extracted, editing, predicting, result
  - [x] 9.3. Implement SESSION_EXPIRED action that resets to upload phase
  - [x] 9.4. Create `frontend/src/api/client.ts` with API helper functions for upload, getSession, predict, deleteSession
  - [x] 9.5. Add session expiry interception: any 401 response dispatches SESSION_EXPIRED

- [x] 10. Frontend Upload View
  Build the PDF upload view with drag-and-drop, validation feedback, and progress indicator.
  - [x] 10.1. Create `frontend/src/views/UploadView.tsx` with drag-and-drop zone and file input accepting .pdf
  - [x] 10.2. Implement client-side validation: reject non-PDF files and files over 50 MB with appropriate error messages
  - [x] 10.3. Show progress indicator while upload is processing and update to success state on completion
  - [x] 10.4. Show error message on upload failure with ability to re-upload
  - [x] 10.5. On successful upload, dispatch EXTRACTION_COMPLETE action with MatchData and transition to extracted phase

- [x] 11. Frontend Extraction Summary View
  Build the extraction summary view that confirms extracted data before proceeding to lineup editing.
  - [x] 11.1. Create `frontend/src/views/ExtractionSummary.tsx` displaying team names, lineup counts, substitute counts, event count, and statistics presence
  - [x] 11.2. Show warning banner with missing field names if extraction was partial, with acknowledge button
  - [x] 11.3. Provide Edit Lineups button that transitions to editing phase
  - [x] 11.4. Provide Upload Different PDF button that clears session and returns to upload phase

- [x] 12. Frontend Lineup Editor View
  Build the lineup editor with side-by-side team display, player swaps, custom player entry, reset, and change markers.
  - [x] 12.1. Create `frontend/src/views/LineupEditorView.tsx` with side-by-side team lineup lists
  - [x] 12.2. Create `frontend/src/components/TeamLineup.tsx` rendering 11 starters with position, name, squad number
  - [x] 12.3. Create `frontend/src/components/PlayerSwapModal.tsx` allowing selection from substitutes or entry of custom player
  - [x] 12.4. Apply distinct visual marker to changed player entries and remove marker when restored to original
  - [x] 12.5. Implement reset button that restores both teams to original extracted lineups
  - [x] 12.6. Validate exactly 11 players per team before allowing predict submission with error if invalid
  - [x] 12.7. Implement Predict submit button that dispatches prediction request and transitions to predicting phase

- [x] 13. Frontend Result View
  Build the result view showing predicted vs actual scoreline, confidence, contributing factors, and annotated lineup.
  - [x] 13.1. Create `frontend/src/views/ResultView.tsx` with predicted scoreline section at top
  - [x] 13.2. Display actual result alongside predicted result in matching format
  - [x] 13.3. Display confidence score as percentage adjacent to predicted scoreline
  - [x] 13.4. Render 3-5 contributing factors as natural-language sentences
  - [x] 13.5. Display modified lineup with changed players marked with distinct visual marker
  - [x] 13.6. Provide Edit Lineup button returning to editing phase and Retry button for error cases

- [x] 14. Frontend Session Handling
  Implement session expiry notifications, clear session confirmation, and page refresh handling.
  - [x] 14.1. Add dismissible session-expired banner component that displays on SESSION_EXPIRED action
  - [x] 14.2. Implement Clear Session button with confirmation dialog; on confirm call DELETE /api/session and reset to upload phase
  - [x] 14.3. On page load or refresh, call GET /api/session; if 401 show session-cleared notification and display upload view
  - [x] 14.4. Implement 30-minute inactivity timer on frontend that shows expiry warning

- [x] 15. Frontend Property Tests
  Write fast-check property-based tests for the lineup editor state logic.
  - [x] 15.1. Create `frontend/src/__tests__/lineup.pbt.test.ts`
  - [x] 15.2. Write property test: after any sequence of swap and reset operations each team always has exactly 11 players (Property 7)
  - [x] 15.3. Write property test: reset always produces a lineup equal to the original (Property 8)
  - [x] 15.4. Write property test: a player has a change marker if and only if it differs from the original (Property 9)
  - [x] 15.5. Verify all property tests pass with npx vitest

- [x] 16. End-to-End Integration
  Wire frontend to backend, verify the full flow works end-to-end with CORS configuration and proxy setup.
  - [x] 16.1. Configure Vite proxy to forward /api requests to FastAPI backend during development
  - [x] 16.2. Add CORS middleware to FastAPI allowing the frontend origin
  - [x] 16.3. Test full flow: upload PDF, view extraction summary, edit lineup, predict, view result, edit again, predict again
  - [x] 16.4. Test error flows: invalid file upload, session expiry, prediction engine error with retry
  - [x] 16.5. Test clear session flow with confirmation dialog

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": [1] },
    { "wave": 2, "tasks": [2, 9] },
    { "wave": 3, "tasks": [3, 4, 5, 6, 10, 11, 12, 13, 14] },
    { "wave": 4, "tasks": [7, 8, 15] },
    { "wave": 5, "tasks": [16] }
  ],
  "dependencies": {
    "2": [1],
    "3": [2],
    "4": [2],
    "5": [2],
    "6": [2],
    "7": [6],
    "8": [4, 5, 6],
    "9": [1],
    "10": [9],
    "11": [9],
    "12": [9],
    "13": [9],
    "14": [9],
    "15": [12],
    "16": [8, 10, 11, 12, 13, 14]
  }
}
```

## Notes

- The backend uses an in-memory session store for development. Redis integration is deferred to a production deployment task.
- The PDF parser is designed against the standard FIFA World Cup match report layout. Older tournament formats may require layout-specific adjustments.
- Property-based tests use Hypothesis (Python backend) and fast-check (TypeScript frontend).
- A sample FIFA match report PDF should be placed in `backend/tests/fixtures/` for parser testing.
