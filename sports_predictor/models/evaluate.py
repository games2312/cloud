"""
Évaluation des modèles de pronostics sportifs.
Métriques : Brier Score, Log Loss, Accuracy, ROC-AUC, Calibration.
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional, Any
from sklearn.metrics import (
    brier_score_loss, log_loss, accuracy_score,
    roc_auc_score, classification_report
)
from sklearn.calibration import calibration_curve
import mlflow

from config.settings import config as cfg


class ModelEvaluator:
    """Évaluation rigoureuse avec métriques adaptées aux paris sportifs."""

    def __init__(self):
        self.model_cfg = cfg.model

    # =====================================================================
    # Métriques principales
    # =====================================================================

    def evaluate(
        self,
        model: Any,
        X_test: pd.DataFrame,
        y_test: pd.DataFrame,
        model_name: str = "model",
    ) -> Dict[str, float]:
        """
        Évaluation complète d'un modèle de prédiction.
        Retourne un dictionnaire de métriques.
        """
        metrics = {}

        try:
            y_proba = model.predict_proba(X_test)
            y_pred = model.predict(X_test)
        except Exception as exc:
            print(f"[ERROR] Predict failed: {exc}")
            return {"error": str(exc)}

        # Conversion multi-class → one-hot si nécessaire
        if y_proba.shape[1] == 3 and y_test.shape[1] == 3:
            pass  # déjà au bon format
        elif y_proba.shape[1] == 2:
            # Binaire → on étend
            y_proba = np.column_stack([y_proba[:, 0], 1 - y_proba.sum(axis=1), y_proba[:, 1]])

        y_test_np = y_test.values if hasattr(y_test, "values") else np.array(y_test)

        # --- Brier Score (métrique reine pour les probas) ---
        metrics["brier_score"] = self.brier_score_multiclass(y_test_np, y_proba)

        # --- Log Loss ---
        try:
            metrics["log_loss"] = log_loss(y_test_np, y_proba)
        except Exception:
            metrics["log_loss"] = None

        # --- Accuracy ---
        y_test_labels = np.argmax(y_test_np, axis=1) if y_test_np.ndim > 1 else y_test_np
        y_pred_labels = y_pred if y_pred.ndim == 1 else np.argmax(y_pred, axis=1)
        try:
            metrics["accuracy"] = accuracy_score(y_test_labels, y_pred_labels)
        except Exception:
            metrics["accuracy"] = None

        # --- Per-class Brier ---
        for i, label in enumerate(["home", "draw", "away"]):
            if i < y_proba.shape[1]:
                try:
                    metrics[f"brier_{label}"] = brier_score_loss(
                        y_test_np[:, i], y_proba[:, i]
                    )
                except Exception:
                    metrics[f"brier_{label}"] = None

        # --- Calibration ---
        try:
            calib = self.calibration_metrics(y_test_np, y_proba)
            metrics.update(calib)
        except Exception:
            pass

        # --- Classification report ---
        labels_map = {0: "home", 1: "draw", 2: "away"}
        try:
            report = classification_report(
                y_test_labels, y_pred_labels,
                target_names=[labels_map.get(i, str(i))
                              for i in range(max(len(labels_map), y_proba.shape[1]))],
                output_dict=True,
                zero_division=0,
            )
            metrics["classification_report"] = report
        except Exception:
            pass

        # Log dans MLflow
        with mlflow.start_run(run_name=f"eval_{model_name}", nested=True):
            mlflow.log_metrics({k: v for k, v in metrics.items()
                                if isinstance(v, (int, float)) and v is not None})

        return metrics

    # =====================================================================
    # Helpers
    # =====================================================================

    @staticmethod
    def brier_score_multiclass(y_true: np.ndarray, y_proba: np.ndarray) -> float:
        """
        Brier Score pour classification multi-classe.
        BS = (1/N) * sum_i sum_k (p_ik - y_ik)^2
        """
        if y_true.ndim == 1:
            # One-hot encode
            n_classes = y_proba.shape[1]
            y_true_oh = np.eye(n_classes)[y_true.astype(int)]
        else:
            y_true_oh = y_true

        return np.mean(np.sum((y_proba - y_true_oh) ** 2, axis=1))

    @staticmethod
    def calibration_metrics(
        y_true: np.ndarray, y_proba: np.ndarray
    ) -> Dict[str, float]:
        """
        Calcule l'Expected Calibration Error (ECE) par classe.
        ECE mesure l'écart entre confiance et précision réelle.
        """
        n_bins = 10
        if y_true.ndim > 1:
            y_labels = np.argmax(y_true, axis=1)
        else:
            y_labels = y_true

        ece_total = 0.0
        n_samples = len(y_labels)

        for k in range(y_proba.shape[1]):
            prob_k = y_proba[:, k]
            bin_boundaries = np.linspace(0, 1, n_bins + 1)
            ece_k = 0.0

            for i in range(n_bins):
                mask = (prob_k > bin_boundaries[i]) & (prob_k <= bin_boundaries[i + 1])
                if mask.sum() == 0:
                    continue
                bin_acc = np.mean(y_labels[mask] == k)
                bin_conf = np.mean(prob_k[mask])
                ece_k += (mask.sum() / n_samples) * abs(bin_acc - bin_conf)

            ece_total += ece_k / y_proba.shape[1]

        return {"ece": round(ece_total, 4)}

    # =====================================================================
    # Comparaison de modèles
    # =====================================================================

    def compare_models(
        self,
        models_results: Dict[str, Dict[str, float]],
    ) -> pd.DataFrame:
        """
        Compare plusieurs modèles sur leurs métriques clés.
        models_results: {model_name: {metric: value, ...}}
        """
        rows = []
        for name, metrics in models_results.items():
            rows.append({"model": name, **metrics})

        df = pd.DataFrame(rows)
        # Trier par Brier Score (plus bas = meilleur)
        if "brier_score" in df.columns:
            df = df.sort_values("brier_score")
        return df

    # =====================================================================
    # Backtest historique
    # =====================================================================

    def backtest_profitability(
        self,
        predictions: pd.DataFrame,
        actual_outcomes: pd.DataFrame,
        odds: pd.DataFrame,
        stake_pct: float = 0.02,
    ) -> Dict:
        """
        Simule la profitabilité d'une stratégie de paris sur données historiques.
        predictions: DataFrame avec probas
        actual_outcomes: résultats réels
        odds: cotes disponibles
        stake_pct: % de bankroll misé par pari

        Retourne: ROI, profit total, win rate, drawdown max
        """
        bankroll = 1000.0
        bankroll_history = [bankroll]
        wins, losses = 0, 0
        total_bets = 0

        for i in range(len(predictions)):
            stake = bankroll * stake_pct
            pred_outcome = predictions.iloc[i].idxmax()  # outcome le plus probable
            actual = actual_outcomes.iloc[i].idxmax()

            if pred_outcome == actual:
                # Gain
                odd = odds.iloc[i][pred_outcome]
                profit = stake * (odd - 1)
                bankroll += profit
                wins += 1
            else:
                bankroll -= stake
                losses += 1

            total_bets += 1
            bankroll_history.append(bankroll)

        roi = (bankroll - 1000) / 1000
        win_rate = wins / total_bets if total_bets > 0 else 0
        drawdown = self._max_drawdown(bankroll_history)

        return {
            "initial_bankroll": 1000.0,
            "final_bankroll": round(bankroll, 2),
            "roi": round(roi * 100, 2),
            "win_rate": round(win_rate * 100, 2),
            "total_bets": total_bets,
            "max_drawdown_pct": round(drawdown * 100, 2),
        }

    @staticmethod
    def _max_drawdown(history: list) -> float:
        """Calcule le drawdown maximal en pourcentage."""
        peak = history[0]
        max_dd = 0.0
        for val in history:
            if val > peak:
                peak = val
            dd = (peak - val) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd