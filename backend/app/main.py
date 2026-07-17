import os

from fastapi import Cookie, Depends, FastAPI, UploadFile, File, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.models import MatchData, Player
from app.pdf_parser import parse_match_report, PDFParseError
from app.prediction_engine import predict
from app.session import get_session_dependency, session_store, set_session_cookie


def _get_allowed_origins() -> list[str]:
    origins = os.getenv("ALLOWED_ORIGINS")
    if origins:
        return [origin.strip() for origin in origins.split(",") if origin.strip()]

    return ["http://localhost:5173", "http://localhost:3000"]

app = FastAPI(title="FIFA Match Predictor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/upload")
async def upload_pdf(response: Response, file: UploadFile = File(...)):
    # Validate content type
    if file.content_type != "application/pdf":
        return JSONResponse(
            status_code=400,
            content={"error": "Only PDF files are accepted"},
        )

    # Read file bytes and validate size
    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        return JSONResponse(
            status_code=413,
            content={"error": "File exceeds 50 MB limit"},
        )

    # Parse the PDF
    try:
        parse_result = parse_match_report(file_bytes)
    except PDFParseError as e:
        return JSONResponse(
            status_code=400,
            content={"error": str(e), "missingFields": e.missing_fields},
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "operation": "pdf_parsing"},
        )

    # Store match data in session
    match_data = parse_result.match_data
    session_id = session_store.create_session(match_data)
    set_session_cookie(response, session_id)

    # Build response payload
    response_body: dict = {"matchData": match_data.model_dump()}
    if parse_result.missing_fields:
        response_body["missingFields"] = parse_result.missing_fields

    return response_body


@app.get("/api/session")
async def get_session(match_data: MatchData = Depends(get_session_dependency)):
    """Return stored MatchData for the current session, or 401 if expired."""
    return {"matchData": match_data.model_dump()}


class PredictRequest(BaseModel):
    """Request body for the prediction endpoint."""

    homeLineup: list[Player]
    awayLineup: list[Player]


@app.post("/api/predict")
async def predict_outcome(
    request: PredictRequest,
    match_data: MatchData = Depends(get_session_dependency),
):
    """Accept modified lineups, validate, run prediction engine, return outcome."""
    # Validate both lineups have exactly 11 players
    if len(request.homeLineup) != 11:
        return JSONResponse(
            status_code=400,
            content={"error": f"Home lineup must have exactly 11 players, got {len(request.homeLineup)}"},
        )
    if len(request.awayLineup) != 11:
        return JSONResponse(
            status_code=400,
            content={"error": f"Away lineup must have exactly 11 players, got {len(request.awayLineup)}"},
        )

    # Run prediction engine
    try:
        predicted_outcome = predict(match_data, request.homeLineup, request.awayLineup)
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={"error": str(e)},
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "operation": "prediction"},
        )

    return {"predictedOutcome": predicted_outcome.model_dump()}


@app.delete("/api/session", status_code=204)
async def delete_session(response: Response, session_id: str | None = Cookie(None)):
    """Clear the current session and delete the session cookie. Returns 204 No Content.

    Idempotent: if no session cookie is present, still returns 204.
    """
    if session_id is not None:
        session_store.delete_session(session_id)

    # Delete the session cookie from the response
    response.delete_cookie(key="session_id", httponly=True, samesite="strict")
