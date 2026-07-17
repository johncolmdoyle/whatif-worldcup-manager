# Design Document

## Overview

The FIFA Match Predictor is a web application built with a Python (FastAPI) backend and a React/TypeScript frontend. Users upload an official FIFA World Cup match report PDF, the backend extracts structured match data, the frontend presents a lineup editor, and a prediction engine simulates what the result might have been with a different starting eleven.

The system is decomposed into four primary components:

1. **PDF Parser** — extracts structured Match_Data from the uploaded PDF
2. **Lineup Editor** — React UI for viewing and modifying starting lineups
3. **Prediction Engine** — scoring model that estimates a match outcome from lineup + statistics
4. **Session Store** — server-side session (backed by Redis or in-memory) to persist Match_Data within a 30-minute window

---

## Architecture

### High-Level Component Diagram

```
┌─────────────────────────────────────────────────────┐
│                     Browser (React)                  │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ Upload Page│  │Lineup Editor │  │ Result View  │ │
│  └─────┬──────┘  └──────┬───────┘  └──────┬───────┘ │
└────────┼────────────────┼─────────────────┼─────────┘
         │  HTTP/REST     │                 │
┌────────▼────────────────▼─────────────────▼─────────┐
│                  FastAPI Backend                      │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │PDF Parser  │  │Session Store │  │Prediction    │ │
│  │(pdfplumber)│  │(Redis/memory)│  │Engine        │ │
│  └────────────┘  └──────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────┘
```

### Request Flow

1. User uploads PDF → `POST /api/upload` → PDF Parser → Match_Data stored in session
2. Frontend renders Lineup Editor from session Match_Data
3. User modifies lineup → `POST /api/predict` with altered lineup → Prediction Engine → Predicted_Outcome returned
4. Frontend renders Result View

---

## Data Models

### Player

```typescript
interface Player {
  name: string;          // 1–100 characters
  squadNumber: number;   // 1–99
  position: "GK" | "DEF" | "MID" | "FWD";
}
```

### MatchEvent

```typescript
interface MatchEvent {
  type: "goal" | "yellow_card" | "red_card" | "substitution";
  minute: number;        // 1–120
  playerName: string;
  teamName: string;
  relatedPlayerName?: string; // for substitutions: the player coming on
}
```

### MatchStatistics

```typescript
interface MatchStatistics {
  possessionPct: number;    // 0–100
  shotsOnTarget: number;    // >= 0
  totalShots: number;       // >= 0
  passes: number;           // >= 0
  fouls: number;            // >= 0
}
```

### TeamData

```typescript
interface TeamData {
  name: string;
  startingLineup: Player[];   // exactly 11
  substitutes: Player[];
  statistics: MatchStatistics;
}
```

### MatchData

```typescript
interface MatchData {
  matchId: string;           // UUID generated on upload
  homeTeam: TeamData;
  awayTeam: TeamData;
  events: MatchEvent[];
  actualScore: {
    home: number;
    away: number;
  };
}
```

### ContributingFactor

```typescript
interface ContributingFactor {
  attribute: string;          // e.g. "positional strength"
  direction: "positive" | "negative";
  magnitudePct: number;       // 1–100
}
```

### PredictedOutcome

```typescript
interface PredictedOutcome {
  predictedScore: {
    home: number;
    away: number;
  };
  confidencePct: number;        // 0–100
  contributingFactors: ContributingFactor[];  // 3–5 items
  modifiedHomeLineup: Player[];
  modifiedAwayLineup: Player[];
}
```

---

## Components and Interfaces

### 1. PDF Parser

**Library:** `pdfplumber` (Python) — handles text extraction from multi-column PDFs without requiring OCR for standard FIFA report layouts.

**Strategy:**

FIFA World Cup match reports follow a consistent layout across tournaments. The parser uses a pattern-matching approach against known section headings and table structures:

- **Lineup extraction**: Locates the "Line-ups" section; parses two-column tables mapping squad number → name → position for starting XI and substitutes.
- **Events extraction**: Locates the "Match Events" / "Goals & Disciplinary" section; parses rows of `[minute] [event type] [player name]`.
- **Statistics extraction**: Locates the statistics table at the report footer; reads the five required fields (possession %, shots on target, total shots, passes, fouls) for each team.

**Validation:** After extraction, a Pydantic model validates the complete `MatchData` structure before it is stored in the session. Any missing fields produce a structured error response listing each missing field.

