package httpcontroller

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"orchestrator-service/internal/domain"
	"orchestrator-service/internal/dto"
	httpdto "orchestrator-service/internal/dto/http"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

type MockRegionUsecase struct {
	regions    []domain.RegionInfo
	region     domain.Region
	err        error
	receivedID uuid.UUID
}

func (mockU *MockRegionUsecase) GetRegions(context.Context) ([]domain.RegionInfo, error) {
	return mockU.regions, mockU.err
}

func (mockU *MockRegionUsecase) GetRegion(_ context.Context, regionID uuid.UUID) (domain.Region, error) {
	mockU.receivedID = regionID
	return mockU.region, mockU.err
}

func (mockU *MockRegionUsecase) AddRegion(context.Context, string, string, dto.RegionFeatureCollection) (domain.Region, error) {
	panic("unexpected AddRegion call")
}

func TestGetRegionsHandler(t *testing.T) {
	firstID := uuid.New()
	secondID := uuid.New()
	testTable := []struct {
		Name           string
		Regions        []domain.RegionInfo
		UsecaseErr     error
		ExpectedStatus int
		ExpectedBody   string
	}{
		{
			Name: "Список сохранённых регионов",
			Regions: []domain.RegionInfo{
				{ID: firstID, Name: "spb.geojson"},
				{ID: secondID, Name: "leningrad.geojson"},
			},
			ExpectedStatus: http.StatusOK,
			ExpectedBody: fmt.Sprintf(`[
				{"region_id":%q,"name":"spb.geojson"},
				{"region_id":%q,"name":"leningrad.geojson"}
			]`, firstID.String(), secondID.String()),
		},
		{
			Name:           "При отсутствии регионов возвращается пустой массив",
			ExpectedStatus: http.StatusOK,
			ExpectedBody:   `[]`,
		},
		{
			Name:           "Ошибка БД",
			UsecaseErr:     domain.ErrInternalDB,
			ExpectedStatus: http.StatusInternalServerError,
			ExpectedBody:   `{"code":"internal_db_error","message":"Не удалось выполнить операцию с базой данных"}`,
		},
	}
	for _, tt := range testTable {
		t.Run(tt.Name, func(t *testing.T) {
			mockUsecase := MockRegionUsecase{regions: tt.Regions, err: tt.UsecaseErr}
			controller := NewHTTPController(nil, &mockUsecase, nil, slog.Default())
			request := httptest.NewRequest(http.MethodGet, "/regions", http.NoBody)
			response := httptest.NewRecorder()

			controller.Routes().ServeHTTP(response, request)

			assert.Equal(t, tt.ExpectedStatus, response.Code)
			assert.Equal(t, "application/json", response.Header().Get("Content-Type"))
			assert.JSONEq(t, tt.ExpectedBody, response.Body.String())
		})
	}
}

func TestGetRegionHandler(t *testing.T) {
	regionID := uuid.New()
	testRegion := domain.Region{
		ID: regionID,
		Boundary: domain.BoundaryGeometry{
			Type:        "Polygon",
			Coordinates: []byte(`[[[30,59],[31,59],[31,60],[30,60],[30,59]]]`),
		},
	}
	testTable := []struct {
		Name           string
		RegionID       string
		Region         domain.Region
		UsecaseErr     error
		ExpectedStatus int
		ExpectedCode   string
		ExpectedID     uuid.UUID
	}{
		{
			Name:           "Граница выбранного региона",
			RegionID:       regionID.String(),
			Region:         testRegion,
			ExpectedStatus: http.StatusOK,
			ExpectedID:     regionID,
		},
		{
			Name:           "Некорректный UUID",
			RegionID:       "not-a-uuid",
			ExpectedStatus: http.StatusBadRequest,
			ExpectedCode:   "invalid_region_id",
		},
		{
			Name:           "Регион или файл не найден",
			RegionID:       regionID.String(),
			UsecaseErr:     domain.ErrRegionNotFound,
			ExpectedStatus: http.StatusNotFound,
			ExpectedCode:   "region_not_found",
			ExpectedID:     regionID,
		},
		{
			Name:           "Ошибка БД",
			RegionID:       regionID.String(),
			UsecaseErr:     domain.ErrInternalDB,
			ExpectedStatus: http.StatusInternalServerError,
			ExpectedCode:   "internal_db_error",
			ExpectedID:     regionID,
		},
		{
			Name:           "Ошибка MinIO",
			RegionID:       regionID.String(),
			UsecaseErr:     domain.ErrInternalStorage,
			ExpectedStatus: http.StatusInternalServerError,
			ExpectedCode:   "storage_error",
			ExpectedID:     regionID,
		},
		{
			Name:           "Повреждённый файл границы",
			RegionID:       regionID.String(),
			UsecaseErr:     domain.ErrInvalidRegionData,
			ExpectedStatus: http.StatusInternalServerError,
			ExpectedCode:   "storage_error",
			ExpectedID:     regionID,
		},
	}
	for _, tt := range testTable {
		t.Run(tt.Name, func(t *testing.T) {
			mockUsecase := MockRegionUsecase{region: tt.Region, err: tt.UsecaseErr}
			controller := NewHTTPController(nil, &mockUsecase, nil, slog.Default())
			request := httptest.NewRequest(http.MethodGet, "/regions/"+tt.RegionID, http.NoBody)
			response := httptest.NewRecorder()

			controller.Routes().ServeHTTP(response, request)

			assert.Equal(t, tt.ExpectedStatus, response.Code)
			assert.Equal(t, "application/json", response.Header().Get("Content-Type"))
			assert.Equal(t, tt.ExpectedID, mockUsecase.receivedID)
			if tt.ExpectedCode != "" {
				var errorResponse httpdto.Error
				require.NoError(t, json.Unmarshal(response.Body.Bytes(), &errorResponse))
				assert.Equal(t, tt.ExpectedCode, errorResponse.Code)
				assert.NotEmpty(t, errorResponse.Message)
				if tt.ExpectedStatus == http.StatusBadRequest || tt.ExpectedStatus == http.StatusNotFound {
					assert.Equal(t, "region_id", errorResponse.Field)
				}
				return
			}
			expectedBody := fmt.Sprintf(`{
				"region_id":%q,
				"boundary":{"type":"Polygon","coordinates":[[[30,59],[31,59],[31,60],[30,60],[30,59]]]}
			}`, regionID.String())
			assert.JSONEq(t, expectedBody, response.Body.String())
		})
	}
}
