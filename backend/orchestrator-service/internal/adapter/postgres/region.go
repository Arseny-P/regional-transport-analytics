package postgres

import (
	"context"
	"errors"
	"fmt"
	"orchestrator-service/internal/domain"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

func (p *DB) GetRegionInfo(ctx context.Context, regionID uuid.UUID) (domain.ObjectKey, error) {

	var objectKey domain.ObjectKey

	err := p.pool.QueryRow(ctx, `SELECT object_key FROM regions WHERE id = $1`, regionID).Scan(&objectKey)

	if err != nil {
		switch {
		case errors.Is(err, pgx.ErrNoRows):
			return "", domain.ErrRegionNotFound
		default:
			return "", fmt.Errorf("get region: %w: %w", domain.ErrInternalDB, err)
		}
	}
	return objectKey, nil
}
