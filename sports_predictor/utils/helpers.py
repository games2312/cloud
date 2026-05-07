"""
Utilitaires partagés : logging, cache, helpers.
"""

import logging
import sys
from pathlib import Path
from functools import lru_cache, wraps
from datetime import datetime, timedelta
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Logging centralisé
# ---------------------------------------------------------------------------

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def setup_logger(name: str = "sports_predictor") -> logging.Logger:
    """Configure un logger avec rotation et double sortie (console + fichier)."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    # Console
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                                    datefmt="%H:%M:%S")
    console.setFormatter(console_fmt)
    logger.addHandler(console)

    # Fichier avec date
    file_handler = logging.FileHandler(
        LOG_DIR / f"app_{datetime.now():%Y%m%d}.log", encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d: %(message)s"
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    return logger


logger = setup_logger()


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def retry(max_attempts: int = 3, delay_seconds: float = 1.0,
          backoff: float = 2.0, exceptions: tuple = (Exception,)):
    """
    Décorateur pour réessayer une fonction en cas d'échec.
    Avec backoff exponentiel.
    """
    import time as _time

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            attempt_delay = delay_seconds
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        logger.warning(
                            f"Retry {attempt}/{max_attempts} pour {func.__name__}: {exc}. "
                            f"Nouvelle tentative dans {attempt_delay:.1f}s"
                        )
                        _time.sleep(attempt_delay)
                        attempt_delay *= backoff
            raise last_exc
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Cache avec TTL
# ---------------------------------------------------------------------------

class TTLCache:
    """Cache simple avec expiration temporelle."""

    def __init__(self, ttl_seconds: int = 300):
        self._cache: dict = {}
        self._expiry: dict = {}
        self.ttl = ttl_seconds

    def get(self, key: str) -> Any:
        if key in self._cache and datetime.now() < self._expiry.get(key, datetime.min):
            return self._cache[key]
        return None

    def set(self, key: str, value: Any, ttl_seconds: int = None):
        ttl = ttl_seconds or self.ttl
        self._cache[key] = value
        self._expiry[key] = datetime.now() + timedelta(seconds=ttl)

    def clear(self):
        self._cache.clear()
        self._expiry.clear()


match_cache = TTLCache(ttl_seconds=600)
odds_cache = TTLCache(ttl_seconds=300)


# ---------------------------------------------------------------------------
# Helpers génériques
# ---------------------------------------------------------------------------

def safe_divide(a: float, b: float, default: float = 0.0) -> float:
    """Division sécurisée (évite ZeroDivisionError)."""
    return a / b if b != 0 else default


def normalize_probabilities(probs: list) -> list:
    """Normalise une liste de probabilités pour que la somme = 1."""
    total = sum(probs)
    if total == 0:
        n = len(probs)
        return [1.0 / n] * n
    return [p / total for p in probs]


def outcome_label(home_score: int, away_score: int) -> str:
    """Retourne H, D ou A selon le score."""
    if home_score > away_score:
        return "H"
    elif away_score > home_score:
        return "A"
    return "D"


def implied_probability(odd: float) -> float:
    """Probabilité implicite depuis une cote décimale."""
    return 1.0 / odd if odd > 0 else 0.0


def overround(odds: tuple) -> float:
    """Marge du bookmaker (overround) à partir des cotes 1X2."""
    return sum(1.0 / o for o in odds if o and o > 0)


def timestamp_now() -> str:
    """Horodatage ISO 8601."""
    return datetime.now().isoformat()