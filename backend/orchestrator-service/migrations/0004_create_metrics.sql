-- +goose Up

CREATE TABLE IF NOT EXISTS metrics(
    job_id UUID PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    metrics JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);




-- +goose Down
DROP TABLE IF EXISTS metrics;