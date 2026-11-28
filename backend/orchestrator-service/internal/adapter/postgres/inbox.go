package postgres

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"orchestrator-service/internal/domain"
	"slices"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

func (p *DB) CreateAnalysisRes(ctx context.Context, inboxMessage *domain.InboxMessage) error {
	tx, err := p.pool.Begin(ctx)
	if err != nil {
		return fmt.Errorf("begin inbox transaction: %w: %w", domain.ErrInternalDB, err)
	}

	defer func() { _ = tx.Rollback(ctx) }()

	inboxInsert, err := tx.Exec(ctx, `INSERT INTO inbox (id,job_id)
		VALUES($1,$2) ON CONFLICT (id) DO NOTHING`, inboxMessage.MessageID, inboxMessage.JobID)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == "23503" {
			return fmt.Errorf("insert inbox message: %w: %w", domain.ErrJobNotFound, err)
		}
		return fmt.Errorf("insert inbox message: %w: %w", domain.ErrInternalDB, err)
	}
	if inboxInsert.RowsAffected() == 0 {
		return nil
	}

	var jobStatus domain.JobStatus
	var transports []domain.Transport
	err = tx.QueryRow(ctx, `SELECT job_status, transport_types FROM jobs WHERE id = $1 FOR NO KEY UPDATE`,
		inboxMessage.JobID).Scan(&jobStatus, &transports)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return fmt.Errorf("read analysis job status: %w: %w", domain.ErrJobNotFound, err)
		}
		return fmt.Errorf("read analysis job status: %w: %w", domain.ErrInternalDB, err)
	}

	err = applyAnalysisMessage(ctx, tx, inboxMessage, jobStatus, transports)
	if err != nil {
		return err
	}

	if err = tx.Commit(ctx); err != nil {
		return fmt.Errorf("commit inbox transaction: %w: %w", domain.ErrInternalDB, err)
	}
	return nil
}

func applyAnalysisMessage(ctx context.Context, tx pgx.Tx, message *domain.InboxMessage, jobStatus domain.JobStatus, transports []domain.Transport) error {
	payload := message.Payload
	if jobStatus == "canceled" || (jobStatus == "cancel_requested" && payload.Status != "canceled") {
		return nil
	}

	transport := message.TransportType
	if transport != "" && !slices.Contains(transports, transport) {
		return fmt.Errorf("%w: transport_type %q was not requested for job %s", domain.ErrInvalidKafkaMessage, transport, message.JobID)
	}

	if message.Type == "STATUS" {
		if jobStatus == "completed" || jobStatus == "failed" {
			return nil
		}
		return updateAnalysisStatus(ctx, tx, message.JobID, payload.Status)
	}

	if transport == "" && len(transports) == 1 {
		transport = transports[0]
	}
	reported := []domain.Transport{transport}
	if transport == "" {
		if payload.Status != "failed" || payload.Error == nil || payload.Graph != nil || len(payload.Metrics) != 0 ||
			(payload.Error.Code != "unsupported_transport" && payload.Error.Code != "invalid_parameters") {
			return fmt.Errorf("%w: transport_type is required for a result with multiple requested transports", domain.ErrInvalidKafkaMessage)
		}
		reported = transports
	}

	return saveAnalysisWorkResult(ctx, tx, message, jobStatus, reported, transports)
}

func saveAnalysisWorkResult(ctx context.Context, tx pgx.Tx, message *domain.InboxMessage, jobStatus domain.JobStatus, reported, requested []domain.Transport) error {
	var failure domain.ErrorResp
	if message.Payload.Error != nil {
		failure = *message.Payload.Error
	}
	insert, err := tx.Exec(ctx, `INSERT INTO analysis_work_outcomes (job_id,transport_type,error_code,error_message)
		SELECT $1::uuid, unnest($2::text[]), $3::text, $4::text
		ON CONFLICT (job_id,transport_type) DO NOTHING`,
		message.JobID, reported, failure.Code, failure.Message)
	if err != nil {
		return fmt.Errorf("save transport outcome: %w: %w", domain.ErrInternalDB, err)
	}
	if insert.RowsAffected() == 0 {
		return nil
	}
	if len(reported) == 1 {
		err = saveAnalysisGraphAndMetrics(ctx, tx, message, reported[0])
		if err != nil {
			return err
		}
	}
	if jobStatus == "completed" {
		return nil
	}
	return updateAnalysisResultStatus(ctx, tx, message.JobID, requested)
}

