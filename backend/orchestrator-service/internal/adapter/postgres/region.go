package postgres

import (
	"context"
	"errors"
	"fmt"
	"orchestrator-service/internal/domain"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
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

func (p *DB) CreateRegionInfo(ctx context.Context, key domain.ObjectKey, regionID uuid.UUID) error {
	_, err := p.pool.Exec(ctx, `INSERT INTO regions (id, object_key) VALUES ($1, $2)`, regionID, key)
	if err != nil {
		var pgErr *pgconn.PgError
		if pgconn.SafeToRetry(err) || (errors.As(err, &pgErr) &&
			(strings.HasPrefix(pgErr.Code, "23") || pgErr.Code == "40001" || pgErr.Code == "40P01")) {
			return fmt.Errorf("create region: %w: %w: %w", domain.ErrInternalDB, domain.ErrRegionInsertRejected, err)
		}
		return fmt.Errorf("create region: %w: %w", domain.ErrInternalDB, err)
	}
	return nil
}

func (p *DB) GetRegionsInfo(ctx context.Context) ([]domain.RegionRecord, error) {
	rows, err := p.pool.Query(ctx, `SELECT id, object_key FROM regions ORDER BY created_at, id`)
	if err != nil {
		return nil, fmt.Errorf("get regions: %w: %w", domain.ErrInternalDB, err)
	}
	defer rows.Close()

	regions := make([]domain.RegionRecord, 0)
	for rows.Next() {
		var region domain.RegionRecord
		if err := rows.Scan(&region.ID, &region.ObjectKey); err != nil {
			return nil, fmt.Errorf("scan region: %w: %w", domain.ErrInternalDB, err)
		}
		regions = append(regions, region)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("read regions: %w: %w", domain.ErrInternalDB, err)
	}
	return regions, nil
}
