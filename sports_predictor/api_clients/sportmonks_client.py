"""
Client API Sportmonks — données footballistiques complètes (matchs, stats, live).
Documentation : https://docs.sportmonks.com/football
"""

import asyncio
import time
from typing import Optional, List, Dict
import httpx
from config.settings import config as cfg


class SportmonksClient:
    """Wrapper asynchrone autour de l'API Sportmonks v3."""

    BASE_URL = "https://api.sportmonks.com/v3/football"

    def __init__(self):
        self.token = cfg.api_client.sportmonks_api_token
        self.timeout = cfg.api_client.request_timeout
        self._rate_limiter = asyncio.Semaphore(int(cfg.api_client.rate_limit_rps))
        self._last_call = 0.0

    async def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Appel GET authentifié avec rate-limiting."""
        async with self._rate_limiter:
            # Respect du rate limit
            now = time.monotonic()
            wait = (1.0 / cfg.api_client.rate_limit_rps) - (now - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                url = f"{self.BASE_URL}/{endpoint}"
                if params is None:
                    params = {}
                params["api_token"] = self.token

                resp = await client.get(url, params=params)
                self._last_call = time.monotonic()

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 60))
                    await asyncio.sleep(retry_after)
                    return await self._get(endpoint, params)

                resp.raise_for_status()
                return resp.json()

    # ------------------------------------------------------------------
    # Ligues & Équipes
    # ------------------------------------------------------------------

    async def get_leagues(self) -> List[Dict]:
        """Liste toutes les ligues disponibles."""
        data = await self._get("leagues")
        return data.get("data", [])

    async def get_teams_by_league(self, league_id: int) -> List[Dict]:
        """Récupère les équipes d'une ligue."""
        data = await self._get(f"teams/seasons/{league_id}")
        return data.get("data", [])

    async def get_team_by_id(self, team_id: int, includes: str = "") -> Dict:
        """Détail d'une équipe avec relations."""
        params = {}
        if includes:
            params["include"] = includes
        data = await self._get(f"teams/{team_id}", params)
        return data.get("data", {})

    # ------------------------------------------------------------------
    # Matchs & Résultats
    # ------------------------------------------------------------------

    async def get_fixtures_by_date(self, date_str: str, includes: str = "") -> List[Dict]:
        """
        Récupère les matchs d'une date donnée.
        date_str: 'YYYY-MM-DD'
        includes: ex. 'scores;odds;statistics;lineup'
        """
        params = {"filters": f"fixtureDate:{date_str}"}
        if includes:
            params["include"] = includes
        data = await self._get("fixtures/date/{date_str}", params)
        return data.get("data", [])

    async def get_fixtures_by_date_range(
        self, from_date: str, to_date: str, includes: str = ""
    ) -> List[Dict]:
        """Matchs sur une plage de dates."""
        params = {"filters": f"fixtureDateRange:{from_date},{to_date}"}
        if includes:
            params["include"] = includes
        data = await self._get("fixtures/between/{from_date}/{to_date}", params)
        return data.get("data", [])

    async def get_live_scores(self, includes: str = "scores;statistics") -> List[Dict]:
        """Matchs en direct."""
        params = {}
        if includes:
            params["include"] = includes
        data = await self._get("livescores", params)
        return data.get("data", [])

    async def get_fixture_details(self, fixture_id: int) -> Dict:
        """Tous les détails d'un match (stats, scores, lineups, events)."""
        params = {
            "include": "scores;statistics;lineup;events;odds;predictions"
        }
        data = await self._get(f"fixtures/{fixture_id}", params)
        return data.get("data", {})

    # ------------------------------------------------------------------
    # Statistiques & Prédictions
    # ------------------------------------------------------------------

    async def get_fixture_statistics(self, fixture_id: int) -> List[Dict]:
        """Statistiques détaillées d'un match (possession, tirs, xG…)."""
        data = await self._get(f"statistics/fixtures/{fixture_id}")
        return data.get("data", [])

    async def get_predictions(self, fixture_id: int) -> Dict:
        """Prédictions Sportmonks pour un match donné."""
        data = await self._get(f"predictions/fixtures/{fixture_id}")
        return data.get("data", {})

    async def get_head_to_head(self, team1_id: int, team2_id: int) -> List[Dict]:
        """Historique des confrontations directes."""
        params = {"filters": f"headToHead:{team1_id},{team2_id}"}
        data = await self._get("fixtures/head-to-head", params)
        return data.get("data", [])

    # ------------------------------------------------------------------
    # Saisons & Calendrier
    # ------------------------------------------------------------------

    async def get_standings(self, season_id: int) -> List[Dict]:
        """Classement d'une saison."""
        data = await self._get(f"standings/seasons/{season_id}")
        return data.get("data", [])

    async def get_seasons(self, league_id: int) -> List[Dict]:
        """Toutes les saisons d'une ligue."""
        data = await self._get(f"seasons/{league_id}")
        return data.get("data", [])

    # ------------------------------------------------------------------
    # Cotes
    # ------------------------------------------------------------------

    async def get_odds_by_fixture(self, fixture_id: int) -> List[Dict]:
        """Cotes pour un match spécifique."""
        data = await self._get(f"odds/fixtures/{fixture_id}")
        return data.get("data", [])

    async def get_odds_by_date(self, date_str: str) -> List[Dict]:
        """Toutes les cotes pour une date."""
        params = {"filters": f"fixtureDate:{date_str}"}
        data = await self._get("odds/prematch", params)
        return data.get("data", [])