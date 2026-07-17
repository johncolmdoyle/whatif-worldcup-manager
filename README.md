# What-If World Cup Manager

This project is a submission for **Kiro Birthday 2026, Day 4: Build one app with one sentence**.

It turns a FIFA World Cup match report PDF into a playable "what if?" simulator: upload the official report, let the app extract the squads, events, and stats, swap players in and out of the starting XI, and generate a predicted alternate outcome.

## Submission Context

**Challenge:** Day 4: Build one app with one sentence  
**Submission window:** Thursday, July 16, 2026, 3:00 AM EDT to Friday, July 17, 2026, 2:59 AM EDT

The rule for this challenge was simple:

1. Start from one genuine sentence.
2. Use **Kiro Specs** to generate the requirements, design, and task breakdown.
3. Build the app by following that generated spec.
4. Include the one-sentence prompt, the Kiro spec in `.kiro`, and a short demo video in the submission.

## One-Sentence Starting Prompt

`I want you to design and build an application that reads in a FIFA World Cup match report, the PDFs that they create after the game, and I want to be able to change the starting squad and have the application predict how the game would have turned out in that circumstance`

## What The App Does

The app takes an official FIFA World Cup match report PDF and turns it into an interactive alternate-history simulator.

The core flow is:

1. Upload a FIFA match report PDF.
2. Extract both teams, starting lineups, substitutes, events, and match statistics.
3. Edit either team's starting XI by swapping in bench players or adding a custom player.
4. Run a prediction engine to simulate how the result might have changed.
5. Compare the predicted scoreline with the actual match result and inspect the contributing factors.

## How This Came From Kiro

This project was built in the spirit of the challenge: the implementation was driven by a **Kiro-generated spec**, not by hand-written planning docs.

The Kiro spec for this project lives in:

- [.kiro/specs/fifa-match-predictor/requirements.md](/Users/johndoyle/Code/github/johncolmdoyle/whatif-worldcup-manager/.kiro/specs/fifa-match-predictor/requirements.md)
- [.kiro/specs/fifa-match-predictor/design.md](/Users/johndoyle/Code/github/johncolmdoyle/whatif-worldcup-manager/.kiro/specs/fifa-match-predictor/design.md)
- [.kiro/specs/fifa-match-predictor/tasks.md](/Users/johndoyle/Code/github/johncolmdoyle/whatif-worldcup-manager/.kiro/specs/fifa-match-predictor/tasks.md)
- [.kiro/specs/fifa-match-predictor/.config.kiro](/Users/johndoyle/Code/github/johncolmdoyle/whatif-worldcup-manager/.kiro/specs/fifa-match-predictor/.config.kiro)

That spec established the product in three layers:

- **Requirements** defined the user-facing behavior: PDF upload, extraction, lineup editing, prediction output, and session handling.
- **Design** chose the architecture: FastAPI backend, React/TypeScript frontend, PDF parsing with `pdfplumber`, and a session-backed prediction workflow.
- **Tasks** broke the build into executable implementation steps, from scaffolding and models to parser logic, prediction logic, frontend views, tests, and end-to-end integration.

In other words, the app wasn’t just "implemented with Kiro help." The product shape itself was derived from the Kiro spec workflow.

## Stack

- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS
- **Backend:** FastAPI, Pydantic v2, `pdfplumber`, `uvicorn`
- **Testing:** `pytest`, Hypothesis, Vitest, fast-check

## Repo Structure

- [frontend](/Users/johndoyle/Code/github/johncolmdoyle/whatif-worldcup-manager/frontend)
- [backend](/Users/johndoyle/Code/github/johncolmdoyle/whatif-worldcup-manager/backend)
- [.kiro/specs/fifa-match-predictor](/Users/johndoyle/Code/github/johncolmdoyle/whatif-worldcup-manager/.kiro/specs/fifa-match-predictor)
- [scripts/deploy-aws.sh](/Users/johndoyle/Code/github/johncolmdoyle/whatif-worldcup-manager/scripts/deploy-aws.sh)

## Running Locally

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --reload
```

The backend runs on `http://localhost:8000`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend runs on `http://localhost:5173`.

The Vite dev server proxies `/api` calls to the FastAPI backend during local development.

## Tests

### Backend

```bash
cd backend
.venv/bin/pytest
```

### Frontend

```bash
cd frontend
npm test -- --run
```

## Notes On Deployment

Deployment was handled as a separate step from the original Kiro-spec-driven app build.

This repo now also includes AWS deployment support for:

- S3 + CloudFront frontend hosting
- App Runner backend hosting
- Route 53 DNS configuration

Those deployment additions live outside the core Day 4 build story and are best treated as post-build operational work rather than the central submission artifact.

## Demo Video Checklist

For the final submission video, the key things to show are:

1. The one-sentence starting prompt.
2. The `.kiro` spec folder in the repo.
3. Uploading a FIFA match report PDF.
4. Extracted squads and match details.
5. Editing a lineup.
6. Generating and viewing a predicted alternate result.

## Why This Project Fits The Challenge

This is not a mockup or a concept deck. It is a working app with a real upload flow, real extraction pipeline, a real editing interface, and a functioning prediction workflow.

It also cleanly matches the Day 4 constraint:

- one app
- one sentence to start
- Kiro-generated spec in `.kiro`
- implementation built from that spec
