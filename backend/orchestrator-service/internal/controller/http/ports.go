package httpcontroller

import (
	"context"
	"orchestrator-service/internal/domain"
	"orchestrator-service/internal/dto"
	"time"

	"github.com/google/uuid"
)

type HeartbeatWorker interface {
	UpdateHeartbeat(uuid.UUID, time.Time, time.Time) error
	GetHeartbeatResponse(context.Context, uuid.UUID) (domain.HeartbeatResponse, error)
}

type RegionUsecase interface {
	AddRegion(context.Context, string, string, dto.RegionFeatureCollection) (domain.Region, error)
	GetRegions(context.Context) ([]domain.RegionInfo, error)
	GetRegion(context.Context, uuid.UUID) (domain.Region, error)
}

type JobUsecase interface {
	GetAnalysisResult(context.Context, uuid.UUID) (domain.AnalysisResult, error)
	CancelJob(context.Context, uuid.UUID) (domain.AnalysisResult, bool, error)
	CreateJob(context.Context, uuid.UUID, uuid.UUID, float64, float64, float64, float64, []domain.Transport) (domain.JobStatus, bool, error)
}
