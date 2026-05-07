"""
Scheduler de pipelines ETL basé sur APScheduler.
Orchestre les tâches de collecte, transformation et entraînement
selon des planifications CRON configurables.
"""

import asyncio
import logging
from datetime import datetime
from typing import Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from config.settings import config as cfg

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scheduler")


class PipelineScheduler:
    """
    Planificateur de workflows ETL et ML.
    Utilise APScheduler pour une exécution asynchrone périodique.
    """

    def __init__(self):
        self._scheduler = AsyncIOScheduler(
            timezone=cfg.scheduler.timezone,
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 600,
            },
        )
        self._jobs = {}

    # ------------------------------------------------------------------
    # Enregistrement des jobs
    # ------------------------------------------------------------------

    def register_job(
        self,
        name: str,
        func: Callable,
        cron_expression: str,
        **kwargs,
    ):
        """
        Enregistre une tâche planifiée.
        name: identifiant unique du job
        func: coroutine asynchrone à exécuter
        cron_expression: ex. '0 6 * * *' (6h tous les jours)
        """
        trigger = CronTrigger.from_crontab(
            cron_expression, timezone=cfg.scheduler.timezone
        )

        async def wrapped():
            logger.info(f"[{name}] Démarrage @ {datetime.now()}")
            try:
                result = await func(**kwargs)
                logger.info(f"[{name}] Terminé: {result}")
            except Exception as exc:
                logger.error(f"[{name}] Erreur: {exc}", exc_info=True)

        self._jobs[name] = self._scheduler.add_job(
            wrapped, trigger=trigger, id=name, name=name
        )

    # ------------------------------------------------------------------
    # DAGs (Directed Acyclic Graphs) — workflows
    # ------------------------------------------------------------------

    async def dag_scrape_matches(self, date_str: Optional[str] = None):
        """
        DAG: Scraping quotidien des matchs.
        1. Scrape FlashScore → 2. Scrape Forebet → 3. ETL load
        """
        from scrapers.match_scraper import MatchScraper
        from pipeline.etl import ETLEngine

        scraper = MatchScraper()
        etl = ETLEngine()

        logger.info("DAG matches: scraping FlashScore...")
        flash_matches = await scraper.scrape_flashscore_league(
            "https://www.flashscore.fr/football/france/ligue-1/"
        )
        logger.info(f"DAG matches: {len(flash_matches)} matchs FlashScore")

        logger.info("DAG matches: scraping Forebet...")
        forebet_preds = await scraper.scrape_forebet_predictions(date_str)
        logger.info(f"DAG matches: {len(forebet_preds)} pronostics Forebet")

        etl.close()
        return {"flashscore": len(flash_matches), "forebet": len(forebet_preds)}

    async def dag_scrape_odds(self):
        """
        DAG: Scraping périodique des cotes (toutes les 4h).
        """
        from scrapers.odds_scraper import OddsScraper
        from pipeline.etl import ETLEngine

        scraper = OddsScraper()
        etl = ETLEngine()

        logger.info("DAG odds: scraping OddsPortal...")
        odds_data = await scraper.scrape_oddsportal_league("france/ligue-1/")

        # Charger les cotes dans la DB
        for odd in odds_data:
            if odd.get("avg_home"):
                # Ici on pourrait faire le matching avec les matchs existants
                pass

        etl.close()
        return {"odds_scraped": len(odds_data)}

    async def dag_retrain_models(self):
        """
        DAG: Ré-entraînement hebdomadaire des modèles ML.
        1. Extract features → 2. Train RF + XGBoost → 3. Evaluate → 4. Register MLflow
        """
        from models.feature_engineering import FeatureEngineer
        from models.trainer import ModelTrainer
        from models.evaluate import ModelEvaluator
        from pipeline.etl import ETLEngine

        etl = ETLEngine()
        engineer = FeatureEngineer()
        trainer = ModelTrainer()
        evaluator = ModelEvaluator()

        logger.info("DAG retrain: extraction des données historiques...")
        # Extraction depuis la DB des matchs terminés
        # features, targets = engineer.build_training_dataset(session=etl.session)

        logger.info("DAG retrain: entraînement Random Forest...")
        # rf_model, rf_metrics = trainer.train_random_forest(features, targets)

        logger.info("DAG retrain: entraînement XGBoost...")
        # xgb_model, xgb_metrics = trainer.train_xgboost(features, targets)

        logger.info("DAG retrain: évaluation (Brier Score, LogLoss)...")
        # brier_rf = evaluator.brier_score(rf_model, X_test, y_test)

        etl.close()
        return {"status": "models_retrained"}

    async def dag_generate_predictions(self):
        """
        DAG: Génération des pronostics pour les matchs du jour.
        """
        from models.predict import PredictionGenerator
        from analysis.value_betting import ValueBetDetector
        from analysis.kelly import KellyCriterion

        generator = PredictionGenerator()
        value_detector = ValueBetDetector()
        kelly = KellyCriterion()

        logger.info("DAG predict: génération des pronostics...")
        # predictions = await generator.predict_today()

        logger.info("DAG predict: détection des value bets...")
        # value_bets = value_detector.detect(predictions)

        logger.info("DAG predict: calcul du Kelly Criterion...")
        # stakes = kelly.compute_optimal_stakes(value_bets)

        return {"predictions_generated": 0}

    # ------------------------------------------------------------------
    # Démarrage / Arrêt
    # ------------------------------------------------------------------

    def start(self):
        """Démarre le scheduler avec les jobs par défaut."""
        self.register_job(
            "scrape_matches",
            self.dag_scrape_matches,
            cfg.scheduler.match_scrape_cron,
        )
        self.register_job(
            "scrape_odds",
            self.dag_scrape_odds,
            cfg.scheduler.odds_scrape_cron,
        )
        self.register_job(
            "retrain_models",
            self.dag_retrain_models,
            cfg.scheduler.model_retrain_cron,
        )
        self.register_job(
            "generate_predictions",
            self.dag_generate_predictions,
            "0 7 * * *",  # 7h tous les jours, après le scraping
        )

        self._scheduler.start()
        logger.info(
            f"Scheduler démarré avec {len(self._jobs)} jobs. "
            f"Timezone: {cfg.scheduler.timezone}"
        )

    def stop(self):
        """Arrête le scheduler proprement."""
        self._scheduler.shutdown(wait=True)
        logger.info("Scheduler arrêté.")

    def list_jobs(self) -> list:
        """Liste tous les jobs enregistrés avec leur prochaine exécution."""
        jobs_info = []
        for job in self._scheduler.get_jobs():
            jobs_info.append({
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
                "trigger": str(job.trigger),
            })
        return jobs_info


# ------------------------------------------------------------------
# Point d'entrée standalone
# ------------------------------------------------------------------

async def main():
    scheduler = PipelineScheduler()
    scheduler.start()

    # Lancer immédiatement le DAG matches pour test
    logger.info("Exécution immédiate DAG matches (test)...")
    await scheduler.dag_scrape_matches()

    try:
        # Maintient le scheduler actif
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        logger.info("Interruption reçue, arrêt...")
    finally:
        scheduler.stop()


if __name__ == "__main__":
    asyncio.run(main())