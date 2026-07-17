import type { MatchData, Player, PredictedOutcome } from "../types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

export class ApiError extends Error {
  status: number;
  missingFields?: string[];

  constructor(status: number, message: string, missingFields?: string[]) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.missingFields = missingFields;
  }
}

export class SessionExpiredError extends ApiError {
  constructor(message = "Session expired") {
    super(401, message);
    this.name = "SessionExpiredError";
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    if (response.status === 401) {
      throw new SessionExpiredError();
    }

    let message = `Request failed with status ${response.status}`;
    let missingFields: string[] | undefined;

    try {
      const body = await response.json();
      if (body.error) {
        message = body.error;
      }
      if (body.missingFields) {
        missingFields = body.missingFields;
      }
    } catch {
      // Response body wasn't JSON; use default message
    }

    throw new ApiError(response.status, message, missingFields);
  }

  return response.json() as Promise<T>;
}

export async function uploadPdf(
  file: File
): Promise<{ matchData: MatchData; missingFields?: string[] }> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(apiUrl("/api/upload"), {
    method: "POST",
    body: formData,
    credentials: "include",
  });

  return handleResponse<{ matchData: MatchData; missingFields?: string[] }>(response);
}

export async function getSession(): Promise<{ matchData: MatchData }> {
  const response = await fetch(apiUrl("/api/session"), {
    method: "GET",
    credentials: "include",
  });

  return handleResponse<{ matchData: MatchData }>(response);
}

export async function predictOutcome(
  homeLineup: Player[],
  awayLineup: Player[]
): Promise<{ predictedOutcome: PredictedOutcome }> {
  const response = await fetch(apiUrl("/api/predict"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ homeLineup, awayLineup }),
    credentials: "include",
  });

  return handleResponse<{ predictedOutcome: PredictedOutcome }>(response);
}

export async function deleteSession(): Promise<void> {
  const response = await fetch(apiUrl("/api/session"), {
    method: "DELETE",
    credentials: "include",
  });

  if (!response.ok) {
    if (response.status === 401) {
      throw new SessionExpiredError();
    }

    let message = `Request failed with status ${response.status}`;
    try {
      const body = await response.json();
      if (body.error) {
        message = body.error;
      }
    } catch {
      // Response body wasn't JSON; use default message
    }

    throw new ApiError(response.status, message);
  }
}
