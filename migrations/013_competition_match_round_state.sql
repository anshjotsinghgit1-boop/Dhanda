-- Round state for the level-specific two-opponent competition engine.
ALTER TABLE club_competition_matches ADD COLUMN layout_a TEXT;
ALTER TABLE club_competition_matches ADD COLUMN layout_b TEXT;
ALTER TABLE club_competition_matches ADD COLUMN picked_a INTEGER;
ALTER TABLE club_competition_matches ADD COLUMN picked_b INTEGER;
ALTER TABLE club_competition_matches ADD COLUMN deadline_at TIMESTAMPTZ;
