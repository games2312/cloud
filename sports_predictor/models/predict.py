"""
Générateur de pronostics — applique les modèles entraînés aux matchs à venir.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any
from datetime import datetime

from sqlalchemy.orm import Session
from database.models import Match, Prediction, get_session
from models.feature_engineering import FeatureEngineer
from models.trainer import ModelTrainer
from config.settings import config as cfg


class PredictionGenerator:
    """Génère et persiste les pronostics pour les matchs à venir."""

    def __init__(self):
        self.feature_engineer = FeatureEngineer()
        self.trainer = ModelTrainer()
        self.model_cfg = cfg.model

    # =====================================================================
    # Génération
    # =====================================================================

    def generate_daily(
        self,
        session: Session,
        rf_model: Any,
        xgb_model: Any,
        date_str: Optional[str] = None,
    ) -> List[Dict]:
        """
        Génère les pronostics pour les matchs du jour.
        Combine Random Forest + XGBoost (ensemble).
        """
        features_df, match_ids = self.feature_engineer.build_prediction_dataset(
            session, date_str
        )
        if features_df.empty:
            print("[INFO] Aucun match à prédire.")
            return []

        # Alignement des features
        features = features_df.fillna(0).replace([np.inf, -np.inf], 0)

        predictions = []

        for idx, match_id in enumerate(match_ids):
            row = features.iloc[idx:idx + 1]

            try:
                # Random Forest
                rf_proba = rf_model.predict_proba(row)
                # XGBoost
                xgb_proba = xgb_model.predict_proba(row)

                # Ensemble: moyenne des probas
                ensemble_proba = (rf_proba + xgb_proba) / 2.0

                # Mapping des classes
                if ensemble_proba.shape[1] == 3:
                    prob_h, prob_d, prob_a = ensemble_proba[0]
                elif ensemble_proba.shape[1] == 2:
                    prob_h = ensemble_proba[0, 0]
                    prob_a = ensemble_proba[0, 1]
                    prob_d = 0.0
                else:
                    continue

                outcome = self._best_outcome(prob_h, prob_d, prob_a)
                confidence = max(prob_h, prob_d, prob_a)

                pred = {
                    "match_id": match_id,
                    "prob_home": round(prob_h, 4),
                    "prob_draw": round(prob_d, 4),
                    "prob_away": round(prob_a, 4),
                    "predicted_outcome": outcome,
                    "confidence": round(confidence, 4),
                    "model_name": "RF+XGB_Ensemble",
                    "model_version": "1.0",
                    "created_at": datetime.utcnow(),
                }

                self._save_prediction(session, pred)
                predictions.append(pred)

            except Exception as exc:
                print(f"[WARN] Prédiction échouée match_id={match_id}: {exc}")

        session.commit()
        return predictions

    # =====================================================================
    # Requêtes
    # =====================================================================

    def get_predictions_for_date(
        self, session: Session, date_str: str
    ) -> List[Dict]:
        """Récupère les pronostics stockés pour une date donnée."""
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        preds = (
            session.query(Prediction, Match)
            .join(Match, Prediction.match_id == Match.id)
            .filter(
                Match.match_date >= date_obj,
                Match.match_date < date_obj.replace(hour=23, minute=59),
            )
            .all()
        )

        results = []
        for pred, match in preds:
            results.append({
                "match_id": match.id,
                "home_team": match.home_team.name if match.home_team else "?",
                "away_team": match.away_team.name if match.away_team else "?",
                "match_date": str(match.match_date),
                "prob_home": pred.prob_home,
                "prob_draw": pred.prob_draw,
                "prob_away": pred.prob_away,
                "outcome": pred.predicted_outcome,
                "confidence": pred.confidence,
                "kelly_fraction": pred.kelly_fraction,
                "recommended_stake": pred.recommended_stake_pct,
            })

        return results

    def get_top_predictions(
        self, session: Session, min_confidence: float = 0.5, limit: int = 10
    ) -> List[Dict]:
        """Top pronostics par confiance décroissante."""
        preds = (
            session.query(Prediction)
            .filter(Prediction.confidence >= min_confidence)
            .order_by(Prediction.confidence.desc())
            .limit(limit)
            .all()
        )

        results = []
        for pred in preds:
            match = session.query(Match).filter(Match.id == pred.match_id).first()
            results.append({
                "match_id": pred.match_id,
                "home_team": match.home_team.name if match and match.home_team else "?",
                "away_team": match.away_team.name if match and match.away_team else "?",
                "outcome": pred.predicted_outcome,
                "confidence": pred.confidence,
                "odds": {
                    "home": pred.prob_home,
                    "draw": pred.prob_draw,
                    "away": pred.prob_away,
                },
            })

        return results

    # =====================================================================
    # Helpers
    # =====================================================================

    @staticmethod
    def _best_outcome(ph: float, pd: float, pa: float) -> str:
        """Détermine l'issue la plus probable."""
        best = max(ph, pd, pa)
        if best == ph:
            return "H"
        elif best == pa:
            return "A"
        return "D"

    def _save_prediction(self, session: Session, pred: Dict):
        """Sauvegarde ou met à jour une prédiction en DB."""
        existing = session.query(Prediction).filter(
            Prediction.match_id == pred["match_id"]
        ).first()

        if existing:
            for k, v in pred.items():
                if hasattr(existing, k) and v is not None:
                    setattr(existing, k, v)
        else:
            p = Prediction(**pred)
            session.add(p)