**Fallback:** If the standard layout is not detected (e.g., older tournament PDFs), the parser returns partial data with a list of fields it could not locate, allowing the user to acknowledge and proceed with whatever was extracted.

---

### 2. Session Store

Sessions are identified by a `session_id` cookie (HTTP-only, SameSite=Strict). `MatchData` is serialized to JSON and stored keyed by `session_id`.

- **Development**: Python `dict` in-process (sufficient for single-worker dev mode)
- **Production**: Redis with a 30-minute TTL

On each request the TTL is reset. If the key has expired, the backend returns a 401 with `{ "error": "session_expired" }` and the frontend displays the session expiry notification.

---

### 3. Prediction Engine

The engine uses a **weighted scoring model** derived entirely from data present in the match report — no external player ratings API is required, keeping the application self-contained.

#### Inputs

- `originalMatchData`: the extracted `MatchData` (including actual score)
- `modifiedHomeLineup`: the user's amended starting eleven for the home team
- `modifiedAwayLineup`: the user's amended starting eleven for the away team

#### Scoring Model

The model works in three phases:

**Phase 1 — Baseline Score**

Anchor on the actual match result. The baseline expected goals (xG) for each team is derived from their statistics:

```
xG = (shotsOnTarget / totalShots) * totalShots * shotConversionFactor
```

where `shotConversionFactor` is calibrated to match the actual scoreline when the original lineup is submitted unchanged (satisfying Requirement 5.4).

**Phase 2 — Lineup Delta**

For each substituted player, compute a positional impact delta:

- **Positional coverage**: Compare the position distribution of the original vs. modified lineup. A lineup with fewer midfielders than the original loses a possession multiplier; fewer forwards loses an attack multiplier.
- **Known match contribution**: If a substituted-out player scored a goal or provided a key event in the actual match, their absence reduces the attacking weight by a calibrated factor.
- **Introduced player**: If the new player is from the original squad (a substitute), their known in-match contribution (if any) is factored in positively.

**Phase 3 — Score Simulation**

```
adjustedXG_home = baselineXG_home * productOf(homeDeltas)
adjustedXG_away = baselineXG_away * productOf(awayDeltas)

predictedGoals_home = round(adjustedXG_home)
predictedGoals_away = round(adjustedXG_away)
```

**Confidence Score**

```
confidence = 100 - (sum of absolute positional deltas across all swaps) * penaltyPerSwap
```

Clamped to [0, 100]. More lineup changes → lower confidence.

**Contributing Factors**

The top 3–5 deltas by magnitude are surfaced as `ContributingFactor` objects with their attribute name, direction, and percentage magnitude.

---

### 4. Frontend (React + TypeScript)

**Stack:** React 18, TypeScript, Vite, TailwindCSS

#### Page / View Structure

```
App
├── UploadView          — drag-and-drop PDF upload, validation errors, progress bar
├── ExtractionSummary   — confirms extracted team names, player counts, event count, stats presence
├── LineupEditorView    — side-by-side team lineups (list layout), player swap controls, reset button
│   ├── TeamLineup      — renders 11 starters + bench, highlights changed players
│   └── PlayerSwapModal — select substitute or enter custom player (name + position)
└── ResultView          — predicted vs. actual scoreline, confidence %, factors list, annotated lineup
```

#### State Management

React Context + `useReducer` for application-level state:

```typescript
type AppState = {
  phase: "upload" | "extracted" | "editing" | "predicting" | "result";
  matchData: MatchData | null;
  modifiedHomeLineup: Player[] | null;
  modifiedAwayLineup: Player[] | null;
  predictedOutcome: PredictedOutcome | null;
  error: string | null;
};
```

Transitions are triggered by API responses. The session is purely server-side; the frontend holds a transient in-memory copy for rendering.

#### Session Expiry Handling

On any API response with `{ "error": "session_expired" }` or on page load after a refresh, the frontend dispatches a `SESSION_EXPIRED` action, resets local state to `phase: "upload"`, and displays a dismissible banner.

---

## API Endpoints

### `POST /api/upload`

- **Request**: `multipart/form-data` with `file` field (PDF, max 50 MB)
- **Response 200**: `{ "matchData": MatchData }`
- **Response 400**: `{ "error": string, "missingFields": string[] }`
- **Response 413**: `{ "error": "File exceeds 50 MB limit" }`
- **Sets** `session_id` cookie

### `GET /api/session`

- **Response 200**: `{ "matchData": MatchData }` if session active
- **Response 401**: `{ "error": "session_expired" }`

