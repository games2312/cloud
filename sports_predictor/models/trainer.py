"""
Entraînement des modèles de prédiction sportive.
Supporte Random Forest, XGBoost avec MLflow tracking et walk-forward validation.
"""

import os
import pickle
from datetime import datetime
from typing import Dict, Tuple, Optional, Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit
import xgboost as xgb
import mlflow
import mlflow.sklearn
import mlflow.xgboost

from config.settings import config as cfg
from models.feature_engineering import FeatureEngineer


class ModelTrainer:
    """Pipeline d'entraînement avec MLflow tracking."""

    def __init__(self):
        self.model_cfg = cfg.model
        mlflow.set_tracking_uri(self.model_cfg.mlflow_tracking_uri)
        mlflow.set_experiment("sports_predictor")
        self.feature_engineer = FeatureEngineer()

    # =====================================================================
    # Random Forest
    # =====================================================================

    def train_random_forest(
        self,
        X: pd.DataFrame,
        y: pd.DataFrame,
        use_walk_forward: bool = True,
    ) -> Tuple[RandomForestClassifier, Dict[str, float]]:
        """
        Entraîne un Random Forest avec walk-forward validation.
        Retourne: (modèle entraîné, métriques moyennes)
        """
        model = RandomForestClassifier(
            n_estimators=self.model_cfg.random_forest_n_estimators,
            max_depth=self.model_cfg.xgboost_max_depth,
            random_state=42,
            n_jobs=-1,
            class_weight="balanced_subsample",
        )
        params = model.get_params()

        with mlflow.start_run(run_name=f"RF_{datetime.now():%Y%m%d_%H%M}"):
            mlflow.log_params({f"rf_{k}": v for k, v in params.items()})

            if use_walk_forward:
                metrics = self._walk_forward_train(model, X, y, "rf")
            else:
                model.fit(X, y)
                metrics = {"train_completed": 1.0}

            # Log model
            mlflow.sklearn.log_model(model, "random_forest")
            mlflow.log_metrics(metrics)

        return model, metrics

    # =====================================================================
    # XGBoost (multi-output pour H/D/A)
    # =====================================================================

    def train_xgboost(
        self,
        X: pd.DataFrame,
        y: pd.DataFrame,
        use_walk_forward: bool = True,
    ) -> Tuple[Any, Dict[str, float]]:
        """
        Entraîne un XGBoost multi-class (H / D / A).
        Walk-forward validation pour robustesse temporelle.
        """
        # Conversion en labels multi-class: 0=H, 1=D, 2=A
        if y.shape[1] == 3:
            y_labels = np.argmax(y.values, axis=1)
        else:
            y_labels = y.values.ravel()

        params = {
            "n_estimators": self.model_cfg.xgboost_n_estimators,
            "max_depth": self.model_cfg.xgboost_max_depth,
            "learning_rate": self.model_cfg.xgboost_learning_rate,
            "objective": "multi:softprob",
            "num_class": 3,
            "eval_metric": "mlogloss",
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "random_state": 42,
            "n_jobs": -1,
        }

        with mlflow.start_run(run_name=f"XGB_{datetime.now():%Y%m%d_%H%M}"):
            mlflow.log_params({f"xgb_{k}": v for k, v in params.items()})

            if use_walk_forward:
                metrics = self._walk_forward_xgb(X, y_labels, params)
            else:
                model = xgb.XGBClassifier(**params)
                model.fit(X, y_labels)
                metrics = {"train_completed": 1.0}
                mlflow.xgboost.log_model(model, "xgboost")

            mlflow.log_metrics(metrics)

            # Re-train complet pour le modèle final
            final_model = xgb.XGBClassifier(**params)
            final_model.fit(X, y_labels)
            mlflow.xgboost.log_model(final_model, "xgboost_final")

        return final_model, metrics

    # =====================================================================
    # Walk-Forward Validation (validation temporelle)
    # =====================================================================

    def _walk_forward_train(
        self, model: Any, X: pd.DataFrame, y: pd.DataFrame, model_name: str
    ) -> Dict[str, float]:
        """
        Walk-forward validation: entraîne sur les données passées,
        teste sur la période suivante. Évite l'overfitting temporel.
        """
        n_splits = min(self.model_cfg.walk_forward_windows, len(X) // 100 + 2)
        tscv = TimeSeriesSplit(n_splits=max(2, n_splits))

        from sklearn.metrics import accuracy_score, log_loss

        accuracies, loglosses = [], []

        for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
            X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
            y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

            if len(X_test) < 5:
                continue

            model_clone = model.__class__(**model.get_params())
            model_clone.fit(X_train, y_train)

            try:
                y_pred_proba = model_clone.predict_proba(X_test)
                y_pred = model_clone.predict(X_test)
                acc = accuracy_score(y_test, y_pred)
                ll = log_loss(y_test, y_pred_proba)

                accuracies.append(acc)
                loglosses.append(ll)

                mlflow.log_metric(f"{model_name}_fold_{fold}_accuracy", acc)
                mlflow.log_metric(f"{model_name}_fold_{fold}_logloss", ll)
            except Exception as exc:
                print(f"[WARN] Fold {fold} eval failed: {exc}")

        metrics = {
            f"{model_name}_cv_accuracy_mean": np.mean(accuracies) if accuracies else 0,
            f"{model_name}_cv_accuracy_std": np.std(accuracies) if accuracies else 0,
            f"{model_name}_cv_logloss_mean": np.mean(loglosses) if loglosses else 0,
        }
        return metrics

    def _walk_forward_xgb(
        self, X: pd.DataFrame, y_labels: np.ndarray, params: Dict
    ) -> Dict[str, float]:
        """Walk-forward spécifique XGBoost."""
        n_splits = min(self.model_cfg.walk_forward_windows, len(X) // 100 + 2)
        tscv = TimeSeriesSplit(n_splits=max(2, n_splits))

        from sklearn.metrics import accuracy_score, log_loss

        accuracies, loglosses = [], []

        for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
            X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
            y_train, y_test = y_labels[train_idx], y_labels[test_idx]

            if len(X_test) < 5:
                continue

            model = xgb.XGBClassifier(**params)
            model.fit(X_train, y_train, verbose=False)

            try:
                y_pred_proba = model.predict_proba(X_test)
                y_pred = model.predict(X_test)
                accuracies.append(accuracy_score(y_test, y_pred))
                loglosses.append(log_loss(y_test, y_pred_proba))
            except Exception as exc:
                print(f"[WARN] XGB fold {fold} eval failed: {exc}")

        return {
            "xgb_cv_accuracy_mean": np.mean(accuracies) if accuracies else 0,
            "xgb_cv_accuracy_std": np.std(accuracies) if accuracies else 0,
            "xgb_cv_logloss_mean": np.mean(loglosses) if loglosses else 0,
        }

    # =====================================================================
    # Sauvegarde / Chargement
    # =====================================================================

    def save_model(self, model: Any, filepath: str):
        """Sauvegarde le modèle sur disque."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "wb") as f:
            pickle.dump(model, f)

    def load_model(self, filepath: str) -> Any:
        """Charge un modèle sauvegardé."""
        with open(filepath, "rb") as f:
            return pickle.load(f)