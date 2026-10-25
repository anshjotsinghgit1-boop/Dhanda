-- Apply after migrations 002 and 003.
CREATE TABLE IF NOT EXISTS employee_challenges (
  id BIGSERIAL PRIMARY KEY,
  boss_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
  employee_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','declined','expired')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW()+INTERVAL '24 hours'),
  resolved_at TIMESTAMPTZ,
  CHECK(boss_id <> employee_id)
);
CREATE INDEX IF NOT EXISTS employee_challenges_target_idx ON employee_challenges(employee_id,status);
CREATE TABLE IF NOT EXISTS stock_market (
  symbol TEXT PRIMARY KEY,
  company_name TEXT NOT NULL,
  price BIGINT NOT NULL CHECK(price > 0),
  volatility_pct INTEGER NOT NULL DEFAULT 5 CHECK(volatility_pct BETWEEN 1 AND 50),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS stock_transactions (
  id BIGSERIAL PRIMARY KEY,
  player_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
  symbol TEXT NOT NULL REFERENCES stock_market(symbol),
  shares INTEGER NOT NULL CHECK(shares <> 0),
  price_each BIGINT NOT NULL CHECK(price_each > 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO stock_market(symbol,company_name,price,volatility_pct) VALUES
 ('ECOR','Empire Core Industries',250,5),
 ('NOVA','Nova Systems',500,8),
 ('VYBE','Vybe Consumer Group',120,10),
 ('AURA','Aura Luxury Holdings',900,6)
ON CONFLICT(symbol) DO NOTHING;
