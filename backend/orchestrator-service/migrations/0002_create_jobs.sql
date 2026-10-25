-- +goose Up
CREATE TABLE IF NOT EXISTS jobs(
    id UUID PRIMARY KEY,
    region_id UUID NOT NULL REFERENCES regions(id) ON DELETE CASCADE,
    transport_types TEXT[] NOT NULL,
    job_status VARCHAR(16) NOT NULL CHECK (job_status IN ('queued','completed','canceled','failed','running','cancel_requested')),
    p1_latitude FLOAT NOT NULL,
    p1_longitude FLOAT NOT NULL,
    p2_latitude FLOAT NOT NULL,
    p2_longitude FLOAT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT point_values CHECK (p1_latitude BETWEEN -90 AND 90 
    AND p1_longitude BETWEEN -180 AND 180
    AND p2_latitude BETWEEN -90 AND 90 
    AND p2_longitude BETWEEN -180 AND 180),
    CHECK (cardinality(transport_types) BETWEEN 1 AND 3 AND transport_types <@ ARRAY['rail','sea','road'])
);



-- +goose Down
DROP TABLE IF EXISTS jobs;