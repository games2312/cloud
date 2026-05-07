"""
Routes API pour les pronostics sportifs.
Endpoints REST pour la consultation et la génération de pronostics.
"""

import asyncio
from datetime import datetime, date
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session

from api.schemas.predictions import (
    PredictionsRequest,
    PredictionsFilter,
    PredictionResponse,
    PredictionListItem,
    ValueBetResponse,
    KellyPortfolioResponse,
    PerformanceResponse,
    BacktestResponse,
    DashboardResponse,
    DashboardCard,
    HealthResponse,
    MatchResponse,
    MatchQuery,
    OddsQuery,
)
from database.models import (
    Match, Prediction, Odds, Team, League, get_session
)
from models.predict import PredictionGenerator
from analysis.value_betting import ValueBetDetector
from analysis.kelly import KellyCriterion
from config.settings import config as cfg

router = APIRouter(prefix="/api/v1", tags=["predictions"])


def get_db() -> Session:
    """Dépendance DB."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


# =========================================================================
# Santé
# =========================================================================

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Vérification de l'état du système."""
    try:
        db = get_session()
        db.execute("SELECT 1")
        db_ok = True
        db.close()
    except Exception:
        db_ok = False

    return HealthResponse(
        status="healthy" if db_ok else "degraded",
        version=cfg.api.version,
        db_connected=db_ok,
        ml_models_loaded=False,  # à initialiser au startup
    )


# =========================================================================
# Dashboard
# =========================================================================

@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(db: Session = Depends(get_db)):
    """Tableau de bord résumé (matchs du jour, top pronostics)."""
    today = date.today()

    today_matches = db.query(Match).filter(
        Match.match_date >= today,
        Match.match_date < today.replace(day=today.day + 1),
    ).count()

    live_matches = db.query(Match).filter(Match.status == "live").count()

    predictions_ready = db.query(Prediction).join(Match).filter(
        Match.match_date >= today,
        Match.match_date < today.replace(day=today.day + 1),
    ).count()

    value_bets_found = 0
    # Récupération des top prédictions
    generator = PredictionGenerator()
    top_preds = generator.get_top_predictions(db, min_confidence=0.4, limit=5)

    return DashboardResponse(
        summary=DashboardCard(
            today_matches=today_matches,
            live_matches=live_matches,
            predictions_ready=predictions_ready,
            value_bets_found=value_bets_found,
        ),
        top_predictions=[
            PredictionListItem(
                match_id=p["match_id"],
                home_team=p["home_team"],
                away_team=p["away_team"],
                match_date="",
                prob_home=p["odds"]["home"],
                prob_draw=p["odds"]["draw"],
                prob_away=p["odds"]["away"],
                predicted_outcome=p["outcome"],
                confidence=p["confidence"],
            )
            for p in top_preds
        ],
        top_value_bets=[],
        recent_results=[],
    )


# =========================================================================
# Pronostics
# =========================================================================

