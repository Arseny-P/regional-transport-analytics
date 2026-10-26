-- +goose Up
CREATE TABLE IF NOT EXISTS regions(
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_key VARCHAR(128) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);






-- +goose Down
DROP TABLE IF EXISTS regions;