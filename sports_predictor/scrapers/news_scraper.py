"""
Scraper d'actualités sportives : blessures, compositions, transferts.
Utilise des flux RSS et le scraping de sites d'actus pour alimenter
les features contextuelles des modèles de prédiction.
"""

import asyncio
import hashlib
from datetime import datetime
from typing import List, Dict, Optional

import feedparser
import httpx
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper


class NewsScraper(BaseScraper):
    """Scraper d'actualités sportives (RSS + HTML)."""

    RSS_FEEDS = [
        "https://www.lequipe.fr/rss/football.xml",
        "https://www.footmercato.net/rss.xml",
        "https://rmcsport.bfmtv.com/rss/football/",
        "https://www.maxifoot.fr/rss.xml",
    ]

    NEWS_SITES = {
        "lequipe": {
            "url": "https://www.lequipe.fr/Football/",
            "article_selector": "article",
            "title_selector": "h2 a",
            "link_selector": "h2 a",
        },
        "rmc_sport": {
            "url": "https://rmcsport.bfmtv.com/football/",
            "article_selector": "div.news-feed-item",
            "title_selector": "a.news-feed-item-title",
            "link_selector": "a.news-feed-item-title",
        },
    }

    INJURY_KEYWORDS = [
        "blessure", "blessé", "forfait", "indisponible", "infirmerie",
        "reprise", "retour", "entorse", "déchirure", "fracture",
        "lésion", "opéré", "rechute", "convalescence", "absent",
        "injury", "injured", "out", "doubtful", "unavailable",
    ]
    LINEUP_KEYWORDS = [
        "compo", "composition", "compos", "titulaire", "titulaires",
        "probable", "XI", "onze", "groupe", "convoqué", "convoqués",
        "équipe", "sélection",
    ]
    TRANSFER_KEYWORDS = [
        "transfert", "mercato", "signe", "signature", "recrue",
        "prolongation", "contrat", "prêté", "transfer", "signs",
    ]

    async def scrape_rss_feeds(self) -> List[Dict]:
        """Récupère les articles depuis les flux RSS configurés."""
        articles = []
        seen_urls = set()

        async def fetch_feed(url: str):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        return []
                    feed = feedparser.parse(resp.text)
                    results = []
                    for entry in feed.entries:
                        url_hash = hashlib.md5(entry.link.encode()).hexdigest()
                        if url_hash in seen_urls:
                            continue
                        seen_urls.add(url_hash)
                        tags = self._classify_article(
                            entry.get("title", "") + " " + entry.get("summary", "")
                        )
                        results.append({
                            "title": entry.get("title", ""),
                            "url": entry.get("link", ""),
                            "source": feed.feed.get("title", url),
                            "content_summary": entry.get("summary", "")[:2000],
                            "published_at": entry.get("published", None),
                            "tags": tags,
                            "scraped_at": datetime.utcnow().isoformat(),
                        })
                    return results
            except Exception as exc:
                print(f"[WARN] RSS fetch failed for {url}: {exc}")
                return []

        tasks = [fetch_feed(url) for url in self.RSS_FEEDS]
        results = await asyncio.gather(*tasks)
        for batch in results:
            articles.extend(batch)

        return articles

    async def scrape_news_sites(self) -> List[Dict]:
        """Scrape les pages d'accueil des sites d'actualités."""
        browser = await self.start_browser()
        page = await self.new_page()
        all_articles = []

        for site_name, site_cfg in self.NEWS_SITES.items():
            try:
                ok = await self.safe_goto(
                    page, site_cfg["url"],
                    wait_selector=site_cfg["article_selector"]
                )
                if not ok:
                    continue

                items = await page.query_selector_all(site_cfg["article_selector"])
                for item in items[:30]:  # Limiter à 30 articles par site
                    article = await self._parse_news_item(
                        item, page, site_name, site_cfg
                    )
                    if article:
                        all_articles.append(article)

            except Exception as exc:
                print(f"[WARN] News site scrape failed for {site_name}: {exc}")

        await self.close()
        return all_articles

    async def scrape_injury_reports(self, team_name: str) -> List[Dict]:
        """Recherche ciblée de blessures pour une équipe spécifique."""
        browser = await self.start_browser()
        page = await self.new_page()
        injuries = []

        search_query = f"{team_name} blessure blessé forfait football"
        search_url = f"https://www.google.com/search?q={search_query}&tbm=nws&hl=fr"

        try:
            ok = await self.safe_goto(page, search_url, wait_selector="div#search")
            if not ok:
                return injuries

            results = await page.query_selector_all("div.SoaBEf")
            for result in results[:10]:
                title = await self.text_or_none(result, "div.n0jPhd")
                link = await result.query_selector("a")
                href = await link.get_attribute("href") if link else None
                snippet = await self.text_or_none(result, "div.GI74Re")

                if title:
                    injuries.append({
                        "title": title,
                        "url": href,
                        "source": "google_news",
                        "content_summary": snippet[:2000] if snippet else "",
                        "published_at": datetime.utcnow().isoformat(),
                        "tags": ["injury"],
                        "relevant_team": team_name,
                        "scraped_at": datetime.utcnow().isoformat(),
                    })

        except Exception as exc:
            print(f"[WARN] Injury search failed for {team_name}: {exc}")
        finally:
            await self.close()

        return injuries

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    async def _parse_news_item(
        self, item, page, site_name: str, site_cfg: Dict
    ) -> Optional[Dict]:
        try:
            title_el = await item.query_selector(site_cfg["title_selector"])
            link_el = await item.query_selector(site_cfg["link_selector"])

            title = (await title_el.inner_text()).strip() if title_el else ""
            href = await link_el.get_attribute("href") if link_el else ""

            if not title:
                return None

            tags = self._classify_article(title)
            return {
                "title": title,
                "url": href,
                "source": site_name,
                "content_summary": title,
                "published_at": datetime.utcnow().isoformat(),
                "tags": tags,
                "scraped_at": datetime.utcnow().isoformat(),
            }
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify_article(self, text: str) -> List[str]:
        """Classifie un article par tags (injury, lineup, transfer)."""
        tags = []
        text_lower = text.lower()

        if any(kw in text_lower for kw in self.INJURY_KEYWORDS):
            tags.append("injury")
        if any(kw in text_lower for kw in self.LINEUP_KEYWORDS):
            tags.append("lineup")
        if any(kw in text_lower for kw in self.TRANSFER_KEYWORDS):
            tags.append("transfer")

        return tags if tags else ["general"]