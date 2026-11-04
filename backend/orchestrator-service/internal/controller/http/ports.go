package httpcontroller

import (
	"context"
	"orchestrator-service/internal/domain"
	"orchestrator-service/internal/dto"

	"github.com/google/uuid"
)

type UsecaseOrchestrator interface {
	AddRegion(context.Context, string, string, dto.RegionFeatureCollection) (domain.Region, error)
	GetRegions(context.Context) ([]domain.RegionInfo, error)
	GetRegion(context.Context, uuid.UUID) (domain.Region, error)
	GetAnalysisResult(context.Context, uuid.UUID) (domain.AnalysisResult, error)
	CreateJob(context.Context, uuid.UUID, uuid.UUID, float64, float64, float64, float64, []domain.Transport) (domain.JobStatus, bool, error)
}
