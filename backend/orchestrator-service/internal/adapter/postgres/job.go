package postgres

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"orchestrator-service/internal/domain"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

func (p *DB) GetJob(ctx context.Context, jobID uuid.UUID) (domain.Job, error) {

	var job domain.Job
	job.JobID = jobID
	err := p.pool.QueryRow(ctx, `SELECT region_id,transport_types,job_status,
	p1_latitude,p1_longitude,p2_latitude,p2_longitude 
	FROM jobs WHERE id = $1 `, jobID).Scan(
		&job.RegionID, &job.TransportTypes, &job.Status,
		&job.Point1.Latitude, &job.Point1.Longitude, &job.Point2.Latitude, &job.Point2.Longitude,
	)
	if err != nil {
		switch {
		case errors.Is(err, pgx.ErrNoRows):
			return domain.Job{}, domain.ErrJobNotFound
		default:
			return domain.Job{}, fmt.Errorf("get job: %w: %w", domain.ErrInternalDB, err)
		}
	}

	return job, nil
}

func (p *DB) CreateJob(ctx context.Context, job *domain.Job) error {
	tx, err := p.pool.Begin(ctx)

	if err != nil {
		return fmt.Errorf("begin job transaction: %w: %w", domain.ErrInternalDB, err)
	}

	defer func() {
		_ = tx.Rollback(ctx)

	}()

	_, err = tx.Exec(ctx, `INSERT INTO jobs (id,region_id,transport_types,job_status,
	p1_latitude,p1_longitude,
	p2_latitude,p2_longitude
	) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, job.JobID, job.RegionID, job.TransportTypes, job.Status,
		job.Point1.Latitude, job.Point1.Longitude, job.Point2.Latitude, job.Point2.Longitude,
	)

	if err != nil {
		if pgErr, ok := err.(*pgconn.PgError); ok {
			if pgErr.Code == "23505" {
				return domain.ErrJobConflict
			}
		}
		return fmt.Errorf("insert job: %w: %w", domain.ErrInternalDB, err)
	}
	payload, err := json.Marshal(job)
	if err != nil {
		return fmt.Errorf("encode outbox payload: %w: %w", domain.ErrInternalServer, err)
	}
	_, err = tx.Exec(ctx, `INSERT INTO outbox (job_id,command_type,payload) VALUES($1,$2,$3)`,
		job.JobID,
		"START",
		payload,
	)
	if err != nil {
		return fmt.Errorf("insert outbox command: %w: %w", domain.ErrInternalDB, err)
	}

	if err = tx.Commit(ctx); err != nil {
		return fmt.Errorf("commit job transaction: %w: %w", domain.ErrInternalDB, err)
	}
	return nil

}
