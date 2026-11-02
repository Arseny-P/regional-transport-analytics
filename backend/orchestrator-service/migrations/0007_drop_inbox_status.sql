-- +goose Up
ALTER TABLE inbox DROP COLUMN status_message;

-- +goose Down
ALTER TABLE inbox ADD COLUMN status_message TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status_message IN ('PENDING','READY'));
