"""
Kelly Criterion — gestion optimale de bankroll pour les paris sportifs.
Implémente le Full Kelly, Fractional Kelly et des stratégies conservatrices.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from config.settings import config as cfg


@dataclass
class KellyResult:
    """Résultat du calcul Kelly pour un pari."""
    match_id: int
    outcome: str
    model_prob: float
    market_odd: float
    fraction: float         # Fraction Kelly recommandée (0 = pas de pari)
    stake_pct: float        # % de bankroll à miser
    bankroll_impact: float  # EV du pari
    confidence: str         # "high" | "medium" | "low"


class KellyCriterion:
    """
    Implémentation du Kelly Criterion pour les paris sportifs.

    Formule: f* = (p * b - q) / b
    où: p = probabilité estimée, q = 1-p, b = cote - 1
    """

    def __init__(self):
        self.kelly_cfg = cfg.kelly
        self.fractional_kelly = self.kelly_cfg.fractional_kelly
        self.max_stake_pct = self.kelly_cfg.max_stake_pct

    # =====================================================================
    # Calcul principal
    # =====================================================================

    def compute(
        self,
        model_prob: float,
        market_odd: float,
    ) -> Tuple[float, float]:
        """
        Calcule la fraction Kelly optimale.
        Retourne: (full_kelly_fraction, fractional_kelly_fraction)

        Si full_kelly <= 0 → pas de pari avantageux.
        """
        if model_prob <= 0 or market_odd <= 1.0:
            return 0.0, 0.0

        q = 1.0 - model_prob
        b = market_odd - 1.0  # cote nette

        # Full Kelly
        f_star = (model_prob * b - q) / b

        # Fractional Kelly
        f_frac = f_star * self.fractional_kelly

        # Plafonnement
        f_frac = min(f_frac, self.max_stake_pct)
        f_frac = max(f_frac, 0.0)

        return f_star, f_frac

    def compute_optimal_stakes(
        self,
        value_bets: List[Dict],
    ) -> List[KellyResult]:
        """
        Calcule les mises optimales pour une liste de value bets.
        value_bets: liste de dicts avec match_id, outcome, model_prob, market_odd
        """
        results = []

        for vb in value_bets:
            full, frac = self.compute(
                vb.get("model_prob", 0),
                vb.get("market_odd", 0),
            )

            ev = self.expected_value(vb.get("model_prob", 0), vb.get("market_odd", 0))

            confidence = "low"
            if frac >= 0.02:
                confidence = "high"
            elif frac >= 0.01:
                confidence = "medium"

            results.append(KellyResult(
                match_id=vb.get("match_id", 0),
                outcome=vb.get("outcome", "?"),
                model_prob=vb.get("model_prob", 0),
                market_odd=vb.get("market_odd", 0),
                fraction=round(frac, 4),
                stake_pct=round(frac * 100, 2),
                bankroll_impact=round(ev, 4),
                confidence=confidence,
            ))

        results.sort(key=lambda r: r.fraction, reverse=True)
        return results

    # =====================================================================
    # Gestion de portefeuille
    # =====================================================================

    def allocate_portfolio(
        self,
        bets: List[KellyResult],
        total_bankroll: float = 1000.0,
        max_exposure_pct: float = 0.25,
    ) -> Dict:
        """
        Alloue le capital entre plusieurs paris simultanés.
        Respecte une exposition maximale totale.
        """
        total_raw = sum(b.fraction for b in bets)

        if total_raw <= 0:
            return {"bets": [], "total_stake": 0, "remaining": total_bankroll}

        # Normalisation si l'exposition dépasse le max
        scale = 1.0
        if total_raw > max_exposure_pct:
            scale = max_exposure_pct / total_raw

        allocations = []
        total_stake = 0.0

        for bet in bets:
            adjusted_fraction = bet.fraction * scale
            stake_amount = total_bankroll * adjusted_fraction
            total_stake += stake_amount
            allocations.append({
                "match_id": bet.match_id,
                "outcome": bet.outcome,
                "stake_amount": round(stake_amount, 2),
                "stake_pct": round(adjusted_fraction * 100, 2),
                "confidence": bet.confidence,
            })

        # Trier par confiance
        allocations.sort(
            key=lambda a: {"high": 0, "medium": 1, "low": 2}[a["confidence"]]
        )

        return {
            "bets": allocations,
            "total_stake": round(total_stake, 2),
            "total_exposure_pct": round(total_stake / total_bankroll * 100, 2),
            "remaining_bankroll": round(total_bankroll - total_stake, 2),
        }

    # =====================================================================
    # Utilitaires
    # =====================================================================

    @staticmethod
    def expected_value(prob: float, odd: float) -> float:
        """Expected Value d'un pari: EV = p * (c-1) - (1-p)."""
        if prob <= 0 or odd <= 0:
            return 0.0
        return prob * (odd - 1.0) - (1.0 - prob)

    @staticmethod
    def probability_from_odd(odd: float, margin: float = 0.06) -> float:
        """Convertit une cote en probabilité implicite (avec marge estimée)."""
        if odd <= 0:
            return 0.0
        return (1.0 / odd) * (1.0 - margin)

    def conservative_strategy(
        self,
        model_prob: float,
        market_odd: float,
    ) -> Dict:
        """
        Stratégie conservatrice: ne parie que si l'avantage est significatif.
        Combine Fractional Kelly + seuils de confiance.
        """
        _, frac = self.compute(model_prob, market_odd)
        ev = self.expected_value(model_prob, market_odd)

        should_bet = (
            frac >= 0.005                 # au moins 0.5% de bankroll
            and ev > 0.01                  # EV positif
            and model_prob >= 0.30        # probabilité > 30%
            and market_odd >= 1.50        # cote > 1.50
        )

        return {
            "should_bet": should_bet,
            "fractional_kelly": round(frac, 4),
            "stake_pct": round(frac * 100, 2) if should_bet else 0,
            "expected_value": round(ev, 4),
            "reason": self._explain_decision(model_prob, market_odd, frac, ev),
        }

    def _explain_decision(
        self, prob: float, odd: float, frac: float, ev: float
    ) -> str:
        """Génère une explication textuelle de la décision."""
        reasons = []
        if frac < 0.005:
            reasons.append("fraction Kelly trop faible")
        if ev <= 0.01:
            reasons.append("EV insuffisant")
        if prob < 0.30:
            reasons.append("probabilité modèle trop basse")
        if odd < 1.50:
            reasons.append("cote trop basse")
        if not reasons:
            return "Pari recommandé : avantage détecté"
        return "Pari déconseillé : " + ", ".join(reasons)

    # =====================================================================
    # Suivi de performance
    # =====================================================================

    def simulate_bankroll(
        self,
        bets_history: List[Dict],
        initial_bankroll: float = 1000.0,
    ) -> pd.DataFrame:
        """
        Simule l'évolution d'une bankroll sur un historique de paris.
        bets_history: [{stake, odd, won}, ...]
        Retourne un DataFrame avec la courbe de bankroll.
        """
        bankroll = initial_bankroll
        history = [{"bet_num": 0, "bankroll": bankroll}]

        for i, bet in enumerate(bets_history, 1):
            stake = bet.get("stake", 0)
            odd = bet.get("odd", 1)
            won = bet.get("won", False)

            if won:
                bankroll += stake * (odd - 1)
            else:
                bankroll -= stake

            history.append({"bet_num": i, "bankroll": round(bankroll, 2)})

        df = pd.DataFrame(history)
        df["return_pct"] = (df["bankroll"] / initial_bankroll - 1) * 100
        return df

    def performance_summary(self, history_df: pd.DataFrame) -> Dict:
        """Résumé de performance à partir de l'historique simulé."""
        if history_df.empty:
            return {"error": "No data"}

        initial = history_df["bankroll"].iloc[0]
        final = history_df["bankroll"].iloc[-1]
        peak = history_df["bankroll"].max()

        return {
            "initial_bankroll": initial,
            "final_bankroll": final,
            "total_return_pct": round((final / initial - 1) * 100, 2),
            "peak_bankroll": peak,
            "max_drawdown_pct": round(
                (1 - history_df["bankroll"].min() / peak) * 100, 2
            ),
        }