func updateAnalysisResultStatus(ctx context.Context, tx pgx.Tx, jobID uuid.UUID, requested []domain.Transport) error {
	var finishedCount int
	err := tx.QueryRow(ctx, `SELECT count(*) FROM analysis_work_outcomes
		WHERE job_id = $1 AND transport_type = ANY($2::text[])`, jobID, requested).Scan(&finishedCount)
	if err != nil {
		return fmt.Errorf("count transport outcomes: %w: %w", domain.ErrInternalDB, err)
	}
	if finishedCount < len(requested) {
		return updateAnalysisStatus(ctx, tx, jobID, "running")
	}

	var hasGraph bool
	err = tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM graphs
		WHERE job_id = $1 AND transport_type = ANY($2::text[]))`, jobID, requested).Scan(&hasGraph)
	if err != nil {
		return fmt.Errorf("check saved analysis graphs: %w: %w", domain.ErrInternalDB, err)
	}
	if hasGraph {
		return updateAnalysisStatus(ctx, tx, jobID, "completed")
	}
	return updateAnalysisStatus(ctx, tx, jobID, "failed")
}

func updateAnalysisStatus(ctx context.Context, tx pgx.Tx, jobID uuid.UUID, status domain.JobStatus) error {
	_, err := tx.Exec(ctx, `UPDATE jobs SET job_status = $1 WHERE id = $2 AND job_status <> $1`, status, jobID)
	if err != nil {
		return fmt.Errorf("update analysis job status: %w: %w", domain.ErrInternalDB, err)
	}
	return nil
}

func saveAnalysisGraphAndMetrics(ctx context.Context, tx pgx.Tx, inboxMessage *domain.InboxMessage, transport domain.Transport) error {
	if inboxMessage.Payload.Graph != nil {
		graphPayload, marshalErr := json.Marshal(inboxMessage.Payload.Graph)
		if marshalErr != nil {
			return fmt.Errorf("encode analysis graph: %w: %w", domain.ErrInternalServer, marshalErr)
		}
		_, graphInsertErr := tx.Exec(ctx, `INSERT INTO graphs (job_id,transport_type,graph) VALUES($1,$2,$3)
			ON CONFLICT (job_id,transport_type) DO UPDATE SET graph = EXCLUDED.graph`,
			inboxMessage.JobID, transport, graphPayload)
		if graphInsertErr != nil {
			return fmt.Errorf("save analysis graph: %w: %w", domain.ErrInternalDB, graphInsertErr)
		}
	}
	if inboxMessage.Payload.Metrics != nil && (inboxMessage.Payload.Status != "failed" || len(inboxMessage.Payload.Metrics) > 0) {
		metricsPayload, marshalErr := json.Marshal(inboxMessage.Payload.Metrics)
		if marshalErr != nil {
			return fmt.Errorf("encode analysis metrics: %w: %w", domain.ErrInternalServer, marshalErr)
		}
		_, metricsInsertErr := tx.Exec(ctx, `INSERT INTO metrics (job_id,transport_type,metrics) VALUES($1,$2,$3)
			ON CONFLICT (job_id,transport_type) DO UPDATE SET metrics = EXCLUDED.metrics`,
			inboxMessage.JobID, transport, metricsPayload)
		if metricsInsertErr != nil {
			return fmt.Errorf("save analysis metrics: %w: %w", domain.ErrInternalDB, metricsInsertErr)
		}
	}
	return nil
}
