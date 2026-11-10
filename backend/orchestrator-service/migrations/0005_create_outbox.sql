-- +goose Up
CREATE TABLE IF NOT EXISTS outbox(
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    command_type TEXT NOT NULL CHECK (command_type IN ('START', 'CANCEL')),
    payload JSONB NOT NULL,
    status_message TEXT NOT NULL DEFAULT 'PENDING' CHECK (status_message IN ('PENDING','READY')),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);


CREATE INDEX IF NOT EXISTS idx_outbox_pending_created_at ON outbox(created_at)
    WHERE status_message = 'PENDING';




-- +goose Down
DROP TABLE IF EXISTS outbox;
