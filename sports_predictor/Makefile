# =============================================================================
# Sports Predictor — Makefile
# =============================================================================
# Commandes principales pour le développement et le déploiement.
#
# Usage:
#   make install     → installer les dépendances
#   make dev         → lancer le serveur API en mode dev
#   make scrape      → lancer le scraping manuel
#   make train       → entraîner les modèles
#   make predict     → générer les pronostics
#   make docker      → construire l'image Docker
#   make test        → lancer les tests

.PHONY: help install dev scrape train predict test docker clean db-init

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------
PYTHON := python3
PIP := pip3
APP := server.py
HOST := 0.0.0.0
PORT := 8000

# ---------------------------------------------------------------------------
# Aide
# ---------------------------------------------------------------------------
help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
install: ## Installe toutes les dépendances Python
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PYTHON) -m playwright install chromium

# ---------------------------------------------------------------------------
# Développement
# ---------------------------------------------------------------------------
dev: ## Lance le serveur API en mode développement (hot-reload)
	$(PYTHON) -m uvicorn server:app --host $(HOST) --port $(PORT) --reload

dev-prod: ## Lance le serveur en mode production
	$(PYTHON) -m uvicorn server:app --host $(HOST) --port $(PORT) --workers 4

# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------
scrape-matches: ## Lance le scraping des matchs (manuel)
	$(PYTHON) -c "from pipeline.scheduler import PipelineScheduler; \
		import asyncio; asyncio.run(PipelineScheduler().dag_scrape_matches())"

scrape-odds: ## Lance le scraping des cotes (manuel)
	$(PYTHON) -c "from pipeline.scheduler import PipelineScheduler; \
		import asyncio; asyncio.run(PipelineScheduler().dag_scrape_odds())"

scrape-news: ## Lance le scraping des actualités
	$(PYTHON) -c "from scrapers.news_scraper import NewsScraper; \
		import asyncio; asyncio.run(NewsScraper().scrape_rss_feeds())"

# ---------------------------------------------------------------------------
# Machine Learning
# ---------------------------------------------------------------------------
train: ## Entraîne les modèles ML (RF + XGBoost)
	$(PYTHON) -c "from models.trainer import ModelTrainer; \
		from models.feature_engineering import FeatureEngineer; \
		from database.models import get_session; \
		session = get_session(); \
		fe = FeatureEngineer(); \
		X, y = fe.build_training_dataset(session); \
		trainer = ModelTrainer(); \
		rf, _ = trainer.train_random_forest(X, y); \
		xgb, _ = trainer.train_xgboost(X, y); \
		trainer.save_model(rf, 'models_saved/rf_latest.pkl'); \
		trainer.save_model(xgb, 'models_saved/xgb_latest.pkl'); \
		print('[OK] Modèles entraînés et sauvegardés.');"

predict: ## Génère les pronostics pour aujourd'hui
	$(PYTHON) -c "from models.predict import PredictionGenerator; \
		from database.models import get_session; \
		session = get_session(); \
		gen = PredictionGenerator(); \
		results = gen.generate_daily(session, None, None); \
		print(f'[OK] {len(results)} pronostics générés.');"

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
scheduler: ## Lance le scheduler de pipelines
	$(PYTHON) -c "from pipeline.scheduler import PipelineScheduler; \
		import asyncio; sched = PipelineScheduler(); sched.start(); \
		asyncio.get_event_loop().run_forever()"

# ---------------------------------------------------------------------------
# Base de données
# ---------------------------------------------------------------------------
db-init: ## Initialise les tables de la base de données
	$(PYTHON) -c "from database.models import init_db; init_db(); print('[OK] Tables créées.')"

db-reset: ## Réinitialise toutes les tables (⚠️ DESTRUCTIF)
	$(PYTHON) -c "from database.models import Base, engine; \
		Base.metadata.drop_all(engine); Base.metadata.create_all(engine); \
		print('[OK] Base réinitialisée.')"

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
test: ## Lance les tests unitaires
	$(PYTHON) -m pytest tests/ -v --cov=. --cov-report=term-missing

test-coverage: ## Génère le rapport de couverture HTML
	$(PYTHON) -m pytest tests/ --cov=. --cov-report=html

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------
docker-build: ## Construit l'image Docker
	docker build -t sports-predictor:latest .

docker-run: ## Lance le conteneur Docker
	docker run -d -p 8000:8000 --name sports-predictor \
		-e DB_HOST=host.docker.internal \
		sports-predictor:latest

docker-stop: ## Arrête le conteneur
	docker stop sports-predictor || true
	docker rm sports-predictor || true

# ---------------------------------------------------------------------------
# Nettoyage
# ---------------------------------------------------------------------------
clean: ## Nettoie les fichiers temporaires
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	find . -type f -name '*.pyo' -delete
	rm -rf .pytest_cache .coverage htmlcov
	rm -rf data/raw/* data/processed/*

clean-all: clean ## Nettoie tout (modèles, logs inclus)
	rm -rf mlruns/* models_saved/*
	rm -rf logs/*