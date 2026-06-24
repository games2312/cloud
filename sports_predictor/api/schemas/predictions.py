"""
Schémas Pydantic pour la validation et la documentation de l'API.
"""

from datetime import datetime
from typing import Optional, List, Dict
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Requêtes
# ---------------------------------------------------------------------------

class PredictionsRequest(BaseModel):
    """Requête de génération de pronostics."""
    date: str = Field(default="", description="Date au format YYYY-MM-DD (vide = aujourd'hui)")
    league_ids: Optional[List[int]] = Field(default=None, description="IDs des ligues ciblées")
    model_type: str = Field(default="ensemble", description="Type de modèle: ensemble, rf, xgb")


class PredictionsFilter(BaseModel):
    """Filtres pour la recherche de pronostics."""
    date_from: Optional[str] = Field(default=None, description="Date début YYYY-MM-DD")
    date_to: Optional[str] = Field(default=None, description="Date fin YYYY-MM-DD")
    min_confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    outcome: Optional[str] = Field(default=None, pattern="^(H|D|A)$")
    league_id: Optional[int] = None
    limit: int = Field(default=50, ge=1, le=500)


class MatchQuery(BaseModel):
    """Recherche de matchs."""
    date: Optional[str] = None
    league_id: Optional[int] = None
    team_name: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(scheduled|live|finished)$")
    limit: int = Field(default=50, ge=1, le=500)


class OddsQuery(BaseModel):
    """Recherche de cotes."""
    match_id: Optional[int] = None
    date: Optional[str] = None
    league_id: Optional[int] = None


class StatsQuery(BaseModel):
    """Requête de statistiques."""
    match_id: int


# ---------------------------------------------------------------------------
# Réponses
# ---------------------------------------------------------------------------

class TeamInfo(BaseModel):
    id: int
    name: str
    short_code: Optional[str] = None
    logo_url: Optional[str] = None


class LeagueInfo(BaseModel):
    id: int
    name: str
    country: Optional[str] = None
    season: Optional[str] = None


class OddsInfo(BaseModel):
    avg_home: Optional[float] = None
    avg_draw: Optional[float] = None
    avg_away: Optional[float] = None
    bookmaker_count: Optional[int] = None
    open_home: Optional[float] = None
    open_draw: Optional[float] = None
    open_away: Optional[float] = None
    close_home: Optional[float] = None
    close_draw: Optional[float] = None
    close_away: Optional[float] = None


class MatchResponse(BaseModel):
    id: int
    home_team: Optional[TeamInfo] = None
    away_team: Optional[TeamInfo] = None
    league: Optional[LeagueInfo] = None
    match_date: str
    status: str
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    odds: Optional[OddsInfo] = None

    class Config:
        from_attributes = True


class PredictionResponse(BaseModel):
    match_id: int
    match: Optional[MatchResponse] = None
    prob_home: float
    prob_draw: float
    prob_away: float
    predicted_outcome: str
    confidence: float
    model_name: str
    model_version: str
    brier_score: Optional[float] = None
    kelly_fraction: Optional[float] = None
    recommended_stake_pct: Optional[float] = None
    created_at: Optional[str] = None


class PredictionListItem(BaseModel):
    match_id: int
    home_team: str
    away_team: str
    match_date: str
    prob_home: float
    prob_draw: float
    prob_away: float
    predicted_outcome: str
    confidence: float


class ValueBetResponse(BaseModel):
    match_id: int
    home_team: str
    away_team: str
    outcome: str
    model_prob: float
    market_odd: float
    fair_odd: float
    edge_pct: float
    kelly_stake_pct: float
    confidence: str


class KellyPortfolioResponse(BaseModel):
    bets: List[Dict]
    total_stake: float
    total_exposure_pct: float
    remaining_bankroll: float


class PerformanceResponse(BaseModel):
    total_predictions: int
    accuracy: Optional[float] = None
    avg_brier_score: Optional[float] = None
    roi_pct: Optional[float] = None
    win_rate_pct: Optional[float] = None


class BacktestResponse(BaseModel):
    initial_bankroll: float
    final_bankroll: float
    roi_pct: float
    win_rate_pct: float
    total_bets: int
    max_drawdown_pct: float


class DashboardCard(BaseModel):
    """Carte résumé pour le tableau de bord."""
    today_matches: int
    live_matches: int
    predictions_ready: int
    value_bets_found: int
    daily_roi_estimate: Optional[float] = None


class DashboardResponse(BaseModel):
    summary: DashboardCard
    top_predictions: List[PredictionListItem]
    top_value_bets: List[ValueBetResponse]
    recent_results: List[MatchResponse]


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: Optional[float] = None
    db_connected: bool
    ml_models_loaded: bool


class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None