### `POST /api/predict`

- **Request**: `{ "homeLineup": Player[], "awayLineup": Player[] }`
- **Response 200**: `{ "predictedOutcome": PredictedOutcome }`
- **Response 400**: `{ "error": string }` (e.g. lineup validation failure)
- **Response 401**: `{ "error": "session_expired" }`
- **Response 500**: `{ "error": string, "operation": string }`

### `DELETE /api/session`

- **Response 204**: session cleared

---

## Correctness Properties

The prediction engine must satisfy the following formal correctness properties, validated via property-based tests:

### Property 1: Scoreline Consistency
When the original lineup is submitted unchanged, `predictedGoals` per team are each within ±1 of the actual goals scored.

**Validates: Requirements 5.4**

### Property 2: Non-Negative Scores
`predictedGoals` are always non-negative integers regardless of inputs.

**Validates: Requirements 5.2**

### Property 3: Confidence Bounds
`confidencePct` is always in [0, 100].

**Validates: Requirements 5.4, 6.4**

### Property 4: Factor Count
`contributingFactors` always contains between 3 and 5 items.

**Validates: Requirements 5.3, 6.2**

### Property 5: Round-Trip Integrity
For any valid `MatchData`, `deserialize(serialize(matchData)) == matchData`.

**Validates: Requirements 3.1, 3.2**

### Property 6: Validation Rejection
For any `MatchData` with an injected invalid field, deserialization raises a validation error naming that field.

**Validates: Requirements 3.3, 3.4**

### Property 7: Lineup Count Invariant
After any sequence of swaps and resets, each team's modified lineup always contains exactly 11 players.

**Validates: Requirements 4.4, 4.5**

### Property 8: Reset Idempotence
Activating reset always produces a lineup equal to the original extracted lineup.

**Validates: Requirements 4.6**

### Property 9: Marker Consistency
A player entry carries a change marker if and only if it differs from the corresponding original player.

**Validates: Requirements 4.7, 6.3**

---

## Testing Strategy

Property-based tests use **Hypothesis** (Python) for the backend and **fast-check** (TypeScript) for the frontend.

### Backend Properties

| Property | Description |
|---|---|
| **Round-trip integrity** | For any valid `MatchData` generated by Hypothesis, `deserialize(serialize(matchData)) == matchData` |
| **Validation rejection** | For any `MatchData` with an injected invalid field, `deserialize()` raises a validation error naming that field |
| **Scoreline consistency** | When the original lineup is submitted unchanged, `predictedGoals` are each within ±1 of actual goals |
| **Confidence bounds** | `confidencePct` is always in [0, 100] regardless of inputs |
| **Factor count** | `contributingFactors` always contains between 3 and 5 items |
| **Non-negative scores** | `predictedGoals` are always non-negative integers |

### Frontend Properties

| Property | Description |
|---|---|
| **Lineup count invariant** | After any sequence of swaps and resets, each team's `modifiedLineup` always contains exactly 11 players |
| **Reset idempotence** | Activating reset always produces a lineup equal to the original extracted lineup |
| **Marker consistency** | A player entry carries a change marker if and only if it differs from the corresponding original player |

---

## Error Handling

| Scenario | Backend response | Frontend behaviour |
|---|---|---|
| Non-PDF upload | 400 `only PDF files accepted` | Inline error below upload control |
| PDF > 50 MB | 413 | Inline error with size limit |
| Password-protected PDF | 400 `unreadable PDF` | Inline error |
| Missing extraction fields | 400 with `missingFields[]` | Warning banner listing fields; proceed button available |
| Parser runtime failure | 500 with operation name | Error message + re-upload button |
| Prediction engine failure | 500 with operation name | Error in result section + retry button (lineup retained) |
| Session expired | 401 | Dismissible banner + reset to upload view |
| Page refresh | — (state lost) | Same session-expired banner on next API call |

---

## Technology Stack Summary

| Layer | Technology |
|---|---|
| Frontend framework | React 18 + TypeScript |
| Frontend build | Vite |
| Styling | TailwindCSS |
| Backend framework | FastAPI (Python 3.11+) |
| PDF parsing | pdfplumber |
| Data validation | Pydantic v2 |
| Session storage (dev) | In-process dict |
| Session storage (prod) | Redis |
| Backend PBT | Hypothesis |
| Frontend PBT | fast-check |
| Frontend unit tests | Vitest + React Testing Library |
