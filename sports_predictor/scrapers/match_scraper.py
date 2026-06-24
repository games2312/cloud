"""
Scraper de matchs de football — cible les pages de résultats et calendrier.
Utilise Playwright pour les sites dynamiques avec fallback vers les APIs.
"""

import asyncio
from datetime import datetime
from typing import List, Dict, Optional

from playwright.async_api import Page
from scrapers.base_scraper import BaseScraper
from config.settings import config as cfg


class MatchScraper(BaseScraper):
    """Scraper spécialisé pour les données de matchs (résultats, stats, xG)."""

    URLS = {
        "flashscore": "https://www.flashscore.fr/football/",
        "sofascore": "https://www.sofascore.com/fr/football/",
        "forebet": "https://www.forebet.com/fr/",
    }

    async def scrape_flashscore_league(self, league_url: str) -> List[Dict]:
        """
        Scrape les matchs d'une ligue sur FlashScore.
        Retourne une liste de dicts contenant : home_team, away_team, score, date, stats.
        """
        browser = await self.start_browser()
        page = await self.new_page()
        matches = []

        try:
            ok = await self.safe_goto(
                page, league_url, wait_selector=".event__match"
            )
            if not ok:
                return matches

            # Scroll progressif pour charger les matchs dynamiques
            await self._scroll_to_load_all(page, "div.event__match")

            rows = await page.query_selector_all("div.event__match")
            for row in rows:
                match_data = await self._parse_flashscore_row(row, page)
                if match_data:
                    matches.append(match_data)

        except Exception as exc:
            print(f"[ERROR] FlashScore scrape failed: {exc}")
        finally:
            await self.close()

        return matches

    async def scrape_forebet_predictions(self, date_str: Optional[str] = None) -> List[Dict]:
        """
        Scrape les pronostics Forebet (modèle de référence).
        date_str format: 'YYYY-MM-DD' (None = aujourd'hui).
        """
        browser = await self.start_browser()
        page = await self.new_page()
        predictions = []

        try:
            url = self.URLS["forebet"]
            if date_str:
                url += f"?date={date_str}"

            ok = await self.safe_goto(page, url, wait_selector=".rcnt")
            if not ok:
                return predictions

            rows = await page.query_selector_all("div.rcnt")
            for row in rows:
                pred = await self._parse_forebet_row(row, page)
                if pred:
                    predictions.append(pred)

        except Exception as exc:
            print(f"[ERROR] Forebet scrape failed: {exc}")
        finally:
            await self.close()

        return predictions

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    async def _parse_flashscore_row(self, row, page: Page) -> Optional[Dict]:
        """Parse une ligne de match FlashScore."""
        try:
            home = await self.text_or_none(row, ".event__participant--home")
            away = await self.text_or_none(row, ".event__participant--away")
            score_home = await self.text_or_none(row, ".event__score--home")
            score_away = await self.text_or_none(row, ".event__score--away")
            time_el = await self.text_or_none(row, ".event__time")

            if not home or not away:
                return None

            return {
                "source": "flashscore",
                "home_team": home,
                "away_team": away,
                "home_score": int(score_home) if score_home and score_home.isdigit() else None,
                "away_score": int(score_away) if score_away and score_away.isdigit() else None,
                "status": "finished" if score_home and score_home.isdigit() else "scheduled",
                "match_time": time_el,
            }
        except Exception:
            return None

    async def _parse_forebet_row(self, row, page: Page) -> Optional[Dict]:
        """Parse une ligne de pronostic Forebet."""
        try:
            home = await self.text_or_none(row, ".homeTeam")
            away = await self.text_or_none(row, ".awayTeam")
            pred_1 = await self.text_or_none(row, ".fprc:nth-child(1)")
            pred_x = await self.text_or_none(row, ".fprc:nth-child(2)")
            pred_2 = await self.text_or_none(row, ".fprc:nth-child(3)")

            if not home or not away:
                return None

            return {
                "source": "forebet",
                "home_team": home,
                "away_team": away,
                "forebet_home_pct": self._parse_pct(pred_1),
                "forebet_draw_pct": self._parse_pct(pred_x),
                "forebet_away_pct": self._parse_pct(pred_2),
            }
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_pct(text: Optional[str]) -> Optional[float]:
        if not text:
            return None
        try:
            return float(text.replace("%", "").strip()) / 100.0
        except ValueError:
            return None

    async def _scroll_to_load_all(self, page: Page, selector: str, max_scrolls: int = 20):
        """Scroll progressif pour charger le contenu lazy-loadé."""
        for _ in range(max_scrolls):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self.random_delay(1, 2)
            current = len(await page.query_selector_all(selector))
            await self.random_delay(0.5, 1.5)
            after = len(await page.query_selector_all(selector))
            if current == after:
                break