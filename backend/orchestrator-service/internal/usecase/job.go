package usecase

import (
	"context"
	"errors"
	"fmt"
	"orchestrator-service/internal/domain"
	"orchestrator-service/internal/dto"

	"github.com/google/uuid"
	"github.com/peterstace/simplefeatures/geom"
)

func (u *Usecase) GetAnalysisResult(ctx context.Context, jobID uuid.UUID) (domain.AnalysisResult, error) {
	return u.jobRepository.GetAnalysisResult(ctx, jobID)
}

func (u *Usecase) CreateJob(ctx context.Context, jobID, regionID uuid.UUID,
	p1Latitude, p1Longitude, p2Latitude, p2Longitude float64, transportTypes []domain.Transport) (domain.JobStatus, bool, error) {
	inputJob := domain.Job{
		JobID:          jobID,
		RegionID:       regionID,
		TransportTypes: transportTypes,
		Status:         "queued",
		Point1: domain.MapPoint{
			Latitude:  p1Latitude,
			Longitude: p1Longitude,
		},
		Point2: domain.MapPoint{
			Latitude:  p2Latitude,
			Longitude: p2Longitude,
		},
	}
	databaseJob, err := u.jobRepository.GetJob(ctx, inputJob.JobID)

	if err != nil && !errors.Is(err, domain.ErrJobNotFound) {
		return "", false, err
	}
	if err == nil {
		if !domain.EqualJobs(&inputJob, &databaseJob) {
			return "", false, domain.ErrJobConflict
		}

		u.logger.DebugContext(ctx, "returning existing analysis job",
			"job_id", jobID, "region_id", regionID, "status", databaseJob.Status)
		return databaseJob.Status, false, nil
	}
	objectKey, err := u.regionRepository.GetRegionInfo(ctx, regionID)
	if err != nil {
		return "", false, err
	}
	err = u.minIO.StatObject(ctx, objectKey)
	if err != nil {
		return "", false, err
	}
	region, err := u.minIO.GetObject(ctx, objectKey)
	if err != nil {
		return "", false, err
	}

	boundaries := make([]dto.BoundaryGeometry, 0, len(region.Features))
	for _, feature := range region.Features {
		boundaries = append(boundaries, feature.Geometry)
	}
	regionGeometry, err := mergeRegionGeometries(boundaries)
	if err != nil {
		return "", false, fmt.Errorf("parse stored region geometry: %w: %v", domain.ErrInvalidRegionData, err)
	}
	rectangle := geom.NewEnvelope(geom.XY{
		X: p1Longitude,
		Y: p1Latitude,
	}, geom.XY{
		X: p2Longitude,
		Y: p2Latitude,
	})
	rectangleGeometry := rectangle.AsGeometry()

	isContains, err := geom.Contains(regionGeometry, rectangleGeometry)
	if err != nil {
		return "", false, fmt.Errorf("check analysis boundary: %w: %w", domain.ErrInternalServer, err)
	}
	if !isContains {
		return "", false, domain.ErrAreaOutOfBounds
	}
	err = u.jobRepository.CreateJob(ctx, &inputJob)

	if err != nil {
		switch {
		case errors.Is(err, domain.ErrJobConflict):
			dbJob, dbErr := u.jobRepository.GetJob(ctx, inputJob.JobID)
			if dbErr != nil {
				return "", false, dbErr
			}
			if !domain.EqualJobs(&inputJob, &dbJob) {
				return "", false, domain.ErrJobConflict
			}
			u.logger.DebugContext(ctx, "returning analysis job created by concurrent request",
				"job_id", jobID, "region_id", regionID, "status", dbJob.Status)
			return dbJob.Status, false, nil
		default:
			return "", false, err
		}
	}

	u.logger.InfoContext(ctx, "analysis job queued", "job_id", jobID, "region_id", regionID)
	return "queued", true, nil

}
