"""
Configuration centrale du système Sports Predictor.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class ScraperConfig:
    """Configuration des scrapers Playwright + anti-bot."""
    headless: bool = True
    timeout_ms: int = 30_000
    max_retries: int = 3
    random_delay_range: tuple = (1.0, 3.0)
    proxy_pool: List[str] = field(default_factory=list)
    user_agents: List[str] = field(default_factory=lambda: [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    ])
    captcha_api_key: Optional[str] = None
    stealth_mode: bool = True


@dataclass
class ApiClientConfig:
    """Configuration des clients API sportives."""
    sportmonks_api_token: Optional[str] = None
    odds_api_key: Optional[str] = None
    api_sports_key: Optional[str] = None
    request_timeout: int = 30
    rate_limit_rps: float = 5.0


@dataclass
class DatabaseConfig:
    """Configuration PostgreSQL / warehouse."""
    host: str = "localhost"
    port: int = 5432
    dbname: str = "sports_predictor"
    user: str = "predictor"
    password: str = ""
    pool_min: int = 2
    pool_max: int = 10


@dataclass
class ModelConfig:
    """Configuration des modèles ML."""
    random_forest_n_estimators: int = 200
    xgboost_n_estimators: int = 300
    xgboost_max_depth: int = 6
    xgboost_learning_rate: float = 0.05
    test_split_ratio: float = 0.2
    walk_forward_windows: int = 5
    mlflow_tracking_uri: str = str(PROJECT_ROOT / "mlruns")
    target_columns: List[str] = field(default_factory=lambda: ["home_win", "draw", "away_win"])


@dataclass
class KellyConfig:
    """Configuration du Kelly Criterion."""
    fractional_kelly: float = 0.25
    max_stake_pct: float = 0.05
    min_edge: float = 0.02


@dataclass
class SchedulerConfig:
    """Configuration du scheduler de pipelines."""
    match_scrape_cron: str = "0 6 * * *"       # 6h tous les jours
    odds_scrape_cron: str = "0 */4 * * *"       # toutes les 4h
    model_retrain_cron: str = "0 3 * * 1"       # lundi 3h
    timezone: str = "Europe/Paris"


@dataclass
class APIConfig:
    """Configuration du serveur FastAPI."""
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    cors_origins: List[str] = field(default_factory=lambda: ["*"])
    title: str = "Sports Predictor API"
    version: str = "1.0.0"


@dataclass
class Config:
    scraper: ScraperConfig = field(default_factory=ScraperConfig)
    api_client: ApiClientConfig = field(default_factory=ApiClientConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    kelly: KellyConfig = field(default_factory=KellyConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    api: APIConfig = field(default_factory=APIConfig)

    @classmethod
    def from_env(cls) -> "Config":
        cfg = cls()
        cfg.api_client.sportmonks_api_token = os.getenv("SPORTMONKS_TOKEN")
        cfg.api_client.odds_api_key = os.getenv("ODDS_API_KEY")
        cfg.api_client.api_sports_key = os.getenv("API_SPORTS_KEY")
        cfg.scraper.captcha_api_key = os.getenv("CAPMONSTER_KEY")
        cfg.database.password = os.getenv("DB_PASSWORD", "")
        cfg.database.host = os.getenv("DB_HOST", "localhost")
        cfg.database.port = int(os.getenv("DB_PORT", "5432"))
        cfg.database.dbname = os.getenv("DB_NAME", "sports_predictor")
        return cfg


# Singleton
config = Config.from_env()