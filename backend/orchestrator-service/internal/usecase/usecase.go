package usecase

import "log/slog"

type Usecase struct {
	jobRepository    JobRepository
	regionRepository RegionRepository
	minIO            MinIO
	logger           *slog.Logger
}

func NewUsecase(store JobRepository, regionRepository RegionRepository, minIO MinIO, logger *slog.Logger) *Usecase {
	return &Usecase{
		jobRepository:    store,
		regionRepository: regionRepository,
		minIO:            minIO,
		logger:           logger,
	}
}