@router.post("/predictions/generate", response_model=List[PredictionResponse])
async def generate_predictions(
    req: PredictionsRequest,
    db: Session = Depends(get_db),
):
    """Lance la génération de pronostics pour une date donnée."""
    generator = PredictionGenerator()
    try:
        # Chargement des modèles (en production: via MLflow registry)
        # Pour le MVP, chemins locaux
        from models.trainer import ModelTrainer
        trainer = ModelTrainer()

        rf_model = trainer.load_model("models_saved/rf_latest.pkl") if False else None
        xgb_model = trainer.load_model("models_saved/xgb_latest.pkl") if False else None

        if rf_model is None or xgb_model is None:
            raise HTTPException(
                status_code=503,
                detail="Modèles non disponibles. Lancez l'entraînement d'abord.",
            )

        results = generator.generate_daily(
            db, rf_model, xgb_model, req.date or None
        )

        response = []
        for pred in results:
            match = db.query(Match).filter(Match.id == pred["match_id"]).first()
            response.append(PredictionResponse(
                match_id=pred["match_id"],
                match=_build_match_response(match) if match else None,
                prob_home=pred["prob_home"],
                prob_draw=pred["prob_draw"],
                prob_away=pred["prob_away"],
                predicted_outcome=pred["predicted_outcome"],
                confidence=pred["confidence"],
                model_name=pred["model_name"],
                model_version=pred["model_version"],
                created_at=str(pred["created_at"]),
            ))

        return response

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/predictions", response_model=List[PredictionListItem])
async def list_predictions(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    min_confidence: float = Query(0.3, ge=0.0, le=1.0),
    outcome: Optional[str] = Query(None, pattern="^(H|D|A)$"),
    league_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Liste les pronostics avec filtres."""
    query = db.query(Prediction).join(Match)

    if date_from:
        query = query.filter(Match.match_date >= datetime.strptime(date_from, "%Y-%m-%d"))
    if date_to:
        query = query.filter(Match.match_date <= datetime.strptime(date_to, "%Y-%m-%d"))
    if outcome:
        query = query.filter(Prediction.predicted_outcome == outcome)
    if league_id:
        query = query.filter(Match.league_id == league_id)

    query = query.filter(Prediction.confidence >= min_confidence)
    query = query.order_by(Prediction.confidence.desc()).limit(limit)

    preds = query.all()

    results = []
    for pred in preds:
        match = db.query(Match).filter(Match.id == pred.match_id).first()
        if match:
            results.append(PredictionListItem(
                match_id=pred.match_id,
                home_team=match.home_team.name if match.home_team else "?",
                away_team=match.away_team.name if match.away_team else "?",
                match_date=str(match.match_date),
                prob_home=pred.prob_home,
                prob_draw=pred.prob_draw,
                prob_away=pred.prob_away,
                predicted_outcome=pred.predicted_outcome,
                confidence=pred.confidence,
            ))

    return results


@router.get("/predictions/{match_id}", response_model=PredictionResponse)
async def get_prediction(match_id: int, db: Session = Depends(get_db)):
    """Détail d'un pronostic par ID de match."""
    pred = db.query(Prediction).filter(Prediction.match_id == match_id).first()
    if not pred:
        raise HTTPException(status_code=404, detail="Pronostic non trouvé")

    match = db.query(Match).filter(Match.id == match_id).first()
    return PredictionResponse(
        match_id=match_id,
        match=_build_match_response(match) if match else None,
        prob_home=pred.prob_home,
        prob_draw=pred.prob_draw,
        prob_away=pred.prob_away,
        predicted_outcome=pred.predicted_outcome,
        confidence=pred.confidence,
        model_name=pred.model_name,
        model_version=pred.model_version,
    )


# =========================================================================
# Value Bets
# =========================================================================

@router.get("/value-bets", response_model=List[ValueBetResponse])
async def list_value_bets(
    date: Optional[str] = Query(None),
    min_edge: float = Query(0.02, ge=0.0),
    db: Session = Depends(get_db),
):
    """Liste les value bets détectés."""
    generator = PredictionGenerator()
    detector = ValueBetDetector()
    kelly = KellyCriterion()

    date_str = date or datetime.now().strftime("%Y-%m-%d")
    preds = generator.get_predictions_for_date(db, date_str)

    # Enrichir avec les cotes
    enriched = []
    for p in preds:
        odds = db.query(Odds).filter(Odds.match_id == p["match_id"]).first()
        if odds:
            p["odds_avg_home"] = odds.avg_home
            p["odds_avg_draw"] = odds.avg_draw
            p["odds_avg_away"] = odds.avg_away
        enriched.append(p)

    value_bets = detector.detect(enriched)
    value_bets = [vb for vb in value_bets if vb.edge_pct >= min_edge * 100]

    results = []
    for vb in value_bets:
        match = db.query(Match).filter(Match.id == vb.match_id).first()
        _, stake = kelly.compute(vb.model_prob, vb.market_odd)

        results.append(ValueBetResponse(
            match_id=vb.match_id,
            home_team=match.home_team.name if match and match.home_team else "?",
            away_team=match.away_team.name if match and match.away_team else "?",
            outcome=vb.outcome,
            model_prob=round(vb.model_prob, 4),
            market_odd=vb.market_odd,
            fair_odd=vb.fair_odd,
            edge_pct=vb.edge_pct,
            kelly_stake_pct=round(stake * 100, 2),
            confidence="high" if vb.edge_pct >= 5 else "medium",
        ))

    return results


# =========================================================================
# Portfolio Kelly
# =========================================================================

@router.get("/portfolio", response_model=KellyPortfolioResponse)
async def get_portfolio(
    bankroll: float = Query(1000.0, ge=1),
    date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Calcule l'allocation optimale de portefeuille selon Kelly."""
    generator = PredictionGenerator()
    detector = ValueBetDetector()
    kelly = KellyCriterion()

    date_str = date or datetime.now().strftime("%Y-%m-%d")
    preds = generator.get_predictions_for_date(db, date_str)

    enriched = []
    for p in preds:
        odds = db.query(Odds).filter(Odds.match_id == p["match_id"]).first()
        if odds:
            enriched.append({
                "match_id": p["match_id"],
                "outcome": p["outcome"],
                "model_prob": max(p["prob_home"], p["prob_draw"], p["prob_away"]),
                "market_odd": {"H": odds.avg_home, "D": odds.avg_draw, "A": odds.avg_away}.get(p["outcome"], 0),
            })

    kelly_results = kelly.compute_optimal_stakes(enriched)
    allocation = kelly.allocate_portfolio(kelly_results, total_bankroll=bankroll)

    return KellyPortfolioResponse(**allocation)


# =========================================================================
# Performance & Backtesting
# =========================================================================

@router.get("/performance", response_model=PerformanceResponse)
async def get_performance(db: Session = Depends(get_db)):
    """Métriques de performance globale."""
    total = db.query(Prediction).count()

    from sqlalchemy import func
    avg_brier = db.query(func.avg(Prediction.brier_score)).scalar() or 0

    finished = db.query(Prediction).join(Match).filter(
        Match.status == "finished"
    ).all()

    correct = 0
    for pred in finished:
        match = db.query(Match).filter(Match.id == pred.match_id).first()
        if match:
            actual = "H" if (match.home_score or 0) > (match.away_score or 0) else \
                      "A" if (match.away_score or 0) > (match.home_score or 0) else "D"
            if pred.predicted_outcome == actual:
                correct += 1

    accuracy = correct / len(finished) if finished else None

    return PerformanceResponse(
        total_predictions=total,
        accuracy=round(accuracy, 4) if accuracy else None,
        avg_brier_score=round(avg_brier, 4),
    )


# =========================================================================
# Matchs
# =========================================================================

@router.get("/matches", response_model=List[MatchResponse])
async def list_matches(
    date: Optional[str] = Query(None),
    league_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, pattern="^(scheduled|live|finished)$"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Liste les matchs avec filtres."""
    query = db.query(Match)

    if date:
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        query = query.filter(
            Match.match_date >= date_obj,
            Match.match_date < date_obj.replace(hour=23, minute=59),
        )
    if league_id:
        query = query.filter(Match.league_id == league_id)
    if status:
        query = query.filter(Match.status == status)

    query = query.order_by(Match.match_date.asc()).limit(limit)
    matches = query.all()

    return [_build_match_response(m) for m in matches]


@router.get("/matches/{match_id}", response_model=MatchResponse)
async def get_match(match_id: int, db: Session = Depends(get_db)):
    """Détail d'un match."""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match non trouvé")
    return _build_match_response(match)


# =========================================================================
# Odds
# =========================================================================

@router.get("/odds")
async def get_odds(
    match_id: Optional[int] = Query(None),
    date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Récupère les cotes."""
    if match_id:
        odds = db.query(Odds).filter(Odds.match_id == match_id).first()
        if not odds:
            raise HTTPException(status_code=404)
        return {"match_id": match_id, "odds": odds}
    return {"message": "Spécifiez match_id ou date"}


# =========================================================================
# Helpers
# =========================================================================

def _build_match_response(match: Match) -> MatchResponse:
    """Construit un MatchResponse depuis un ORM Match."""
    return MatchResponse(
        id=match.id,
        home_team=TeamInfo(
            id=match.home_team.id,
            name=match.home_team.name,
            short_code=match.home_team.short_code,
            logo_url=match.home_team.logo_url,
        ) if match.home_team else None,
        away_team=TeamInfo(
            id=match.away_team.id,
            name=match.away_team.name,
            short_code=match.away_team.short_code,
            logo_url=match.away_team.logo_url,
        ) if match.away_team else None,
        league=LeagueInfo(
            id=match.league.id,
            name=match.league.name,
            country=match.league.country,
            season=match.league.season,
        ) if match.league else None,
        match_date=str(match.match_date),
        status=match.status,
        home_score=match.home_score,
        away_score=match.away_score,
        odds=OddsInfo(
            avg_home=match.odds.avg_home,
            avg_draw=match.odds.avg_draw,
            avg_away=match.odds.avg_away,
            bookmaker_count=match.odds.bookmaker_count,
            open_home=match.odds.open_home,
            open_draw=match.odds.open_draw,
            open_away=match.odds.open_away,
            close_home=match.odds.close_home,
            close_draw=match.odds.close_draw,
            close_away=match.odds.close_away,
        ) if match.odds else None,
    )