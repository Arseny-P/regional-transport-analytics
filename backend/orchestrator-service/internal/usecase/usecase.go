package usecase

import "log/slog"

type Usecase struct {
	jobRepository JobRepository
	minIO         MinIO
	logger        *slog.Logger
}

func NewUsecase(store JobRepository, minIO MinIO, logger *slog.Logger) *Usecase {
	return &Usecase{
		jobRepository: store,
		minIO:         minIO,
		logger:        logger,
	}
}
