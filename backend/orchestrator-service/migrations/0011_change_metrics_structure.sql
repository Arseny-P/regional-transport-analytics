-- +goose Up
ALTER TABLE metrics ADD COLUMN transport_type TEXT;
UPDATE metrics SET transport_type = 'road';
ALTER TABLE metrics ALTER COLUMN transport_type SET NOT NULL,
    DROP CONSTRAINT metrics_pkey, ADD PRIMARY KEY (job_id, transport_type);

-- +goose Down
ALTER TABLE metrics DROP CONSTRAINT metrics_pkey, ADD PRIMARY KEY (job_id);
ALTER TABLE metrics DROP COLUMN transport_type;
