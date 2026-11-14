package httpcontroller

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"mime/multipart"
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
	regions            []domain.RegionInfo
	region             domain.Region
	err                error
	receivedID         uuid.UUID
	receivedName       string
	receivedPath       string
	receivedCollection dto.RegionFeatureCollection
}

func (mockU *MockRegionUsecase) GetRegions(context.Context) ([]domain.RegionInfo, error) {
	return mockU.regions, mockU.err
}

func (mockU *MockRegionUsecase) GetRegion(_ context.Context, regionID uuid.UUID) (domain.Region, error) {
	mockU.receivedID = regionID
	return mockU.region, mockU.err
}

func (mockU *MockRegionUsecase) AddRegion(_ context.Context, name, filePath string, collection dto.RegionFeatureCollection) (domain.Region, error) {
	mockU.receivedName = name
	mockU.receivedPath = filePath
	mockU.receivedCollection = collection
	return mockU.region, mockU.err
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

func TestAddRegionHandler(t *testing.T) {
	regionID := uuid.New()
	testRegion := domain.Region{
		ID: regionID,
		Boundary: domain.BoundaryGeometry{
			Type:        "Polygon",
			Coordinates: []byte(`[[[30,59],[31,59],[31,60],[30,60],[30,59]]]`),
		},
	}
	dtoResp := httpdto.Region{
		RegionID: regionID.String(),
		Boundary: dto.BoundaryGeometry{
			Type:        "Polygon",
			Coordinates: []byte(`[[[30,59],[31,59],[31,60],[30,60],[30,59]]]`),
		},
	}
	testFileBody := []byte(`{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {},
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[30,59],[31,59],[31,60],[30,60],[30,59]]]
      }
    }
  ]
}`)

	testTable := []struct {
		TestName     string
		TestFileName string
		FileCount    int
		ContentType  string
		ExpectedCode int
		ExpectedResp httpdto.Region
		TestFileBody []byte
		ExpectedErr  *httpdto.Error
		RegionErr    error
	}{
		{
			TestName:     "Регион успешно загружен",
			TestFileName: "region.geojson",
			FileCount:    1,
			TestFileBody: testFileBody,
			ExpectedCode: http.StatusCreated,
			ExpectedResp: dtoResp,
		},
		{
			TestName:     "Не передан файл",
			ExpectedCode: http.StatusBadRequest,
			ExpectedErr: &httpdto.Error{
				Code: "missing_file", Field: "file", Message: "Передай файл в поле file",
			},
		},
		{
			TestName:     "Передано несколько файлов",
			TestFileName: "region.geojson",
			FileCount:    2,
			TestFileBody: testFileBody,
			ExpectedCode: http.StatusBadRequest,
			ExpectedErr: &httpdto.Error{
				Code: "invalid_multipart", Field: "file", Message: "Передай ровно один файл в multipart/form-data",
			},
		},
		{
			TestName:     "В Content-Type отсутствует boundary",
			TestFileName: "region.geojson",
			FileCount:    1,
			TestFileBody: testFileBody,
			ContentType:  "multipart/form-data",
			ExpectedCode: http.StatusBadRequest,
			ExpectedErr: &httpdto.Error{
				Code: "invalid_multipart", Field: "file", Message: "Передай ровно один файл в multipart/form-data",
			},
		},
		{
			TestName:     "Вместо multipart передан application/json",
			TestFileName: "region.geojson",
			FileCount:    1,
			TestFileBody: testFileBody,
			ContentType:  "application/json",
			ExpectedCode: http.StatusUnsupportedMediaType,
			ExpectedErr: &httpdto.Error{
				Code: "unsupported_media_type", Message: "Ожидается multipart/form-data",
			},
		},
		{
			TestName:     "Пустой файл",
			TestFileName: "region.geojson",
			FileCount:    1,
			ExpectedCode: http.StatusBadRequest,
			ExpectedErr: &httpdto.Error{
				Code: "invalid_json", Message: "Тело запроса должно содержать корректный JSON-объект",
			},
		},
		{
			TestName:     "Битый JSON внутри файла",
			TestFileName: "region.geojson",
			FileCount:    1,
			TestFileBody: []byte(`{"type":`),
			ExpectedCode: http.StatusBadRequest,
			ExpectedErr: &httpdto.Error{
				Code: "invalid_json", Message: "Тело запроса должно содержать корректный JSON-объект",
			},
		},
		{
			TestName:     "Неверный тип features в JSON",
			TestFileName: "region.geojson",
			FileCount:    1,
			TestFileBody: []byte(`{"type":"FeatureCollection","features":"wrong"}`),
			ExpectedCode: http.StatusBadRequest,
			ExpectedErr: &httpdto.Error{
				Code: "invalid_json", Message: "Тело запроса должно содержать корректный JSON-объект",
			},
		},
		{
			TestName:     "В файле два JSON-объекта",
			TestFileName: "region.geojson",
			FileCount:    1,
			TestFileBody: []byte(string(testFileBody) + `{}`),
			ExpectedCode: http.StatusBadRequest,
			ExpectedErr: &httpdto.Error{
				Code: "invalid_json", Message: "Тело запроса должно содержать корректный JSON-объект",
			},
		},
		{
			TestName:     "Размер файла превышает лимит на один байт",
			TestFileName: "region.geojson",
			FileCount:    1,
			TestFileBody: bytes.Repeat([]byte("x"), int(maxRegionFileSize)+1),
			ExpectedCode: http.StatusRequestEntityTooLarge,
			ExpectedErr: &httpdto.Error{
				Code: "file_too_large", Field: "file", Message: "Размер файла не должен превышать 20 000 000 байт",
			},
		},
		{
			TestName:     "Usecase отклонил геометрию региона",
			TestFileName: "region.geojson",
			FileCount:    1,
			TestFileBody: testFileBody,
			RegionErr:    domain.ErrInvalidRegionFile,
			ExpectedCode: http.StatusUnprocessableEntity,
			ExpectedErr: &httpdto.Error{
				Code: "invalid_region_file", Field: "file",
				Message: "Файл должен содержать непустую FeatureCollection с корректными границами Polygon или MultiPolygon",
			},
		},
		{
			TestName:     "Ошибка БД",
			TestFileName: "region.geojson",
			FileCount:    1,
			TestFileBody: testFileBody,
			RegionErr:    domain.ErrInternalDB,
			ExpectedCode: http.StatusInternalServerError,
			ExpectedErr: &httpdto.Error{
				Code: "internal_db_error", Message: "Не удалось выполнить операцию с базой данных",
			},
		},
		{
			TestName:     "Ошибка MinIO",
			TestFileName: "region.geojson",
			FileCount:    1,
			TestFileBody: testFileBody,
			RegionErr:    domain.ErrInternalStorage,
			ExpectedCode: http.StatusInternalServerError,
			ExpectedErr: &httpdto.Error{
				Code: "storage_error", Message: "Не удалось прочитать данные региона",
			},
		},
		{
			TestName:     "Внутренняя ошибка",
			TestFileName: "region.geojson",
			FileCount:    1,
			TestFileBody: testFileBody,
			RegionErr:    domain.ErrInternalServer,
			ExpectedCode: http.StatusInternalServerError,
			ExpectedErr: &httpdto.Error{
				Code: "internal_error", Message: "Внутренняя ошибка сервера",
			},
		},
	}
	createMultipartForm := func(testFileName string, testFileBody []byte, fileCount int) (bytes.Buffer, string, error) {
		var buffer bytes.Buffer
		writer := multipart.NewWriter(&buffer)

		for i := 0; i < fileCount; i++ {
			part, err := writer.CreateFormFile("file", testFileName)
			if err != nil {
				return bytes.Buffer{}, "", err
			}

			_, err = part.Write(testFileBody)
			if err != nil {
				return bytes.Buffer{}, "", err
			}
		}

		if err := writer.Close(); err != nil {
			return bytes.Buffer{}, "", err
		}

		contentType := writer.FormDataContentType()

		return buffer, contentType, nil
	}

	for _, tt := range testTable {
		t.Run(tt.TestName, func(t *testing.T) {
			buffer, contentType, err := createMultipartForm(tt.TestFileName, tt.TestFileBody, tt.FileCount)
			require.NoError(t, err)
			if tt.ContentType != "" {
				contentType = tt.ContentType
			}
			req := httptest.NewRequest(http.MethodPost, "/regions", &buffer)
			req.Header.Add("content-type", contentType)
			w := httptest.NewRecorder()

			mockRegionUsecase := MockRegionUsecase{
				region: testRegion,
				err:    tt.RegionErr,
			}

			controller := NewHTTPController(nil, &mockRegionUsecase, nil, slog.Default())

			controller.AddRegionHandler().ServeHTTP(w, req)

			require.Equal(t, tt.ExpectedCode, w.Code)
			require.Equal(t, "application/json", w.Header().Get("content-type"))
			if tt.ExpectedCode == http.StatusCreated || tt.RegionErr != nil {
				assert.Equal(t, tt.TestFileName, mockRegionUsecase.receivedName)
				assert.NotEmpty(t, mockRegionUsecase.receivedPath)
				var expectedCollection dto.RegionFeatureCollection
				require.NoError(t, json.Unmarshal(tt.TestFileBody, &expectedCollection))
				assert.Equal(t, expectedCollection, mockRegionUsecase.receivedCollection)
			} else {
				assert.Empty(t, mockRegionUsecase.receivedName)
			}

			if tt.ExpectedErr != nil {
				var body httpdto.Error

				require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
				assert.Equal(t, *tt.ExpectedErr, body)
				return
			}

			var respBody httpdto.Region
			require.NoError(t, json.Unmarshal(w.Body.Bytes(), &respBody))

			assert.Equal(t, tt.ExpectedResp, respBody)

		})
	}

}
