"""
Serveur FastAPI principal — point d'entrée de l'API Sports Predictor.
Expose les endpoints REST pour les pronostics, cotes et analyses.
"""

import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import uvicorn

from config.settings import config as cfg
from api.routes.predictions import router as predictions_router
from database.models import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Cycle de vie de l'application."""
    startup_time = time.time()

    # Startup
    print("[INIT] Initialisation de la base de données...")
    try:
        init_db()
        print("[INIT] Base de données prête.")
    except Exception as exc:
        print(f"[WARN] DB init différée: {exc}")

    app.state.startup_time = startup_time
    app.state.uptime_start = startup_time

    yield

    # Shutdown
    print("[SHUTDOWN] Arrêt du serveur...")


app = FastAPI(
    title=cfg.api.title,
    version=cfg.api.version,
    description="""
## API de Pronostics Sportifs

Système complet de prédiction sportive avec:

- **Collecte** : Scraping Playwright + APIs sportives
- **Modèles** : Random Forest & XGBoost avec walk-forward validation
- **Analyse** : Value Betting, Kelly Criterion, backtesting
- **Stockage** : Data Warehouse PostgreSQL

### Fonctionnalités
- Pronostics journaliers multi-ligues
- Détection de value bets en temps réel
- Gestion de bankroll avec Kelly Criterion
- Tableaux de bord de performance
    """,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.api.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Routes
app.include_router(predictions_router)

# Route racine
@app.get("/")
async def root():
    return {
        "service": cfg.api.title,
        "version": cfg.api.version,
        "docs": "/docs",
        "health": "/api/v1/health",
    }


if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host=cfg.api.host,
        port=cfg.api.port,
        reload=cfg.api.debug,
        log_level="info",
    )