CREATE TABLE IF NOT EXISTS box_layout_drafts (
    player_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
    layout_no INTEGER NOT NULL CHECK (layout_no BETWEEN 1 AND 5),
    outcomes TEXT NOT NULL,
    PRIMARY KEY (player_id, layout_no)
);