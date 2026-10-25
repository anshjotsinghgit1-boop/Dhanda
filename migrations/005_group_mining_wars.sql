-- Group-scoped mining wars. Apply after migrations 002, 003 and 004.
CREATE TABLE IF NOT EXISTS group_mining_wars (
  id BIGSERIAL PRIMARY KEY,
  chat_id BIGINT NOT NULL,
  creator_id BIGINT NOT NULL REFERENCES players(telegram_id),
  team_size INTEGER NOT NULL CHECK (team_size IN (3,5)),
  status TEXT NOT NULL DEFAULT 'recruiting' CHECK (status IN ('recruiting','fighting','finished','cancelled')),
  message_id BIGINT,
  winner_team SMALLINT CHECK (winner_team IN (1,2)),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ
);
-- PostgreSQL partial unique index guarantees one open war per group.
CREATE UNIQUE INDEX IF NOT EXISTS one_open_mining_war_per_group
  ON group_mining_wars(chat_id) WHERE status IN ('recruiting','fighting');
CREATE TABLE IF NOT EXISTS mining_war_players (
  war_id BIGINT NOT NULL REFERENCES group_mining_wars(id) ON DELETE CASCADE,
  player_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
  team SMALLINT NOT NULL CHECK (team IN (1,2)),
  joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY(war_id,player_id)
);
CREATE INDEX IF NOT EXISTS mining_war_players_team_idx ON mining_war_players(war_id,team);
