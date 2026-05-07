"""
Feature Engineering pour les modèles de pronostics sportifs.
Transforme les données brutes du warehouse en features exploitables
pour Random Forest, XGBoost et LightGBM.

Catégories de features:
- Structurelles: home/away, date, compétition
- Performances: forme récente (5 matchs), possession, tirs
- Contexte: H2H, avantage domicile
- Marché: cotes implicites, mouvements de cotes
- Avancées: xG, métriques dérivées
"""

import numpy as np
import pandas as pd
from typing import Tuple, Optional, List
from datetime import datetime

from sqlalchemy.orm import Session
from database.models import Match, Odds, Team, League
from config.settings import config as cfg


class FeatureEngineer:
    """Pipeline de feature engineering pour les pronostics sportifs."""

    def __init__(self):
        self.model_cfg = cfg.model

    # =====================================================================
    # Construction du dataset d'entraînement complet
    # =====================================================================

    def build_training_dataset(
        self, session: Session, league_id: Optional[int] = None
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Extrait et prépare le dataset complet pour l'entraînement.
        Retourne: (features_df, targets_df)
        """
        # 1. Requête des matchs terminés avec leurs cotes
        query = session.query(Match).filter(Match.status == "finished")
        if league_id:
            query = query.filter(Match.league_id == league_id)
        matches = query.order_by(Match.match_date.asc()).all()

        if not matches:
            raise ValueError("Aucun match terminé trouvé dans la base")

        rows = []
        for match in matches:
            # Données de base
            row = self._extract_match_features(match)
            if row:
                rows.append(row)

        df = pd.DataFrame(rows)
        if df.empty:
            raise ValueError("Aucune feature extraite des matchs")

        # 2. Features de forme récente (par équipe)
        df = self._add_form_features(df)

        # 3. Features de cotes implicites
        df = self._add_odds_features(df)

        # 4. Features contextuelles
        df = self._add_contextual_features(df)

        # 5. Features dérivées (ratios, différentiels)
        df = self._add_derived_features(df)

        # 6. Séparation features / targets
        target_cols = self.model_cfg.target_columns
        feature_cols = [c for c in df.columns if c not in target_cols + ["match_id", "match_date"]]

        # Nettoyage final
        features = df[feature_cols].copy()
        features = features.replace([np.inf, -np.inf], np.nan)
        features = features.fillna(0)

        # Targets: one-hot encoding du résultat
        targets = df[target_cols].copy()
        targets = targets.fillna(0).astype(float)

        return features, targets

    # =====================================================================
    # Extracteurs de features par catégorie
    # =====================================================================

    def _extract_match_features(self, match: Match) -> Optional[Dict]:
        """Extrait les features de base d'un match."""
        if not match.home_team or not match.away_team:
            return None

        odds = match.odds
        row = {
            "match_id": match.id,
            "match_date": match.match_date,
            "league_id": match.league_id,
            "home_team_id": match.home_team_id,
            "away_team_id": match.away_team_id,

            # Résultat (target)
            "home_win": 1 if (match.home_score or 0) > (match.away_score or 0) else 0,
            "draw": 1 if match.home_score == match.away_score else 0,
            "away_win": 1 if (match.away_score or 0) > (match.home_score or 0) else 0,

            # Stats de match (si disponibles)
            "home_possession": match.home_possession,
            "away_possession": match.away_possession,
            "home_shots": match.home_shots,
            "away_shots": match.away_shots,
            "home_shots_on_target": match.home_shots_on,
            "away_shots_on_target": match.away_shots_on,
            "home_corners": match.home_corners,
            "away_corners": match.away_corners,
            "home_xg": match.home_xg,
            "away_xg": match.away_xg,
        }

        # Cotes (si disponibles)
        if odds:
            row.update({
                "odds_avg_home": odds.avg_home,
                "odds_avg_draw": odds.avg_draw,
                "odds_avg_away": odds.avg_away,
                "odds_open_home": odds.open_home,
                "odds_open_draw": odds.open_draw,
                "odds_open_away": odds.open_away,
                "odds_close_home": odds.close_home,
                "odds_close_draw": odds.close_draw,
                "odds_close_away": odds.close_away,
                "bookmaker_count": odds.bookmaker_count,
            })

        return row

    def _add_form_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Ajoute les features de forme récente (rolling 5 matchs).
        Calcule pour chaque équipe: points, buts marqués/encaissés,
        clean sheets, win rate sur les 5 derniers matchs.
        """
        df = df.sort_values("match_date").copy()

        # Fonction générique pour calculer la forme d'une équipe
        def compute_team_form(group_df: pd.DataFrame, team_col: str) -> pd.DataFrame:
            group_df = group_df.sort_values("match_date")
            is_home = group_df["home_team_id"] == group_df[team_col].iloc[0] if len(group_df) > 0 else pd.Series([])

            # Points gagnés
            group_df["pts"] = np.where(
                is_home & (group_df["home_win"] == 1), 3,
                np.where(~is_home & (group_df["away_win"] == 1), 3,
                np.where(group_df["draw"] == 1, 1, 0))
            )
            group_df["gf"] = np.where(is_home, group_df.get("home_score_actual", group_df.get("home_xg", 0)),
                                      group_df.get("away_score_actual", group_df.get("away_xg", 0)))
            group_df["ga"] = np.where(is_home, group_df.get("away_score_actual", group_df.get("away_xg", 0)),
                                      group_df.get("home_score_actual", group_df.get("home_xg", 0)))

            for w in [3, 5, 10]:
                group_df[f"form_pts_{w}"] = group_df["pts"].rolling(w, min_periods=1).sum().shift(1)
                group_df[f"form_gf_{w}"] = group_df["gf"].rolling(w, min_periods=1).sum().shift(1)
                group_df[f"form_ga_{w}"] = group_df["ga"].rolling(w, min_periods=1).sum().shift(1)
                group_df[f"form_winrate_{w}"] = (
                    group_df["pts"].rolling(w, min_periods=1).sum().shift(1) / (w * 3)
                )

            return group_df

        # Appliquer par équipe
        teams = pd.concat([df["home_team_id"], df["away_team_id"]]).unique()
        form_dfs = []
        for team_id in teams:
            team_matches = df[
                (df["home_team_id"] == team_id) | (df["away_team_id"] == team_id)
            ].copy()
            team_matches["team"] = team_id
            form_dfs.append(compute_team_form(team_matches, "team"))

        if form_dfs:
            all_forms = pd.concat(form_dfs, ignore_index=True)
            # Merge back: home form + away form
            for w in [3, 5, 10]:
                home_form = all_forms[["match_id", f"form_pts_{w}", f"form_gf_{w}", f"form_winrate_{w}"]].rename(
                    columns={c: f"home_{c}" for c in [f"form_pts_{w}", f"form_gf_{w}", f"form_winrate_{w}"]}
                )
                df = df.merge(home_form, on="match_id", how="left")

        return df

    def _add_odds_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Features dérivées des cotes:
        - Probabilités implicites
        - Marge du bookmaker (overround)
        - Mouvement opening → closing
        """
        if "odds_avg_home" not in df.columns:
            return df

        # Probabilités implicites (avant correction de la marge)
        df["implied_home"] = 1.0 / df["odds_avg_home"].replace(0, np.nan)
        df["implied_draw"] = 1.0 / df["odds_avg_draw"].replace(0, np.nan)
        df["implied_away"] = 1.0 / df["odds_avg_away"].replace(0, np.nan)

        # Overround (marge bookmaker)
        df["overround"] = df["implied_home"] + df["implied_draw"] + df["implied_away"]

        # Probabilités corrigées (normalisées)
        df["prob_home_market"] = df["implied_home"] / df["overround"]
        df["prob_draw_market"] = df["implied_draw"] / df["overround"]
        df["prob_away_market"] = df["implied_away"] / df["overround"]

        # Mouvement de cotes (steam move)
        if all(c in df.columns for c in ["odds_open_home", "odds_close_home"]):
            df["steam_home"] = (df["odds_open_home"] - df["odds_close_home"]) / df["odds_open_home"].replace(0, np.nan)
            df["steam_away"] = (df["odds_open_away"] - df["odds_close_away"]) / df["odds_open_away"].replace(0, np.nan)

        df = df.drop(columns=["implied_home", "implied_draw", "implied_away"], errors="ignore")
        return df

    def _add_contextual_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Features contextuelles:
        - Jour de la semaine
        - Heure du match
        - Mois (effet calendrier)
        """
        if "match_date" in df.columns:
            df["match_date"] = pd.to_datetime(df["match_date"])
            df["day_of_week"] = df["match_date"].dt.dayofweek
            df["hour"] = df["match_date"].dt.hour.fillna(15).astype(int)
            df["month"] = df["match_date"].dt.month
            df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)
            df["is_evening"] = (df["hour"] >= 18).astype(int)

        return df

    def _add_derived_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Features dérivées composites:
        - Ratios offensifs / défensifs
        - Différentiels
        - Interactions
        """
        # Différence de forme
        for w in [5]:
            h_col = f"home_form_pts_{w}"
            a_col = f"away_form_pts_{w}"  # forme de l'équipe away (si dispo)
            if h_col in df.columns:
                df[f"form_diff_{w}"] = df[h_col] - df.get(a_col, df[h_col].mean())

        # Ratios si les stats sont disponibles
        if "home_shots_on_target" in df.columns and "home_shots" in df.columns:
            df["home_shot_accuracy"] = np.where(
                df["home_shots"] > 0,
                df["home_shots_on_target"] / df["home_shots"],
                0
            )
        if "away_shots_on_target" in df.columns and "away_shots" in df.columns:
            df["away_shot_accuracy"] = np.where(
                df["away_shots"] > 0,
                df["away_shots_on_target"] / df["away_shots"],
                0
            )

        # Avantage domicile (baseline)
        if "home_win" in df.columns:
            df["home_advantage"] = 1  # feature constante, le modèle apprendra le poids

        # Différence xG (si dispo)
        if "home_xg" in df.columns and "away_xg" in df.columns:
            df["xg_diff"] = df["home_xg"] - df["away_xg"]

        return df

    # =====================================================================
    # Construction du dataset de prédiction (matchs à venir)
    # =====================================================================

    def build_prediction_dataset(
        self, session: Session, date_str: Optional[str] = None
    ) -> Tuple[pd.DataFrame, List[int]]:
        """
        Prépare les features pour les matchs à venir (prédiction).
        Retourne: (features_df, match_ids)
        """
        query = session.query(Match).filter(
            Match.status.in_(["scheduled", "live"])
        )
        if date_str:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            query = query.filter(
                Match.match_date >= date_obj,
                Match.match_date < date_obj.replace(hour=23, minute=59),
            )

        upcoming = query.order_by(Match.match_date.asc()).all()

        rows = []
        match_ids = []
        for match in upcoming:
            row = self._extract_match_features(match)
            if row:
                rows.append(row)
                match_ids.append(match.id)

        if not rows:
            return pd.DataFrame(), []

        df = pd.DataFrame(rows)
        df = self._add_odds_features(df)
        df = self._add_contextual_features(df)
        df = self._add_derived_features(df)

        # Alignement avec les colonnes d'entraînement
        feature_cols = [c for c in df.columns
                        if c not in self.model_cfg.target_columns + ["match_id", "match_date"]]
        features = df[feature_cols].fillna(0)

        return features, match_ids