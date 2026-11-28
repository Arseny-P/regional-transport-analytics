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

func (p *DB) GetAnalysisResult(ctx context.Context, jobID uuid.UUID, transports []domain.Transport) (domain.AnalysisResult, error) {
	result := domain.AnalysisResult{JobID: jobID}
	tx, err := p.pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		return domain.AnalysisResult{}, fmt.Errorf("begin analysis read: %w: %w", domain.ErrInternalDB, err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	var requested []domain.Transport
	err = tx.QueryRow(ctx, `SELECT job_status, transport_types FROM jobs WHERE id = $1`, jobID).
		Scan(&result.Payload.Status, &requested)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return domain.AnalysisResult{}, domain.ErrJobNotFound
		}
		return domain.AnalysisResult{}, fmt.Errorf("read analysis job: %w: %w", domain.ErrInternalDB, err)
	}

	works := make(map[domain.Transport]*domain.WorksRes, len(requested))
	for _, transport := range requested {
		work := &domain.WorksRes{TransportType: transport}
		works[transport] = work
		result.WorkResults = append(result.WorkResults, work)
	}
	err = readAnalysisWorks(ctx, tx, jobID, transports, works)
	if err != nil {
		return domain.AnalysisResult{}, err
	}
	if err = tx.Commit(ctx); err != nil {
		return domain.AnalysisResult{}, fmt.Errorf("commit analysis read: %w: %w", domain.ErrInternalDB, err)
	}

	if len(result.WorkResults) == 1 {
		result.Payload.Graph = result.WorkResults[0].Payload.Graph
		result.Payload.Metrics = result.WorkResults[0].Payload.Metrics
	}
	return result, nil
}

func readAnalysisWorks(ctx context.Context, tx pgx.Tx, jobID uuid.UUID, transports []domain.Transport, works map[domain.Transport]*domain.WorksRes) error {
	rows, err := tx.Query(ctx, `
		SELECT transport_type, 'graph',
			CASE WHEN $2::text[] IS NULL OR transport_type = ANY($2) THEN graph END
		FROM graphs WHERE job_id = $1
		UNION ALL
		SELECT transport_type, 'metrics',
			CASE WHEN $2::text[] IS NULL OR transport_type = ANY($2) THEN metrics END
		FROM metrics WHERE job_id = $1
		UNION ALL
		SELECT transport_type, 'error', jsonb_build_object('code', error_code, 'message', error_message)
		FROM analysis_work_outcomes WHERE job_id = $1 AND (error_code <> '' OR error_message <> '')
	`, jobID, transports)
	if err != nil {
		return fmt.Errorf("query transport results: %w: %w", domain.ErrInternalDB, err)
	}
	var transport domain.Transport
	var kind string
	var data []byte
	_, err = pgx.ForEachRow(rows, []any{&transport, &kind, &data}, func() error {
		work := works[transport]
		if work == nil {
			return nil
		}
		var target any
		switch kind {
		case "graph":
			work.GraphAvailable = true
			target = &work.Payload.Graph
		case "metrics":
			work.MetricsAvailable = true
			target = &work.Payload.Metrics
		case "error":
			target = &work.Payload.Error
		}
		if data == nil {
			return nil
		}
		return json.Unmarshal(data, target)
	})
	if err != nil {
		return fmt.Errorf("read transport results: %w: %w", domain.ErrInternalDB, err)
	}
	return nil
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
	err = insertOutboxCommand(ctx, tx, job.JobID, "START", payload)

	if err != nil {
		return err
	}

	err = tx.Commit(ctx)
	if err != nil {
		return fmt.Errorf("commit job transaction: %w: %w", domain.ErrInternalDB, err)
	}
	return nil

}

func (p *DB) RequestJobCancellation(ctx context.Context, jobID uuid.UUID) (domain.JobStatus, error) {
	tx, err := p.pool.Begin(ctx)
	if err != nil {
		return "", fmt.Errorf("begin cancellation transaction: %w: %w", domain.ErrInternalDB, err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	var status domain.JobStatus
	err = tx.QueryRow(ctx, `SELECT job_status FROM jobs WHERE id = $1 FOR UPDATE`, jobID).Scan(&status)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return "", domain.ErrJobNotFound
		}
		return "", fmt.Errorf("lock job for cancellation: %w: %w", domain.ErrInternalDB, err)
	}

	if status != "queued" && status != "running" {
		return status, nil
	}
	_, err = tx.Exec(ctx, `UPDATE jobs SET job_status = 'cancel_requested' WHERE id = $1`, jobID)
	if err != nil {
		return "", fmt.Errorf("request job cancellation: %w: %w", domain.ErrInternalDB, err)
	}

	err = insertOutboxCommand(ctx, tx, jobID, "CANCEL", []byte(`{}`))
	if err != nil {
		return "", err
	}

	err = tx.Commit(ctx)
	if err != nil {
		return "", fmt.Errorf("commit cancellation transaction: %w: %w", domain.ErrInternalDB, err)
	}
	return "cancel_requested", nil
}
