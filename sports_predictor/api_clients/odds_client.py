"""
Client pour The Odds API — cotes multi-bookmaker en temps réel.
Documentation : https://the-odds-api.com/liveapi/guides/v4/
"""

import asyncio
import time
from typing import Optional, List, Dict
import httpx
from config.settings import config as cfg


class OddsAPIClient:
    """Wrapper asynchrone pour The Odds API v4."""

    BASE_URL = "https://api.the-odds-api.com/v4"

    def __init__(self):
        self.api_key = cfg.api_client.odds_api_key
        self.timeout = cfg.api_client.request_timeout
        self._rate_limiter = asyncio.Semaphore(int(cfg.api_client.rate_limit_rps))
        self._last_call = 0.0

    async def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """GET authentifié avec rate-limiting intégré."""
        async with self._rate_limiter:
            now = time.monotonic()
            wait = (1.0 / cfg.api_client.rate_limit_rps) - (now - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                url = f"{self.BASE_URL}/{endpoint}"
                if params is None:
                    params = {}
                params["apiKey"] = self.api_key

                resp = await client.get(url, params=params)
                self._last_call = time.monotonic()

                if resp.status_code in (401, 403):
                    print("[ERROR] Clé API The Odds invalide ou expirée.")
                    return {"data": [], "remaining": 0}
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 60))
                    await asyncio.sleep(retry_after)
                    return await self._get(endpoint, params)

                resp.raise_for_status()
                result = resp.json()

                # Logger le quota restant
                remaining = resp.headers.get("x-requests-remaining", "?")
                if int(remaining.split("-")[-1]) < 5 if "-" in str(remaining) else False:
                    print(f"[WARN] Quota The Odds API bas : {remaining}")

                return result

    # ------------------------------------------------------------------
    # Sports et ligues
    # ------------------------------------------------------------------

    async def get_sports(self) -> List[Dict]:
        """Liste tous les sports disponibles."""
        return await self._get("sports")

    # ------------------------------------------------------------------
    # Cotes
    # ------------------------------------------------------------------

    async def get_odds(
        self,
        sport_key: str,
        regions: str = "eu",
        markets: str = "h2h",
        odds_format: str = "decimal",
        date_format: str = "iso",
    ) -> Dict:
        """
        Récupère les cotes pour un sport.
        sport_key: ex. 'soccer_france_ligue_one'
        regions: 'eu', 'uk', 'us', 'au'
        markets: 'h2h' (1X2), 'totals', 'spreads'
        """
        params = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format,
            "dateFormat": date_format,
        }
        return await self._get(f"sports/{sport_key}/odds", params)

    async def get_odds_h2h(self, sport_key: str) -> List[Dict]:
        """Cotes 1X2 uniquement, format simplifié pour l'analyse."""
        data = await self.get_odds(sport_key, markets="h2h")
        matches = data if isinstance(data, list) else data.get("data", [])

        simplified = []
        for match in matches:
            bookmakers = match.get("bookmakers", [])
            odds_list = []
            for bm in bookmakers:
                markets = bm.get("markets", [])
                for mkt in markets:
                    outcomes = mkt.get("outcomes", [])
                    if len(outcomes) >= 3:
                        odds_list.append({
                            "bookmaker": bm.get("title"),
                            "home": outcomes[0].get("price"),
                            "draw": outcomes[1].get("price"),
                            "away": outcomes[2].get("price"),
                        })

            if odds_list:
                avg_h = sum(o["home"] for o in odds_list if o["home"]) / len(odds_list)
                avg_d = sum(o["draw"] for o in odds_list if o["draw"]) / len(odds_list)
                avg_a = sum(o["away"] for o in odds_list if o["away"]) / len(odds_list)

                simplified.append({
                    "sport_key": match.get("sport_key"),
                    "home_team": match.get("home_team"),
                    "away_team": match.get("away_team"),
                    "commence_time": match.get("commence_time"),
                    "avg_home": round(avg_h, 3),
                    "avg_draw": round(avg_d, 3),
                    "avg_away": round(avg_a, 3),
                    "bookmaker_count": len(odds_list),
                    "bookmakers": odds_list,
                })

        return simplified

    # ------------------------------------------------------------------
    # Scores
    # ------------------------------------------------------------------

    async def get_scores(self, sport_key: str, days_from: int = 1) -> List[Dict]:
        """Récupère les scores récents pour une ligue."""
        params = {"daysFrom": days_from}
        return await self._get(f"sports/{sport_key}/scores", params)

    # ------------------------------------------------------------------
    # Événements
    # ------------------------------------------------------------------

    async def get_events(self, sport_key: str) -> List[Dict]:
        """Liste les événements à venir avec leurs IDs."""
        return await self._get(f"sports/{sport_key}/events")