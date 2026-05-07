-- =============================================================================
-- Sports Predictor — Initialisation de la base de données
-- =============================================================================
-- Exécuté automatiquement par docker-entrypoint-initdb.d

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ---------------------------------------------------------------------------
-- Tables de référence (ligues et équipes par défaut)
-- ---------------------------------------------------------------------------

-- Ligues majeures pré-enregistrées
INSERT INTO leagues (api_id, name, country, season, active) VALUES
    (501, 'Ligue 1', 'France', '2025/2026', TRUE),
    (502, 'Premier League', 'England', '2025/2026', TRUE),
    (503, 'La Liga', 'Spain', '2025/2026', TRUE),
    (504, 'Serie A', 'Italy', '2025/2026', TRUE),
    (505, 'Bundesliga', 'Germany', '2025/2026', TRUE),
    (506, 'Ligue 2', 'France', '2025/2026', TRUE),
    (507, 'Champions League', 'Europe', '2025/2026', TRUE),
    (508, 'Europa League', 'Europe', '2025/2026', TRUE)
ON CONFLICT (api_id) DO NOTHING;

-- Index pour les recherches textuelles
CREATE INDEX IF NOT EXISTS idx_leagues_name_trgm ON leagues USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_teams_name_trgm ON teams USING gin (name gin_trgm_ops);

-- Vue matérialisée pour les statistiques par équipe
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_team_stats AS
SELECT
    t.id AS team_id,
    t.name AS team_name,
    l.name AS league_name,
    COUNT(m.id) AS matches_played,
    SUM(CASE WHEN m.home_team_id = t.id AND m.home_score > m.away_score THEN 1
             WHEN m.away_team_id = t.id AND m.away_score > m.home_score THEN 1
             ELSE 0 END) AS wins,
    SUM(CASE WHEN m.home_score = m.away_score THEN 1 ELSE 0 END) AS draws,
    SUM(CASE WHEN m.home_team_id = t.id AND m.home_score < m.away_score THEN 1
             WHEN m.away_team_id = t.id AND m.away_score < m.home_score THEN 1
             ELSE 0 END) AS losses,
    AVG(CASE WHEN m.home_team_id = t.id THEN m.home_score ELSE m.away_score END) AS avg_goals_for,
    AVG(CASE WHEN m.home_team_id = t.id THEN m.away_score ELSE m.home_score END) AS avg_goals_against,
    AVG(m.home_xg) FILTER (WHERE m.home_team_id = t.id) AS avg_xg_home,
    AVG(m.away_xg) FILTER (WHERE m.away_team_id = t.id) AS avg_xg_away
FROM teams t
JOIN leagues l ON t.league_id = l.id
LEFT JOIN matches m ON (m.home_team_id = t.id OR m.away_team_id = t.id)
    AND m.status = 'finished'
GROUP BY t.id, t.name, l.name;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_team_stats_team ON mv_team_stats (team_id);