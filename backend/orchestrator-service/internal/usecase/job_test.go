package usecase

import (
	"context"
	"log/slog"
	"orchestrator-service/internal/domain"
	miniodto "orchestrator-service/internal/dto/minio"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

type MockJobRepository struct {
	storage   map[uuid.UUID]domain.Job
	createErr error
}

func (mockJ *MockJobRepository) GetJob(_ context.Context, jobID uuid.UUID) (domain.Job, error) {
	job, ok := mockJ.storage[jobID]
	if !ok {
		return domain.Job{}, domain.ErrJobNotFound
	}
	return job, nil
}

func (mockJ *MockJobRepository) CreateJob(_ context.Context, job *domain.Job) error {
	if mockJ.createErr != nil {
		return mockJ.createErr
	}
	if mockJ.storage == nil {
		mockJ.storage = make(map[uuid.UUID]domain.Job)
	}
	mockJ.storage[job.JobID] = *job
	return nil
}

func (mockJ *MockJobRepository) GetAnalysisResult(context.Context, uuid.UUID) (domain.AnalysisResult, error) {
	return domain.AnalysisResult{}, nil
}

func TestCreateJob(t *testing.T) {
	jobID := uuid.New()
	regionID := uuid.New()
	objectKey := domain.ObjectKey(regionID.String() + "/spb.geojson")
	testJob := domain.Job{
		JobID:          jobID,
		RegionID:       regionID,
		Status:         "queued",
		TransportTypes: []domain.Transport{domain.Road},
		Point1:         domain.MapPoint{Latitude: 59.2, Longitude: 30.2},
		Point2:         domain.MapPoint{Latitude: 59.8, Longitude: 30.8},
	}
	existingJob := testJob
	existingJob.Status = "running"
	conflictingJob := testJob
	conflictingJob.TransportTypes = []domain.Transport{domain.Rail}
	testRegion := miniodto.Region{
		Type: "FeatureCollection",
		Features: []miniodto.RegionFeature{
			{
				Type:       "Feature",
				Properties: map[string]any{},
				Geometry: miniodto.RegionGeometry{
					Type:        "Polygon",
					Coordinates: []byte(`[[[30,59],[31,59],[31,60],[30,60],[30,59]]]`),
				},
			},
		},
	}
	testTable := []struct {
		Name            string
		ExistingJobs    map[uuid.UUID]domain.Job
		RegionErr       error
		CreateErr       error
		Point2          domain.MapPoint
		ExpectedStatus  domain.JobStatus
		ExpectedCreated bool
		ExpectedErr     error
		ExpectedKey     domain.ObjectKey
	}{
		{
			Name:            "Новая задача сохранена",
			Point2:          testJob.Point2,
			ExpectedStatus:  "queued",
			ExpectedCreated: true,
			ExpectedKey:     objectKey,
		},
		{
			Name:           "Повторный запрос возвращает существующую задачу",
			ExistingJobs:   map[uuid.UUID]domain.Job{jobID: existingJob},
			Point2:         testJob.Point2,
			ExpectedStatus: "running",
		},
		{
			Name:         "Тот же ID с другими параметрами",
			ExistingJobs: map[uuid.UUID]domain.Job{jobID: conflictingJob},
			Point2:       testJob.Point2,
			ExpectedErr:  domain.ErrJobConflict,
		},
		{
			Name:        "Регион не найден в БД",
			RegionErr:   domain.ErrRegionNotFound,
			Point2:      testJob.Point2,
			ExpectedErr: domain.ErrRegionNotFound,
		},
		{
			Name:        "Область анализа выходит за границы региона",
			Point2:      domain.MapPoint{Latitude: 61, Longitude: 32},
			ExpectedErr: domain.ErrAreaOutOfBounds,
			ExpectedKey: objectKey,
		},
		{
			Name:        "Ошибка сохранения задачи в БД",
			CreateErr:   domain.ErrInternalDB,
			Point2:      testJob.Point2,
			ExpectedErr: domain.ErrInternalDB,
			ExpectedKey: objectKey,
		},
	}
	for _, tt := range testTable {
		t.Run(tt.Name, func(t *testing.T) {
			mockJobRep := MockJobRepository{storage: tt.ExistingJobs, createErr: tt.CreateErr}
			mockRegionRep := MockRegionRepository{
				storage: map[string]domain.ObjectKey{regionID.String(): objectKey},
				err:     tt.RegionErr,
			}
			mockMinio := MockMinIO{region: testRegion}
			usecase := NewUsecase(&mockJobRep, &mockRegionRep, &mockMinio, slog.Default())

			status, created, err := usecase.CreateJob(context.Background(), jobID, regionID,
				testJob.Point1.Latitude, testJob.Point1.Longitude,
				tt.Point2.Latitude, tt.Point2.Longitude, testJob.TransportTypes)
			assert.Equal(t, tt.ExpectedKey, mockMinio.receivedKey)
			assert.Equal(t, tt.ExpectedStatus, status)
			assert.Equal(t, tt.ExpectedCreated, created)
			if tt.ExpectedErr != nil {
				require.ErrorIs(t, err, tt.ExpectedErr)
				if tt.ExistingJobs == nil {
					assert.Empty(t, mockJobRep.storage)
				} else {
					assert.Equal(t, conflictingJob, mockJobRep.storage[jobID])
				}
				return
			}
			require.NoError(t, err)
			storedJob, err := mockJobRep.GetJob(context.Background(), jobID)
			require.NoError(t, err)
			if tt.ExpectedCreated {
				assert.Equal(t, testJob, storedJob)
			} else {
				assert.Equal(t, existingJob, storedJob)
				assert.Len(t, mockJobRep.storage, 1)
			}
		})
	}
}
