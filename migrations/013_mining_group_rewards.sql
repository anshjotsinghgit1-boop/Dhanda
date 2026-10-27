-- Group-scoped mining rewards and observed group membership for mining rankings.
CREATE TABLE IF NOT EXISTS mining_group_members (
  chat_id BIGINT NOT NULL REFERENCES mining_groups(chat_id) ON DELETE CASCADE,
  player_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY(chat_id, player_id)
);
CREATE INDEX IF NOT EXISTS mining_group_members_player_idx ON mining_group_members(player_id);
CREATE TABLE IF NOT EXISTS mining_group_rewards (
  chat_id BIGINT PRIMARY KEY REFERENCES mining_groups(chat_id) ON DELETE CASCADE,
  event_id BIGINT NOT NULL REFERENCES timed_mining_events(id) ON DELETE CASCADE,
  expires_at TIMESTAMPTZ NOT NULL,
  awarded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS mining_group_reward_players (
  chat_id BIGINT NOT NULL,
  event_id BIGINT NOT NULL,
  player_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
  PRIMARY KEY(chat_id, event_id, player_id),
  FOREIGN KEY(chat_id) REFERENCES mining_groups(chat_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS mining_group_rewards_expiry_idx ON mining_group_rewards(expires_at);
