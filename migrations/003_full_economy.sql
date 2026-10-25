-- EMPIRE CENTURY expansion migration. Apply after schema.sql and 002_seasons.sql.
ALTER TABLE players
  ADD COLUMN IF NOT EXISTS gold_grams NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (gold_grams >= 0),
  ADD COLUMN IF NOT EXISTS stocks BIGINT NOT NULL DEFAULT 0 CHECK (stocks >= 0),
  ADD COLUMN IF NOT EXISTS determination INTEGER NOT NULL DEFAULT 0 CHECK (determination BETWEEN 0 AND 2000),
  ADD COLUMN IF NOT EXISTS vip_level INTEGER NOT NULL DEFAULT 0 CHECK (vip_level BETWEEN 0 AND 10),
  ADD COLUMN IF NOT EXISTS frozen BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS board_unlocked BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS asset_catalog (
  id BIGSERIAL PRIMARY KEY,
  asset_key TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  category TEXT NOT NULL CHECK (category IN ('luxury','vehicle','collection','permanent')),
  price BIGINT NOT NULL CHECK (price >= 0),
  net_worth BIGINT NOT NULL CHECK (net_worth >= 0),
  operation_bonus INTEGER NOT NULL DEFAULT 0 CHECK (operation_bonus >= 0),
  description TEXT NOT NULL DEFAULT '',
  permanent_eligible BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS player_assets (
  id BIGSERIAL PRIMARY KEY,
  player_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
  asset_id BIGINT NOT NULL REFERENCES asset_catalog(id),
  quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
  acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  permanent BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE(player_id, asset_id, permanent)
);
CREATE INDEX IF NOT EXISTS player_assets_owner_idx ON player_assets(player_id);
CREATE TABLE IF NOT EXISTS clubs (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  tag TEXT NOT NULL UNIQUE,
  owner_id BIGINT NOT NULL REFERENCES players(telegram_id),
  treasury BIGINT NOT NULL DEFAULT 0 CHECK (treasury >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS club_members (
  club_id BIGINT NOT NULL REFERENCES clubs(id) ON DELETE CASCADE,
  player_id BIGINT NOT NULL UNIQUE REFERENCES players(telegram_id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner','officer','member')),
  joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY(club_id, player_id)
);
CREATE TABLE IF NOT EXISTS business_wars (
  id BIGSERIAL PRIMARY KEY,
  attacker_id BIGINT NOT NULL REFERENCES players(telegram_id),
  defender_id BIGINT NOT NULL REFERENCES players(telegram_id),
  winner_id BIGINT REFERENCES players(telegram_id),
  attacker_score BIGINT NOT NULL,
  defender_score BIGINT NOT NULL,
  gold_delta NUMERIC(14,2) NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (attacker_id <> defender_id)
);
CREATE TABLE IF NOT EXISTS industrial_buildings (
  id BIGSERIAL PRIMARY KEY,
  building_key TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  price BIGINT NOT NULL CHECK (price > 0),
  reputation_per_hour INTEGER NOT NULL CHECK (reputation_per_hour > 0),
  operation_bonus INTEGER NOT NULL DEFAULT 0,
  unlock_level INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS player_industries (
  player_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
  building_id BIGINT NOT NULL REFERENCES industrial_buildings(id),
  quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
  last_settled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY(player_id, building_id)
);
CREATE TABLE IF NOT EXISTS club_registration (
  id BIGSERIAL PRIMARY KEY,
  opens_at TIMESTAMPTZ NOT NULL,
  closes_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','matched','closed')),
  CHECK (closes_at > opens_at)
);
CREATE TABLE IF NOT EXISTS club_matches (
  id BIGSERIAL PRIMARY KEY,
  club_a BIGINT NOT NULL REFERENCES clubs(id),
  club_b BIGINT NOT NULL REFERENCES clubs(id),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','finished')),
  winner_club_id BIGINT REFERENCES clubs(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (club_a <> club_b)
);
CREATE TABLE IF NOT EXISTS season_reward_catalog (
  id BIGSERIAL PRIMARY KEY,
  rank_min INTEGER NOT NULL,
  rank_max INTEGER NOT NULL,
  asset_id BIGINT NOT NULL REFERENCES asset_catalog(id),
  UNIQUE(rank_min, rank_max, asset_id),
  CHECK (rank_min > 0 AND rank_max >= rank_min)
);

INSERT INTO asset_catalog(asset_key,name,category,price,net_worth,operation_bonus,description,permanent_eligible)
VALUES
 ('sports_car','Sports Car','vehicle',25000,18000,25,'A high-performance ride for your collection.',FALSE),
 ('penthouse','Skyline Penthouse','luxury',60000,50000,60,'A luxury property with prestige.',FALSE),
 ('watch_collection','Rare Watch Collection','collection',120000,100000,90,'Collectible watches with serious status.',TRUE),
 ('private_jet','Private Jet','vehicle',500000,420000,180,'A private jet for a growing empire.',TRUE),
 ('gold_vault','Gold Vault','permanent',0,25000,100,'A season reward asset. Permanent net-worth value is capped.',TRUE)
ON CONFLICT(asset_key) DO NOTHING;

INSERT INTO industrial_buildings(building_key,name,price,reputation_per_hour,operation_bonus,unlock_level)
VALUES
 ('workshop','Workshop',5000,3,5,1),
 ('factory','Factory',25000,12,20,7),
 ('research_lab','Research Lab',100000,40,60,18),
 ('industrial_park','Industrial Park',500000,150,200,30)
ON CONFLICT(building_key) DO NOTHING;

