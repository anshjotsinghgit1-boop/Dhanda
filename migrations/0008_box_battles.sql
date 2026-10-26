CREATE TABLE IF NOT EXISTS box_layouts (
    player_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
    layout_no INTEGER NOT NULL CHECK (layout_no BETWEEN 1 AND 5),
    outcomes TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (player_id, layout_no)
);
CREATE TABLE IF NOT EXISTS box_battles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenger_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
    defender_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
    outcomes TEXT NOT NULL,
    picked TEXT NOT NULL DEFAULT '[]',
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    round_no INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS box_battles_active_idx ON box_battles(challenger_id, status);
