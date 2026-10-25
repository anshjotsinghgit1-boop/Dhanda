CREATE TABLE IF NOT EXISTS timed_mining_rounds (
  event_id BIGINT NOT NULL REFERENCES timed_mining_events(id) ON DELETE CASCADE,
  round_number SMALLINT NOT NULL CHECK (round_number BETWEEN 1 AND 4),
  player_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
  box_kind TEXT NOT NULL CHECK (box_kind IN ('money','empty','normal')),
  temporary_net_worth BIGINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY(event_id,round_number,player_id)
);
