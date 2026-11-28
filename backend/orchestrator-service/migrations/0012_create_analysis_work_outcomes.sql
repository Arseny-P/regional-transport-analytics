-- +goose Up

CREATE TABLE analysis_work_outcomes (
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    transport_type TEXT NOT NULL,
    error_code TEXT NOT NULL,
    error_message TEXT NOT NULL,
    PRIMARY KEY (job_id, transport_type)
);

INSERT INTO analysis_work_outcomes (job_id, transport_type, error_code, error_message)
SELECT id, unnest(transport_types), error_code, error_message
FROM jobs
WHERE job_status IN ('completed', 'failed') OR error_code <> '' OR error_message <> ''
ON CONFLICT (job_id, transport_type) DO NOTHING;

-- +goose Down
DROP TABLE analysis_work_outcomes;
