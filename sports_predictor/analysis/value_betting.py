"""
Détection de Value Bets — compare les probabilités du modèle
avec les cotes implicites du marché pour identifier les opportunités.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from config.settings import config as cfg


@dataclass
class ValueBet:
    """Représente une opportunité de value bet."""
    match_id: int
    outcome: str  # "H", "D", "A"
    model_prob: float
    market_implied_prob: float
    fair_odd: float
    market_odd: float
    edge_pct: float
    bookmaker: Optional[str] = None


class ValueBetDetector:
    """
    Détecteur de Value Bets.
    Un value bet existe quand P_modele > P_marche.
    """

    def __init__(self):
        self.kelly_cfg = cfg.kelly
        self.min_edge = self.kelly_cfg.min_edge

    # =====================================================================
    # Détection
    # =====================================================================

    def detect(
        self,
        predictions: List[Dict],
    ) -> List[ValueBet]:
        """
        Détecte les value bets parmi une liste de pronostics.
        predictions: [{match_id, prob_home, prob_draw, prob_away, odds_avg_home, ...}, ...]
        """
        value_bets = []

        for pred in predictions:
            bet = self._analyze_match(pred)
            if bet:
                value_bets.append(bet)

        value_bets.sort(key=lambda v: v.edge_pct, reverse=True)
        return value_bets

    def detect_from_df(
        self, odds_df: pd.DataFrame, predictions_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Détection par DataFrames (utilisé en production).
        Retourne un DataFrame avec colonnes: edge, is_value, fair_odd.
        """
        results = []

        for idx in range(len(predictions_df)):
            for i, outcome in enumerate(["H", "D", "A"]):
                model_p = predictions_df.iloc[idx, i]
                if i == 0:
                    market_odd = odds_df.iloc[idx].get("avg_home", 0)
                elif i == 1:
                    market_odd = odds_df.iloc[idx].get("avg_draw", 0)
                else:
                    market_odd = odds_df.iloc[idx].get("avg_away", 0)

                if market_odd and model_p and market_odd > 1.0:
                    implied_p = 1.0 / market_odd
                    edge = model_p - implied_p
                    fair_odd = 1.0 / model_p if model_p > 0 else float("inf")

                    results.append({
                        "match_id": odds_df.iloc[idx].get("match_id"),
                        "outcome": outcome,
                        "model_prob": model_p,
                        "implied_prob": implied_p,
                        "market_odd": market_odd,
                        "fair_odd": fair_odd,
                        "edge": edge,
                        "is_value": edge >= self.min_edge,
                    })

        result_df = pd.DataFrame(results)
        return result_df[result_df["is_value"]].sort_values("edge", ascending=False)

    # =====================================================================
    # Analyse
    # =====================================================================

    def _analyze_match(self, pred: Dict) -> Optional[ValueBet]:
        """Analyse un match pour détecter des value bets."""
        outcomes = [
            ("H", pred.get("prob_home", 0), pred.get("odds_avg_home", 0)),
            ("D", pred.get("prob_draw", 0), pred.get("odds_avg_draw", 0)),
            ("A", pred.get("prob_away", 0), pred.get("odds_avg_away", 0)),
        ]

        best_bet = None
        best_edge = 0.0

        for outcome, model_p, market_odd in outcomes:
            if not model_p or not market_odd or market_odd <= 1.0 or model_p <= 0:
                continue

            implied_p = 1.0 / market_odd
            edge = model_p - implied_p

            if edge >= self.min_edge and edge > best_edge:
                fair_odd = 1.0 / model_p
                best_edge = edge
                best_bet = ValueBet(
                    match_id=pred.get("match_id", 0),
                    outcome=outcome,
                    model_prob=model_p,
                    market_implied_prob=implied_p,
                    fair_odd=round(fair_odd, 3),
                    market_odd=market_odd,
                    edge_pct=round(edge * 100, 2),
                )

        return best_bet

    # =====================================================================
    # Métriques de value betting
    # =====================================================================

    def expected_value(self, model_prob: float, market_odd: float) -> float:
        """
        Calcule l'Expected Value (EV) d'un pari.
        EV = P * (cote - 1) - (1 - P) * 1
        """
        return model_prob * (market_odd - 1) - (1 - model_prob)

    def compute_optimal_odd(
        self, model_prob: float, overround: float = 1.08
    ) -> float:
        """
        Calcule la cote minimale pour qu'un pari soit rentable,
        en tenant compte de la marge du bookmaker.
        """
        return (1.0 / model_prob) * overround

    def filter_high_confidence(
        self, value_bets: List[ValueBet], min_confidence: float = 0.35
    ) -> List[ValueBet]:
        """Filtre les value bets avec une probabilité modèle suffisante."""
        return [vb for vb in value_bets if vb.model_prob >= min_confidence]

    # =====================================================================
    # Analyse par ligue
    # =====================================================================

    def league_value_analysis(
        self,
        predictions: List[Dict],
        league_mapping: Dict[int, str],
    ) -> Dict[str, Dict]:
        """
        Analyse les value bets par ligue.
        Retourne: {league_name: {count, avg_edge, top_bets}}
        """
        value_bets = self.detect(predictions)
        analysis = {}

        for vb in value_bets:
            league = league_mapping.get(vb.match_id, "Inconnu")
            if league not in analysis:
                analysis[league] = {"count": 0, "edges": [], "bets": []}
            analysis[league]["count"] += 1
            analysis[league]["edges"].append(vb.edge_pct)
            analysis[league]["bets"].append(vb)

        result = {}
        for league, data in analysis.items():
            result[league] = {
                "value_bet_count": data["count"],
                "avg_edge_pct": round(np.mean(data["edges"]), 2),
                "max_edge_pct": round(max(data["edges"]), 2),
                "top_bet": {
                    "outcome": data["bets"][0].outcome,
                    "fair_odd": data["bets"][0].fair_odd,
                    "market_odd": data["bets"][0].market_odd,
                },
            }

        return result