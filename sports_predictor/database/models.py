"""
Modèles de données ORM SQLAlchemy pour le Data Warehouse.
"""

from datetime import datetime
from decimal import Decimal
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Date, ForeignKey,
    Boolean, Numeric, JSON, Index, UniqueConstraint, create_engine
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from config.settings import config as cfg

Base = declarative_base()

# ---------------------------------------------------------------------------
# Tables de référence
# ---------------------------------------------------------------------------

class League(Base):
    __tablename__ = "leagues"
    id = Column(Integer, primary_key=True, autoincrement=True)
    api_id = Column(Integer, unique=True, index=True)
    name = Column(String(120), nullable=False)
    country = Column(String(80))
    flag_url = Column(String(300))
    season = Column(String(9))  # e.g. "2025/2026"
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    teams = relationship("Team", back_populates="league")
    matches = relationship("Match", back_populates="league")


class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True, autoincrement=True)
    api_id = Column(Integer, unique=True, index=True)
    name = Column(String(120), nullable=False)
    short_code = Column(String(5))
    logo_url = Column(String(300))
    league_id = Column(Integer, ForeignKey("leagues.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    league = relationship("League", back_populates="teams")
    home_matches = relationship("Match", foreign_keys="Match.home_team_id", back_populates="home_team")
    away_matches = relationship("Match", foreign_keys="Match.away_team_id", back_populates="away_team")


# ---------------------------------------------------------------------------
# Données de match
# ---------------------------------------------------------------------------

class Match(Base):
    __tablename__ = "matches"
    id = Column(Integer, primary_key=True, autoincrement=True)
    api_id = Column(Integer, unique=True, index=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), index=True)
    home_team_id = Column(Integer, ForeignKey("teams.id"), index=True)
    away_team_id = Column(Integer, ForeignKey("teams.id"), index=True)
    match_date = Column(DateTime, index=True, nullable=False)
    status = Column(String(20), default="scheduled")  # scheduled | live | finished | postponed
    round_name = Column(String(80))
    venue = Column(String(200))
    referee = Column(String(120))

    # Résultat
    home_score = Column(Integer, nullable=True)
    away_score = Column(Integer, nullable=True)
    home_score_ht = Column(Integer, nullable=True)
    away_score_ht = Column(Integer, nullable=True)

    # Performances
    home_possession = Column(Float)
    away_possession = Column(Float)
    home_shots = Column(Integer)
    away_shots = Column(Integer)
    home_shots_on = Column(Integer)
    away_shots_on = Column(Integer)
    home_corners = Column(Integer)
    away_corners = Column(Integer)
    home_fouls = Column(Integer)
    away_fouls = Column(Integer)
    home_xg = Column(Float)
    away_xg = Column(Float)

    # Métadonnées extraites
    extra_stats = Column(JSON)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    league = relationship("League", back_populates="matches")
    home_team = relationship("Team", foreign_keys=[home_team_id], back_populates="home_matches")
    away_team = relationship("Team", foreign_keys=[away_team_id], back_populates="away_matches")
    odds = relationship("Odds", back_populates="match", uselist=False)
    player_stats = relationship("PlayerStats", back_populates="match")

    __table_args__ = (
        Index("ix_match_date_league", "match_date", "league_id"),
    )


# ---------------------------------------------------------------------------
# Cotes et marché des paris
# ---------------------------------------------------------------------------

class Odds(Base):
    __tablename__ = "odds"
    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), unique=True, index=True)

    # Moyennes marché (multi-bookmaker)
    avg_home = Column(Float)
    avg_draw = Column(Float)
    avg_away = Column(Float)
    bookmaker_count = Column(Integer)

    # Opening / closing pour Value Betting
    open_home = Column(Float)
    open_draw = Column(Float)
    open_away = Column(Float)
    close_home = Column(Float)
    close_draw = Column(Float)
    close_away = Column(Float)

    # Bookmakers individuels (JSON)
    bookmakers_detail = Column(JSON)

    scraped_at = Column(DateTime, default=datetime.utcnow)

    match = relationship("Match", back_populates="odds")


# ---------------------------------------------------------------------------
# Statistiques joueurs
# ---------------------------------------------------------------------------

class PlayerStats(Base):
    __tablename__ = "player_stats"
    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), index=True)
    player_name = Column(String(120))
    team_side = Column(String(4))  # home | away
    goals = Column(Integer, default=0)
    assists = Column(Integer, default=0)
    passes = Column(Integer)
    passes_key = Column(Integer)
    rating = Column(Float)

    match = relationship("Match", back_populates="player_stats")


# ---------------------------------------------------------------------------
# Actualités / Blessures
# ---------------------------------------------------------------------------

class NewsItem(Base):
    __tablename__ = "news_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(300), nullable=False)
    url = Column(String(500), unique=True)
    source = Column(String(100))
    content_summary = Column(String(2000))
    published_at = Column(DateTime)
    tags = Column(JSON)  # ["injury", "transfer", "lineup"]
    relevant_team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    scraped_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_news_tags", "tags", postgresql_using="gin"),
    )


# ---------------------------------------------------------------------------
# Prédictions sauvegardées
# ---------------------------------------------------------------------------

class Prediction(Base):
    __tablename__ = "predictions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), unique=True, index=True)
    model_name = Column(String(80))
    model_version = Column(String(40))

    prob_home = Column(Float)
    prob_draw = Column(Float)
    prob_away = Column(Float)

    predicted_outcome = Column(String(5))  # H | D | A
    confidence = Column(Float)

    # Métriques de qualité
    brier_score = Column(Float, nullable=True)
    log_loss = Column(Float, nullable=True)

    # Value betting
    kelly_fraction = Column(Float, nullable=True)
    recommended_stake_pct = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Connexion DB
# ---------------------------------------------------------------------------

engine = create_engine(
    f"postgresql://{config.database.user}:{config.database.password}"
    f"@{config.database.host}:{config.database.port}/{config.database.dbname}",
    pool_size=config.database.pool_max,
    pool_pre_ping=True,
    echo=False,
)
SessionLocal = sessionmaker(bind=engine)


def init_db():
    """Crée toutes les tables."""
    Base.metadata.create_all(engine)


def get_session():
    return SessionLocal()