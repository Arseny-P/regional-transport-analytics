-- +goose Up
CREATE TABLE IF NOT EXISTS inbox(
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status_message TEXT NOT NULL DEFAULT 'PENDING' CHECK (status_message IN ('PENDING','READY')),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);







-- +goose Down
DROP TABLE IF EXISTS inbox;
