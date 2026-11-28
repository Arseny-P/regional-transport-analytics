-- +goose Up
ALTER TABLE graphs ADD COLUMN transport_type TEXT;
UPDATE graphs SET transport_type = 'road';
ALTER TABLE graphs ALTER COLUMN transport_type SET NOT NULL,
    DROP CONSTRAINT graphs_pkey, ADD PRIMARY KEY (job_id, transport_type);

-- +goose Down
ALTER TABLE graphs DROP CONSTRAINT graphs_pkey, ADD PRIMARY KEY (job_id);
ALTER TABLE graphs DROP COLUMN transport_type;
