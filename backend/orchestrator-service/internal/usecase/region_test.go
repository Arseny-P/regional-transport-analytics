package usecase

import (
	"context"
	"log/slog"
	"orchestrator-service/internal/domain"
	"orchestrator-service/internal/dto"
	miniodto "orchestrator-service/internal/dto/minio"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

type MockRegionRepository struct {
	records []domain.RegionRecord
	err     error // internal err
	storage map[string]domain.ObjectKey
}

func (mockR *MockRegionRepository) GetRegionInfo(_ context.Context, regionID uuid.UUID) (domain.ObjectKey, error) {

	if mockR.err != nil {
		return domain.ObjectKey(""), mockR.err
	}
	key, ok := mockR.storage[regionID.String()]
	if !ok {
		return domain.ObjectKey(""), domain.ErrRegionNotFound
	}
	return key, nil
}
func (mockR *MockRegionRepository) CreateRegionInfo(_ context.Context, key domain.ObjectKey, regionID uuid.UUID) error {
	if mockR.storage == nil {
		mockR.storage = make(map[string]domain.ObjectKey)
	}
	mockR.storage[regionID.String()] = key
	return nil
}
func (mockR *MockRegionRepository) GetRegionsInfo(_ context.Context) ([]domain.RegionRecord, error) {
	if mockR.err != nil {
		return nil, mockR.err
	}
	return mockR.records, nil
}

type MockMinIO struct {
	region       miniodto.Region
	err          error
	receivedKey  domain.ObjectKey
	uploadedKey  domain.ObjectKey
	uploadedPath string
}

func (mockMio *MockMinIO) StatObject(context.Context, domain.ObjectKey) error {
	return nil
}

func (mockMio *MockMinIO) GetObject(_ context.Context, key domain.ObjectKey) (miniodto.Region, error) {
	mockMio.receivedKey = key
	if mockMio.err != nil {
		return miniodto.Region{}, mockMio.err
	}

	return mockMio.region, nil
}
func (mockMio *MockMinIO) FPutObject(_ context.Context, key domain.ObjectKey, filePath string) error {
	mockMio.uploadedKey = key
	mockMio.uploadedPath = filePath
	return mockMio.err
}

func (mockMio *MockMinIO) RemoveObject(context.Context, domain.ObjectKey) error {
	return nil
}

func TestAddRegion(t *testing.T) {
	coordinates := []byte(`[[[30,59],[31,59],[31,60],[30,60],[30,59]]]`)
	collection := dto.RegionFeatureCollection{
		Type: "FeatureCollection",
		Features: []dto.RegionFeature{
			{
				Type:       "Feature",
				Properties: []byte(`{}`),
				Geometry:   dto.BoundaryGeometry{Type: "Polygon", Coordinates: coordinates},
			},
		},
	}
	filePath := "temporary/spb.geojson"
	testTable := []struct {
		Name          string
		RepositoryErr error
		StorageErr    error
		ExpectedErr   error
	}{
		{
			Name: "Регион успешно сохранён",
		},
		{
			Name:          "Ошибка проверки БД",
			RepositoryErr: domain.ErrInternalDB,
			ExpectedErr:   domain.ErrInternalDB,
		},
		{
			Name:        "Ошибка загрузки в MinIO",
			StorageErr:  domain.ErrInternalStorage,
			ExpectedErr: domain.ErrInternalStorage,
		},
	}
	for _, tt := range testTable {
		t.Run(tt.Name, func(t *testing.T) {
			mockRegionRep := MockRegionRepository{err: tt.RepositoryErr}
			mockMinio := MockMinIO{err: tt.StorageErr}
			usecase := NewUsecase(nil, &mockRegionRep, &mockMinio, slog.Default())

			region, err := usecase.AddRegion(context.Background(), "spb.geojson", filePath, collection)
			if tt.ExpectedErr != nil {
				require.ErrorIs(t, err, tt.ExpectedErr)
				assert.Equal(t, domain.Region{}, region)
				assert.Empty(t, mockRegionRep.storage)
				if tt.RepositoryErr != nil {
					assert.Empty(t, mockMinio.uploadedKey)
				}
				return
			}
			require.NoError(t, err)
			assert.NotEqual(t, uuid.Nil, region.ID)
			assert.Equal(t, "Polygon", region.Boundary.Type)
			assert.JSONEq(t, string(coordinates), string(region.Boundary.Coordinates))

			objectKey := domain.ObjectKey(region.ID.String() + "/spb.geojson")
			storedKey, err := mockRegionRep.GetRegionInfo(context.Background(), region.ID)
			require.NoError(t, err)
			assert.Equal(t, objectKey, storedKey)
			assert.Equal(t, objectKey, mockMinio.uploadedKey)
			assert.Equal(t, filePath, mockMinio.uploadedPath)
		})
	}
}

func TestGetRegions(t *testing.T) {

	testInputRecords := []domain.RegionRecord{
		domain.RegionRecord{
			ID:        uuid.New(),
			ObjectKey: "3213213/spb.geojson",
		},
		domain.RegionRecord{
			ID:        uuid.New(),
			ObjectKey: "3213213213/Sevastopol.geojson",
		},
	}
	testTable := []struct {
		Name                string
		testRecords         []domain.RegionRecord
		ExpectedRegionsInfo []domain.RegionInfo
		ExpectedErr         error
	}{
		{
			Name:        "Правильный вормат regionsInfo",
			testRecords: testInputRecords,
			ExpectedRegionsInfo: []domain.RegionInfo{
				domain.RegionInfo{
					ID:   testInputRecords[0].ID,
					Name: "spb.geojson",
				},
				domain.RegionInfo{
					ID:   testInputRecords[1].ID,
					Name: "Sevastopol.geojson",
				},
			},
		},
		{
			Name:        "Ошибка internal DB",
			ExpectedErr: domain.ErrInternalDB,
		},
	}

	for _, tt := range testTable {
		t.Run(tt.Name, func(t *testing.T) {
			mockRegionRep := MockRegionRepository{
				records: tt.testRecords,
				err:     tt.ExpectedErr,
			}
			usecase := NewUsecase(nil, &mockRegionRep, nil, &slog.Logger{})
			regionInfos, err := usecase.GetRegions(context.Background())
			if tt.ExpectedErr != nil {
				assert.EqualError(t, err, tt.ExpectedErr.Error())
				return
			}

			require.NoError(t, err)

			assert.Equal(t, tt.ExpectedRegionsInfo, regionInfos)

		})
	}

}

func TestGetRegion(t *testing.T) {
	id := uuid.New()
	objectKey := domain.ObjectKey(id.String() + "/spb.geojson")
	coordinates := []byte(`[[[30,59],[31,59],[31,60],[30,60],[30,59]]]`)
	testRegion := miniodto.Region{
		Type: "FeatureCollection",
		Features: []miniodto.RegionFeature{
			{
				Type:       "Feature",
				Properties: map[string]any{},
				Geometry:   miniodto.RegionGeometry{Type: "Polygon", Coordinates: coordinates},
			},
		},
	}
	testStorage := map[string]domain.ObjectKey{id.String(): objectKey}
	testTable := []struct {
		Name              string
		RegionID          uuid.UUID
		RepositoryStorage map[string]domain.ObjectKey
		StorageRegion     miniodto.Region
		StorageErr        error
		ExpectedRegion    domain.Region
		ExpectedErr       error
		ExpectedKey       domain.ObjectKey
	}{
		{
			Name:              "Успешно возвращённый регион",
			RegionID:          id,
			RepositoryStorage: testStorage,
			StorageRegion:     testRegion,
			ExpectedRegion: domain.Region{
				ID:       id,
				Boundary: domain.BoundaryGeometry{Type: "Polygon", Coordinates: coordinates},
			},
			ExpectedKey: objectKey,
		},
		{
			Name:        "Регион не найден в БД",
			RegionID:    id,
			ExpectedErr: domain.ErrRegionNotFound,
		},
		{
			Name:              "Файл не найден в MinIO",
			RegionID:          id,
			RepositoryStorage: testStorage,
			StorageErr:        domain.ErrRegionNotFound,
			ExpectedErr:       domain.ErrRegionNotFound,
			ExpectedKey:       objectKey,
		},
	}
	for _, tt := range testTable {
		t.Run(tt.Name, func(t *testing.T) {
			mockRegionRep := MockRegionRepository{storage: tt.RepositoryStorage}
			mockMinio := MockMinIO{region: tt.StorageRegion, err: tt.StorageErr}
			usecase := NewUsecase(nil, &mockRegionRep, &mockMinio, slog.Default())

			region, err := usecase.GetRegion(context.Background(), tt.RegionID)
			assert.Equal(t, tt.ExpectedKey, mockMinio.receivedKey)
			if tt.ExpectedErr != nil {
				require.ErrorIs(t, err, tt.ExpectedErr)
				assert.Equal(t, domain.Region{}, region)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.ExpectedRegion.ID, region.ID)
			assert.Equal(t, tt.ExpectedRegion.Boundary.Type, region.Boundary.Type)
			assert.JSONEq(t, string(tt.ExpectedRegion.Boundary.Coordinates), string(region.Boundary.Coordinates))
		})
	}
}
