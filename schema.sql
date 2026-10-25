CREATE TABLE IF NOT EXISTS players (
    telegram_id BIGINT PRIMARY KEY,
    username TEXT,
    display_name TEXT NOT NULL DEFAULT 'Player',
    cash BIGINT NOT NULL DEFAULT 1000 CHECK (cash >= 0),
    reputation BIGINT NOT NULL DEFAULT 0 CHECK (reputation >= 0),
    business_level INTEGER NOT NULL DEFAULT 1 CHECK (business_level BETWEEN 1 AND 54),
    last_collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    season_id BIGINT NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS employees (
    employee_id BIGINT PRIMARY KEY REFERENCES players(telegram_id) ON DELETE CASCADE,
    boss_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
    hired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (employee_id <> boss_id)
);
CREATE INDEX IF NOT EXISTS employees_boss_id_idx ON employees(boss_id);
CREATE TABLE IF NOT EXISTS seasons (
    id BIGSERIAL PRIMARY KEY,
    starts_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ends_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '7 days'),
    settled_at TIMESTAMPTZ
);
INSERT INTO seasons (id, starts_at, ends_at)
SELECT 1, NOW(), NOW() + INTERVAL '7 days'
WHERE NOT EXISTS (SELECT 1 FROM seasons);
