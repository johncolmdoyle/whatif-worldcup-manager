export interface Player {
  name: string;
  squadNumber: number;
  position: "GK" | "DEF" | "MID" | "FWD";
}

export interface MatchEvent {
  type: "goal" | "yellow_card" | "red_card" | "substitution";
  minute: number;
  playerName: string;
  teamName: string;
  relatedPlayerName?: string;
}

export interface MatchStatistics {
  possessionPct: number;
  shotsOnTarget: number;
  totalShots: number;
  passes: number;
  fouls: number;
}

export interface TeamData {
  name: string;
  startingLineup: Player[];
  substitutes: Player[];
  statistics: MatchStatistics;
}

export interface MatchData {
  matchId: string;
  homeTeam: TeamData;
  awayTeam: TeamData;
  events: MatchEvent[];
  actualScore: { home: number; away: number };
}

export interface ContributingFactor {
  attribute: string;
  direction: "positive" | "negative";
  magnitudePct: number;
}

export interface PredictedOutcome {
  predictedScore: { home: number; away: number };
  confidencePct: number;
  contributingFactors: ContributingFactor[];
  modifiedHomeLineup: Player[];
  modifiedAwayLineup: Player[];
}
