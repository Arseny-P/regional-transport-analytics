-- +goose Up
CREATE TABLE IF NOT EXISTS graphs(
    job_id UUID PRIMARY KEY  REFERENCES jobs(id) ON DELETE CASCADE,
    graph JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);






-- +goose Down
DROP TABLE IF EXISTS graphs;