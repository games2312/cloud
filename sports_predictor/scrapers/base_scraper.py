"""
Scraper de base avec Playwright + rotation proxy + anti-détection.
Fournit les fondations anti-bot pour tous les scrapers spécialisés.
"""

import asyncio
import random
import time
from typing import Optional, Dict, Any
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from config.settings import config as cfg


class BaseScraper:
    """Classe de base pour tous les scrapers Playwright avec protection anti-bot."""

    def __init__(self):
        self.cfg = cfg.scraper
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._proxy_index = 0

    # ------------------------------------------------------------------
    # Cycle de vie du navigateur
    # ------------------------------------------------------------------

    async def start_browser(self) -> Browser:
        """Lance un navigateur Chromium headless avec fingerprinting aléatoire."""
        pw = await async_playwright().start()
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
        proxy = self._next_proxy()
        proxy_opts = {}
        if proxy:
            proxy_opts = {"server": proxy}

        self._browser = await pw.chromium.launch(
            headless=self.cfg.headless,
            args=launch_args,
            proxy=proxy_opts if proxy else None,
        )
        return self._browser

    async def new_context(self) -> BrowserContext:
        """Crée un contexte isolé avec User-Agent aléatoire et stealth viewport."""
        ua = random.choice(self.cfg.user_agents)
        viewports = [(1920, 1080), (1366, 768), (1440, 900)]
        vp = random.choice(viewports)

        self._context = await self._browser.new_context(
            user_agent=ua,
            viewport={"width": vp[0], "height": vp[1]},
            locale="fr-FR",
            timezone_id="Europe/Paris",
            permissions=["geolocation"],
            geolocation={"latitude": 48.8566, "longitude": 2.3522},
        )

        if self.cfg.stealth_mode:
            await self._inject_stealth_scripts()

        return self._context

    async def new_page(self) -> Page:
        """Crée une page avec les contremesures anti-bot actives."""
        if not self._context:
            await self.new_context()
        page = await self._context.new_page()
        page.set_default_timeout(self.cfg.timeout_ms)
        return page

    async def close(self):
        """Ferme proprement le navigateur."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()

    # ------------------------------------------------------------------
    # Anti-bot : proxies, délais, stealth
    # ------------------------------------------------------------------

    def _next_proxy(self) -> Optional[str]:
        """Rotation des proxies (round-robin)."""
        if not self.cfg.proxy_pool:
            return None
        proxy = self.cfg.proxy_pool[self._proxy_index]
        self._proxy_index = (self._proxy_index + 1) % len(self.cfg.proxy_pool)
        return proxy

    async def _inject_stealth_scripts(self):
        """Injecte des scripts pour masquer Puppeteer/Playwright."""
        await self._context.add_init_script("""
        // Supprime webdriver flag
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        // Chrome runtime
        window.chrome = { runtime: {} };
        // Plugins factices
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        // Languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['fr-FR', 'fr', 'en-US', 'en'],
        });
        """)

    async def random_delay(self, min_s: float = None, max_s: float = None):
        """Délai aléatoire pour imiter un humain."""
        lo, hi = self.cfg.random_delay_range
        await asyncio.sleep(random.uniform(min_s or lo, max_s or hi))

    # ------------------------------------------------------------------
    # Navigation robuste
    # ------------------------------------------------------------------

    async def safe_goto(self, page: Page, url: str, wait_selector: Optional[str] = None) -> bool:
        """
        Navigue avec retry automatique et attend qu'un sélecteur CSS clé
        soit visible pour valider le chargement.
        """
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=self.cfg.timeout_ms)
                await self.random_delay()
                if wait_selector:
                    await page.wait_for_selector(wait_selector, state="visible", timeout=15_000)
                return True
            except Exception as exc:
                print(f"[WARN] Tentative {attempt}/{self.cfg.max_retries} échouée pour {url}: {exc}")
                if attempt < self.cfg.max_retries:
                    await self.random_delay(3, 6)
        print(f"[ERROR] Navigation abandonnée pour {url}")
        return False

    async def extract_table_rows(self, page: Page, table_selector: str) -> list:
        """Extrait toutes les lignes d'un tableau HTML."""
        rows = await page.query_selector_all(f"{table_selector} tbody tr")
        if not rows:
            rows = await page.query_selector_all(f"{table_selector} tr")
        return rows

    async def text_or_none(self, page: Page, selector: str) -> Optional[str]:
        """Retourne le texte d'un élément ou None s'il n'existe pas."""
        try:
            el = await page.query_selector(selector)
            return (await el.inner_text()).strip() if el else None
        except Exception:
            return None