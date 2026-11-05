-- +goose Up
ALTER TABLE jobs ADD COLUMN error_code TEXT NOT NULL DEFAULT '';
ALTER TABLE jobs ADD COLUMN error_message TEXT NOT NULL DEFAULT '';

-- +goose Down
ALTER TABLE jobs DROP COLUMN error_code;
ALTER TABLE jobs DROP COLUMN error_message;
