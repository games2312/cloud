"""
Scraper de cotes sportives multi-bookmaker.
Cible OddsPortal et autres agrégateurs de cotes avec Playwright.
"""

import asyncio
from typing import List, Dict, Optional
from datetime import datetime

from playwright.async_api import Page
from scrapers.base_scraper import BaseScraper
from config.settings import config as cfg


class OddsScraper(BaseScraper):
    """Récupère les cotes d'ouverture et de clôture multi-bookmaker."""

    URLS = {
        "oddsportal": "https://www.oddsportal.com/football/",
        "betexplorer": "https://www.betexplorer.com/football/",
    }

    async def scrape_oddsportal_league(self, league_path: str) -> List[Dict]:
        """
        Scrape les cotes sur OddsPortal pour une ligue donnée.
        league_path: ex. 'france/ligue-1/'
        """
        browser = await self.start_browser()
        page = await self.new_page()
        odds_data = []

        try:
            url = f"{self.URLS['oddsportal']}{league_path}"
            ok = await self.safe_goto(
                page, url, wait_selector=".eventRow"
            )
            if not ok:
                return odds_data

            await self._dismiss_cookie_banner(page)
            await self._scroll_to_load_all(page, "div.eventRow")

            rows = await page.query_selector_all("div.eventRow")
            for row in rows:
                odd = await self._parse_oddsportal_row(row, page)
                if odd:
                    odds_data.append(odd)

        except Exception as exc:
            print(f"[ERROR] OddsPortal scrape failed: {exc}")
        finally:
            await self.close()

        return odds_data

    async def scrape_betexplorer_league(self, league_path: str) -> List[Dict]:
        """
        Scrape BetExplorer pour une couverture bookmaker alternative.
        """
        browser = await self.start_browser()
        page = await self.new_page()
        odds_data = []

        try:
            url = f"{self.URLS['betexplorer']}{league_path}"
            ok = await self.safe_goto(
                page, url, wait_selector="table.table-main"
            )
            if not ok:
                return odds_data

            rows = await page.query_selector_all("table.table-main tbody tr")
            for row in rows:
                odd = await self._parse_betexplorer_row(row, page)
                if odd:
                    odds_data.append(odd)

        except Exception as exc:
            print(f"[ERROR] BetExplorer scrape failed: {exc}")
        finally:
            await self.close()

        return odds_data

    async def scrape_odds_with_details(self, match_url: str) -> Dict:
        """
        Scrape les cotes détaillées d'un match spécifique (tous les bookmakers).
        """
        browser = await self.start_browser()
        page = await self.new_page()
        details = {"bookmakers": []}

        try:
            ok = await self.safe_goto(
                page, match_url, wait_selector="table.odds-data"
            )
            if not ok:
                return details

            await self._dismiss_cookie_banner(page)

            # Extraire les cotes moyennes du header
            avg_home = await self.text_or_none(page, "p.average-chart-data:nth-child(1) .odds")
            avg_draw = await self.text_or_none(page, "p.average-chart-data:nth-child(2) .odds")
            avg_away = await self.text_or_none(page, "p.average-chart-data:nth-child(3) .odds")

            details["avg_home"] = self._parse_odd(avg_home)
            details["avg_draw"] = self._parse_odd(avg_draw)
            details["avg_away"] = self._parse_odd(avg_away)

            # Extraire les cotes par bookmaker
            bm_rows = await page.query_selector_all("table.odds-data tbody tr")
            for bm_row in bm_rows:
                bm_data = await self._parse_bookmaker_row(bm_row, page)
                if bm_data:
                    details["bookmakers"].append(bm_data)

        except Exception as exc:
            print(f"[ERROR] Match odds detail scrape failed: {exc}")
        finally:
            await self.close()

        return details

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    async def _parse_oddsportal_row(self, row, page: Page) -> Optional[Dict]:
        try:
            home = await self.text_or_none(row, ".participant--home .participantName")
            away = await self.text_or_none(row, ".participant--away .participantName")
            date_elem = await self.text_or_none(row, ".eventTime")
            odd_home = await self.text_or_none(row, ".odds-1")
            odd_draw = await self.text_or_none(row, ".odds-x")
            odd_away = await self.text_or_none(row, ".odds-2")

            if not home or not away:
                return None

            return {
                "source": "oddsportal",
                "home_team": home.strip(),
                "away_team": away.strip(),
                "date": date_elem.strip() if date_elem else None,
                "avg_home": self._parse_odd(odd_home),
                "avg_draw": self._parse_odd(odd_draw),
                "avg_away": self._parse_odd(odd_away),
            }
        except Exception:
            return None

    async def _parse_betexplorer_row(self, row, page: Page) -> Optional[Dict]:
        try:
            home = await self.text_or_none(row, "td.h-text-left a")
            away = await self.text_or_none(row, "td.h-text-right a")
            cells = await row.query_selector_all("td.table-main__odds")
            if len(cells) >= 3:
                odd_home = await cells[0].inner_text()
                odd_draw = await cells[1].inner_text()
                odd_away = await cells[2].inner_text()
            else:
                return None

            if not home or not away:
                return None

            return {
                "source": "betexplorer",
                "home_team": home.strip(),
                "away_team": away.strip(),
                "avg_home": self._parse_odd(odd_home),
                "avg_draw": self._parse_odd(odd_draw),
                "avg_away": self._parse_odd(odd_away),
            }
        except Exception:
            return None

    async def _parse_bookmaker_row(self, row, page: Page) -> Optional[Dict]:
        try:
            name = await self.text_or_none(row, "td.bet-name")
            home = await self.text_or_none(row, "td:nth-child(2)")
            draw = await self.text_or_none(row, "td:nth-child(3)")
            away = await self.text_or_none(row, "td:nth-child(4)")

            if not name:
                return None

            return {
                "bookmaker": name.strip(),
                "home": self._parse_odd(home),
                "draw": self._parse_odd(draw),
                "away": self._parse_odd(away),
            }
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_odd(text: Optional[str]) -> Optional[float]:
        if not text:
            return None
        try:
            return float(text.strip().replace(",", "."))
        except (ValueError, AttributeError):
            return None

    async def _scroll_to_load_all(self, page: Page, selector: str, max_scrolls: int = 20):
        """Scroll progressif."""
        for _ in range(max_scrolls):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self.random_delay(1, 2)
            current = len(await page.query_selector_all(selector))
            await self.random_delay(0.5, 1.5)
            after = len(await page.query_selector_all(selector))
            if current == after:
                break

    async def _dismiss_cookie_banner(self, page: Page):
        """Ferme le bandeau cookies si présent."""
        for btn_selector in [
            "#onetrust-accept-btn-handler",
            "button.cookie-consent-accept",
            "button[aria-label='Accept all']",
            ".cookieAcceptBox button",
        ]:
            try:
                btn = await page.query_selector(btn_selector)
                if btn and await btn.is_visible():
                    await btn.click()
                    await self.random_delay(0.5, 1)
                    break
            except Exception:
                continue