ALTER TABLE box_battles ADD COLUMN challenger_net_worth BIGINT NOT NULL DEFAULT 0;
ALTER TABLE box_battles ADD COLUMN defender_net_worth BIGINT NOT NULL DEFAULT 0;
ALTER TABLE box_battles ADD COLUMN result_kind TEXT;
