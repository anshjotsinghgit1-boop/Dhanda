-- EMPIRE CENTURY timed mining and club battles (MVP).
ALTER TABLE players
  ADD COLUMN IF NOT EXISTS collection_boost NUMERIC(5,2) NOT NULL DEFAULT 1.0,
  ADD COLUMN IF NOT EXISTS collection_boost_until TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS club_battle_wins INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS empire_level INTEGER NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS mining_groups (
  chat_id BIGINT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT 'Mining group',
  registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS timed_mining_events (
  id BIGSERIAL PRIMARY KEY,
  chat_id BIGINT NOT NULL REFERENCES mining_groups(chat_id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'joining' CHECK (status IN ('joining','fighting','finished','skipped')),
  opens_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  closes_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '5 minutes'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS one_live_timed_mining_per_group
 ON timed_mining_events(chat_id) WHERE status IN ('joining','fighting');
CREATE TABLE IF NOT EXISTS timed_mining_players (
  event_id BIGINT NOT NULL REFERENCES timed_mining_events(id) ON DELETE CASCADE,
  player_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
  joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY(event_id, player_id)
);
CREATE TABLE IF NOT EXISTS club_battle_queue (
  player_id BIGINT PRIMARY KEY REFERENCES players(telegram_id) ON DELETE CASCADE,
  joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS club_battles (
  id BIGSERIAL PRIMARY KEY,
  player_a BIGINT NOT NULL REFERENCES players(telegram_id),
  player_b BIGINT NOT NULL REFERENCES players(telegram_id),
  match_number SMALLINT NOT NULL CHECK (match_number IN (1,2)),
  round_number SMALLINT NOT NULL DEFAULT 1 CHECK (round_number BETWEEN 1 AND 3),
  wins_a SMALLINT NOT NULL DEFAULT 0,
  wins_b SMALLINT NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','finished')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  CHECK (player_a <> player_b)
);
CREATE TABLE IF NOT EXISTS club_battle_rounds (
  id BIGSERIAL PRIMARY KEY,
  battle_id BIGINT NOT NULL REFERENCES club_battles(id) ON DELETE CASCADE,
  round_number SMALLINT NOT NULL,
  player_id BIGINT NOT NULL REFERENCES players(telegram_id),
  box_kind TEXT NOT NULL CHECK (box_kind IN ('money','empty','normal')),
  temporary_net_worth BIGINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(battle_id, round_number, player_id)
);
CREATE INDEX IF NOT EXISTS club_battles_players_idx ON club_battles(player_a,player_b,status);
