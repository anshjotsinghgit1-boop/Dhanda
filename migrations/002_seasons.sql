-- Apply after the original schema.sql. Safe to re-run.
CREATE TABLE IF NOT EXISTS season_results (
    season_id BIGINT NOT NULL REFERENCES seasons(id),
    telegram_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    final_cash BIGINT NOT NULL,
    final_reputation BIGINT NOT NULL,
    final_business_level INTEGER NOT NULL,
    season_rank INTEGER NOT NULL,
    permanent_reward_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (season_id, telegram_id),
    UNIQUE (season_id, season_rank)
);
CREATE TABLE IF NOT EXISTS permanent_assets (
    id BIGSERIAL PRIMARY KEY,
    owner_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
    asset_code TEXT NOT NULL,
    source_season_id BIGINT REFERENCES seasons(id),
    label TEXT NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_id, asset_code, source_season_id)
);
CREATE TABLE IF NOT EXISTS season_settings (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    duration_days INTEGER NOT NULL DEFAULT 7 CHECK (duration_days > 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO season_settings(singleton, duration_days)
VALUES (TRUE, 7) ON CONFLICT (singleton) DO NOTHING;
