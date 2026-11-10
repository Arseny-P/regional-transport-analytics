-- +goose Up
ALTER TABLE regions ALTER COLUMN object_key TYPE TEXT;

-- +goose Down
ALTER TABLE regions ADD CONSTRAINT regions_object_key_rollback_length CHECK (char_length(object_key) <= 128);
ALTER TABLE regions ALTER COLUMN object_key TYPE VARCHAR(128);
ALTER TABLE regions DROP CONSTRAINT regions_object_key_rollback_length;
