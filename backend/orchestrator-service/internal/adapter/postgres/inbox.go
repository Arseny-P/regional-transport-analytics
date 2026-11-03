package postgres

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"orchestrator-service/internal/domain"

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

	var errorCode, errorMessage string
	if inboxMessage.Payload.Error != nil {
		errorCode = inboxMessage.Payload.Error.Code
		errorMessage = inboxMessage.Payload.Error.Message
	}
	jobUpdate, err := tx.Exec(ctx, `UPDATE jobs SET job_status = $1, error_code = $2, error_message = $3 WHERE id = $4`,
		string(inboxMessage.Payload.Status), errorCode, errorMessage, inboxMessage.JobID)
	if err != nil {
		return fmt.Errorf("update analysis job status: %w: %w", domain.ErrInternalDB, err)
	}
	if jobUpdate.RowsAffected() == 0 {
		return domain.ErrJobNotFound
	}

	if inboxMessage.Payload.Graph != nil {
		graphPayload, marshalErr := json.Marshal(inboxMessage.Payload.Graph)
		if marshalErr != nil {
			return fmt.Errorf("encode analysis graph: %w: %w", domain.ErrInternalServer, marshalErr)
		}
		_, graphInsertErr := tx.Exec(ctx, `INSERT INTO graphs (job_id,graph) VALUES($1,$2)
			ON CONFLICT (job_id) DO UPDATE SET graph = EXCLUDED.graph`,
			inboxMessage.JobID, graphPayload)
		if graphInsertErr != nil {
			return fmt.Errorf("save analysis graph: %w: %w", domain.ErrInternalDB, graphInsertErr)
		}
	}
	if inboxMessage.Payload.Metrics != nil {
		metricsPayload, marshalErr := json.Marshal(inboxMessage.Payload.Metrics)
		if marshalErr != nil {
			return fmt.Errorf("encode analysis metrics: %w: %w", domain.ErrInternalServer, marshalErr)
		}
		_, metricsInsertErr := tx.Exec(ctx, `INSERT INTO metrics (job_id,metrics) VALUES($1,$2)
			ON CONFLICT (job_id) DO UPDATE SET metrics = EXCLUDED.metrics`,
			inboxMessage.JobID, metricsPayload)
		if metricsInsertErr != nil {
			return fmt.Errorf("save analysis metrics: %w: %w", domain.ErrInternalDB, metricsInsertErr)
		}
	}

	if err = tx.Commit(ctx); err != nil {
		return fmt.Errorf("commit inbox transaction: %w: %w", domain.ErrInternalDB, err)
	}
	return nil
}
