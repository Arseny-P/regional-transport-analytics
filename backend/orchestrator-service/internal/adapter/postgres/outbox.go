package postgres

import (
	"context"
	"encoding/json"
	"fmt"
	"orchestrator-service/internal/domain"

	"github.com/google/uuid"
)

func (p *DB) GetMessages(ctx context.Context, excessMessages []uuid.UUID) ([]domain.OutboxMessage, error) {

	messages := []domain.OutboxMessage{}
	rows, err := p.pool.Query(ctx, `SELECT id,job_id,command_type,payload FROM outbox 
	WHERE status_message = 'PENDING' AND job_id <> ALL($1::uuid[]) 
	ORDER BY created_at
	 LIMIT 5`, excessMessages)
	if err != nil {
		return nil, fmt.Errorf("read outbox: %w: %w", domain.ErrInternalDB, err)
	}

	defer rows.Close()
	var commandType string
	var id uuid.UUID
	var jobID uuid.UUID
	payload := []byte{}
	for rows.Next() {
		scanErr := rows.Scan(&id, &jobID, &commandType, &payload)
		if scanErr != nil {
			return nil, fmt.Errorf("scan outbox message: %w: %w", domain.ErrInternalDB, scanErr)
		}

		var job domain.Job
		unmarshalErr := json.Unmarshal(payload, &job)
		if unmarshalErr != nil {
			return nil, fmt.Errorf("decode outbox message %s: %w: %w", id, domain.ErrInternalServer, unmarshalErr)

		}

		messages = append(messages, domain.OutboxMessage{
			ID:             id,
			JobID:          jobID,
			CommandType:    commandType,
			Point1:         job.Point1,
			Point2:         job.Point2,
			TransportTypes: job.TransportTypes,
		})
	}

	if err = rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate outbox: %w: %w", domain.ErrInternalDB, err)
	}

	return messages, nil

}

func (p *DB) SetReadyOutboxMessage(ctx context.Context, id uuid.UUID) error {
	result, err := p.pool.Exec(ctx, `UPDATE outbox SET status_message = 'READY' WHERE id = $1 `, id)
	if err != nil {
		return fmt.Errorf("mark outbox message READY: %w: %w", domain.ErrInternalDB, err)
	}
	if result.RowsAffected() == 0 {
		return domain.ErrOutboxMessageNotFound
	}
	return nil
}
