package httpcontroller

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"mime/multipart"
	"net/http"
	"orchestrator-service/internal/domain"
	"orchestrator-service/internal/dto"
	httpdto "orchestrator-service/internal/dto/http"
	"os"

	"github.com/google/uuid"
)

const maxRegionFileSize int64 = 20_000_000

func (hc *HTTPController) AddRegionHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if r.MultipartForm != nil {
				if err := r.MultipartForm.RemoveAll(); err != nil {
					hc.logger.WarnContext(r.Context(), "remove multipart files failed", "error", err)
				}
			}
		}()
		header, err := readRegionFileHeader(w, r)
		if err != nil {
			hc.writeRegionError(w, r, err)
			return
		}
		filePath, collection, err := prepareRegionFile(header)
		if filePath != "" {
			defer func() {
				if osErr := os.Remove(filePath); osErr != nil {
					hc.logger.WarnContext(r.Context(), "remove upload file failed", "error", osErr)
				}
			}()
		}
		if err != nil {
			hc.writeRegionError(w, r, err)
			return
		}
		result, err := hc.regionUsecase.AddRegion(r.Context(), header.Filename, filePath, collection)
		if err != nil {
			hc.writeRegionError(w, r, err)
			return
		}
		hc.WriteResponse(w, http.StatusCreated, httpdto.Region{
			RegionID: result.ID.String(),
			Boundary: httpdto.BoundaryGeometry{
				Type: result.Boundary.Type, Coordinates: json.RawMessage(result.Boundary.Coordinates),
			},
		})
	}
}

func (hc *HTTPController) GetRegionsHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		regions, err := hc.regionUsecase.GetRegions(r.Context())
		if err != nil {
			hc.writeRegionError(w, r, err)
			return
		}
		response := make(httpdto.RegionList, 0, len(regions))
		for _, region := range regions {
			response = append(response, httpdto.RegionSummary{
				RegionID: region.ID.String(), Name: region.Name,
			})
		}
		hc.WriteResponse(w, http.StatusOK, response)
	}
}

func (hc *HTTPController) GetRegionHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		regionID, err := uuid.Parse(r.PathValue("region_id"))
		if err != nil {
			hc.writeError(w, errInvalidRegionPathID)
			return
		}
		region, err := hc.regionUsecase.GetRegion(r.Context(), regionID)
		if err != nil {
			hc.writeRegionError(w, r, err)
			return
		}
		hc.WriteResponse(w, http.StatusOK, httpdto.Region{
			RegionID: region.ID.String(),
			Boundary: httpdto.BoundaryGeometry{
				Type: region.Boundary.Type, Coordinates: json.RawMessage(region.Boundary.Coordinates),
			},
		})
	}
}

func readRegionFileHeader(w http.ResponseWriter, r *http.Request) (*multipart.FileHeader, error) {
	mediaType, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || mediaType != "multipart/form-data" {
		return nil, errUnsupportedMediaType
	}

	r.Body = http.MaxBytesReader(w, r.Body, maxRegionFileSize+(1<<20))
	if err := r.ParseMultipartForm(1 << 20); err != nil {
		var sizeErr *http.MaxBytesError
		if errors.As(err, &sizeErr) || errors.Is(err, multipart.ErrMessageTooLarge) {
			return nil, errEntityTooLarge
		}
		return nil, errInvalidMultipart
	}
	headers := r.MultipartForm.File["file"]
	if len(headers) == 0 {
		return nil, errMissingFile
	}
	fileCount := 0
	for _, files := range r.MultipartForm.File {
		fileCount += len(files)
	}
	if fileCount != 1 {
		return nil, errInvalidMultipart
	}
	if headers[0].Size > maxRegionFileSize {
		return nil, errEntityTooLarge
	}
	return headers[0], nil
}

func prepareRegionFile(header *multipart.FileHeader) (string, dto.RegionFeatureCollection, error) {
	var collection dto.RegionFeatureCollection
	source, err := header.Open()
	if err != nil {
		return "", collection, fmt.Errorf("open upload: %w: %w", domain.ErrInternalServer, err)
	}
	defer func() { _ = source.Close() }()
	temp, err := os.CreateTemp("", "region-*.geojson")
	if err != nil {
		return "", collection, fmt.Errorf("create upload file: %w: %w", domain.ErrInternalServer, err)
	}
	defer func() { _ = temp.Close() }()
	filePath := temp.Name()
	size, err := io.Copy(temp, io.LimitReader(source, maxRegionFileSize+1))
	if err != nil {
		return filePath, collection, fmt.Errorf("copy upload file: %w: %w", domain.ErrInternalServer, err)
	}
	if size > maxRegionFileSize {
		return filePath, collection, errEntityTooLarge
	}
	if _, seekErr := temp.Seek(0, io.SeekStart); seekErr != nil {
		return filePath, collection, fmt.Errorf("rewind upload file: %w: %w", domain.ErrInternalServer, seekErr)
	}
	collection, err = decodeRegionCollection(temp)
	if err != nil {
		return filePath, collection, err
	}
	if err := temp.Close(); err != nil {
		return filePath, collection, fmt.Errorf("close upload file: %w: %w", domain.ErrInternalServer, err)
	}
	return filePath, collection, nil
}

func decodeRegionCollection(reader io.Reader) (dto.RegionFeatureCollection, error) {
	var collection dto.RegionFeatureCollection
	decoder := json.NewDecoder(reader)
	if err := decoder.Decode(&collection); err != nil {
		return collection, regionJSONError(err)
	}
	var extra json.RawMessage
	err := decoder.Decode(&extra)
	if err == nil {
		return collection, errInvalidJSON
	}
	if !errors.Is(err, io.EOF) {
		return collection, regionJSONError(err)
	}
	return collection, nil
}

func (hc *HTTPController) writeRegionError(w http.ResponseWriter, r *http.Request, err error) {
	status, _ := ReturnErrorRespWithCode(err)
	if status == http.StatusInternalServerError && r.Context().Err() == nil {
		hc.logger.ErrorContext(r.Context(), "region request failed", "method", r.Method, "path", r.URL.Path, "error", err)
	}
	hc.writeError(w, err)
}

func regionJSONError(err error) error {
	var syntaxErr *json.SyntaxError
	var typeErr *json.UnmarshalTypeError
	if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) ||
		errors.As(err, &syntaxErr) || errors.As(err, &typeErr) {
		return fmt.Errorf("decode upload JSON: %w: %w", errInvalidJSON, err)
	}
	return fmt.Errorf("read upload JSON: %w: %w", domain.ErrInternalServer, err)
}
