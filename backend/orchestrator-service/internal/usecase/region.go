package usecase

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"orchestrator-service/internal/domain"
	"orchestrator-service/internal/dto"
	"path"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/peterstace/simplefeatures/geom"
)

func (u *Usecase) AddRegion(ctx context.Context, name, filePath string, collection dto.RegionFeatureCollection) (domain.Region, error) {
	result := domain.Region{ID: uuid.New()}
	name = path.Base(strings.ReplaceAll(strings.TrimSpace(name), "\\", "/"))
	objectKey := domain.ObjectKey(result.ID.String() + "/" + name)
	if name == "." || name == ".." || name == "/" || strings.ContainsRune(name, 0) || len(objectKey) > 1024 {
		return domain.Region{}, domain.ErrInvalidRegionFile
	}
	boundary, err := buildRegionBoundary(ctx, collection)
	if err != nil {
		return domain.Region{}, err
	}
	result.Boundary = boundary

	_, err = u.regionRepository.GetRegionInfo(ctx, result.ID)
	if err == nil {
		return domain.Region{}, fmt.Errorf("region ID already exists: %w", domain.ErrInternalDB)
	}
	if !errors.Is(err, domain.ErrRegionNotFound) {
		return domain.Region{}, err
	}
	if err := u.minIO.FPutObject(ctx, objectKey, filePath); err != nil {
		return domain.Region{}, err
	}
	if err := u.saveRegionInfo(ctx, result.ID, objectKey); err != nil {
		return domain.Region{}, err
	}
	return result, nil
}

func (u *Usecase) saveRegionInfo(ctx context.Context, regionID uuid.UUID, objectKey domain.ObjectKey) error {
	createErr := u.regionRepository.CreateRegionInfo(ctx, objectKey, regionID)
	if createErr == nil {
		return nil
	}

	recoveryCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 3*time.Second)
	defer cancel()
	storedKey, checkErr := u.regionRepository.GetRegionInfo(recoveryCtx, regionID)
	if checkErr == nil && storedKey == objectKey {
		return nil
	}
	if errors.Is(checkErr, domain.ErrRegionNotFound) && errors.Is(createErr, domain.ErrRegionInsertRejected) {
		if removeErr := u.minIO.RemoveObject(recoveryCtx, objectKey); removeErr != nil {
			u.logger.ErrorContext(recoveryCtx, "failed to remove region object after rejected insert",
				"region_id", regionID, "object_key", objectKey, "error", removeErr)
		}
		return createErr
	}

	u.logger.ErrorContext(recoveryCtx, "region insert not confirmed; uploaded object retained",
		"region_id", regionID, "object_key", objectKey, "error", createErr, "check_error", checkErr)
	return createErr
}

func buildRegionBoundary(ctx context.Context, featureCollection dto.RegionFeatureCollection) (domain.BoundaryGeometry, error) {
	if featureCollection.Type != "FeatureCollection" || len(featureCollection.Features) == 0 {
		return domain.BoundaryGeometry{}, domain.ErrInvalidRegionFile
	}
	var coordinates [][][][]float64
	geometries := make([]dto.BoundaryGeometry, 0, len(featureCollection.Features))
	for _, feature := range featureCollection.Features {
		if err := ctx.Err(); err != nil {
			return domain.BoundaryGeometry{}, err
		}
		if feature.Type != "Feature" || len(feature.Properties) == 0 ||
			bytes.Contains(feature.Geometry.Coordinates, []byte("null")) {
			return domain.BoundaryGeometry{}, domain.ErrInvalidRegionFile
		}
		var properties map[string]any
		if err := json.Unmarshal(feature.Properties, &properties); err != nil {
			return domain.BoundaryGeometry{}, fmt.Errorf("decode feature properties: %w: %w", domain.ErrInvalidRegionFile, err)
		}
		switch feature.Geometry.Type {
		case "Polygon":
			var polygon [][][]float64
			if err := json.Unmarshal(feature.Geometry.Coordinates, &polygon); err != nil {
				return domain.BoundaryGeometry{}, fmt.Errorf("decode region coordinates: %w: %w", domain.ErrInvalidRegionFile, err)
			}
			coordinates = append(coordinates[:0], polygon)
		case "MultiPolygon":
			if err := json.Unmarshal(feature.Geometry.Coordinates, &coordinates); err != nil {
				return domain.BoundaryGeometry{}, fmt.Errorf("decode region coordinates: %w: %w", domain.ErrInvalidRegionFile, err)
			}
		default:
			return domain.BoundaryGeometry{}, domain.ErrInvalidRegionFile
		}
		if len(coordinates) == 0 {
			return domain.BoundaryGeometry{}, domain.ErrInvalidRegionFile
		}
		for _, polygon := range coordinates {
			if err := CheckPolygons(polygon); err != nil {
				return domain.BoundaryGeometry{}, err
			}
		}
		geometries = append(geometries, feature.Geometry)
	}

	geometry, err := mergeRegionGeometries(geometries)
	if err != nil {
		return domain.BoundaryGeometry{}, fmt.Errorf("merge uploaded region: %w: %w", domain.ErrInvalidRegionFile, err)
	}
	return boundaryFromGeometry(geometry)
}

func boundaryFromGeometry(geometry geom.Geometry) (domain.BoundaryGeometry, error) {
	geometryJSON, err := geometry.MarshalJSON()
	if err != nil {
		return domain.BoundaryGeometry{}, fmt.Errorf("encode region boundary: %w: %w", domain.ErrInternalServer, err)
	}

	var boundary dto.BoundaryGeometry
	if err := json.Unmarshal(geometryJSON, &boundary); err != nil {
		return domain.BoundaryGeometry{}, fmt.Errorf("decode region boundary: %w: %w", domain.ErrInternalServer, err)
	}
	return domain.BoundaryGeometry{Type: boundary.Type, Coordinates: boundary.Coordinates}, nil
}

func mergeRegionGeometries(boundaries []dto.BoundaryGeometry) (geom.Geometry, error) {
	if len(boundaries) == 0 {
		return geom.Geometry{}, domain.ErrInvalidRegionFile
	}
	geometries := make([]geom.Geometry, 0, len(boundaries))
	for _, boundary := range boundaries {
		if boundary.Type != "Polygon" && boundary.Type != "MultiPolygon" {
			return geom.Geometry{}, domain.ErrInvalidRegionFile
		}
		data, err := json.Marshal(boundary)
		if err != nil {
			return geom.Geometry{}, err
		}
		geometry, err := geom.UnmarshalGeoJSON(data)
		if err != nil {
			return geom.Geometry{}, err
		}
		if geometry.IsEmpty() {
			return geom.Geometry{}, domain.ErrInvalidRegionFile
		}
		geometries = append(geometries, geometry)
	}
	if len(geometries) == 1 {
		return geometries[0], nil
	}
	return geom.UnionMany(geometries)
}

func CheckPolygons(polygon [][][]float64) error {
	if len(polygon) == 0 {
		return domain.ErrInvalidRegionFile
	}

	for _, contur := range polygon {
		if len(contur) < 4 {
			return domain.ErrInvalidRegionFile
		}

		for _, point := range contur {
			if len(point) != 2 {
				return domain.ErrInvalidRegionFile
			}
			if !(point[1] >= -90 && point[1] <= 90 &&
				point[0] >= -180 && point[0] <= 180) {
				return domain.ErrInvalidRegionFile
			}
		}
		first, last := contur[0], contur[len(contur)-1]
		if first[0] != last[0] || first[1] != last[1] {
			return domain.ErrInvalidRegionFile
		}

	}

	return nil

}

func (u *Usecase) GetRegions(ctx context.Context) ([]domain.RegionInfo, error) {
	records, err := u.regionRepository.GetRegionsInfo(ctx)
	if err != nil {
		return nil, err
	}
	regions := make([]domain.RegionInfo, 0, len(records))
	for _, record := range records {
		regions = append(regions, domain.RegionInfo{
			ID: record.ID, Name: path.Base(string(record.ObjectKey)),
		})
	}
	return regions, nil
}

func (u *Usecase) GetRegion(ctx context.Context, regionID uuid.UUID) (domain.Region, error) {
	objectKey, err := u.regionRepository.GetRegionInfo(ctx, regionID)
	if err != nil {
		return domain.Region{}, err
	}
	region, err := u.minIO.GetObject(ctx, objectKey)
	if err != nil {
		return domain.Region{}, err
	}
	boundaries := make([]dto.BoundaryGeometry, 0, len(region.Features))
	for _, feature := range region.Features {
		boundaries = append(boundaries, feature.Geometry)
	}
	geometry, err := mergeRegionGeometries(boundaries)
	if err != nil {
		return domain.Region{}, fmt.Errorf("parse stored region geometry: %w: %v", domain.ErrInvalidRegionData, err)
	}
	boundary, err := boundaryFromGeometry(geometry)
	if err != nil {
		return domain.Region{}, err
	}
	return domain.Region{ID: regionID, Boundary: boundary}, nil
}
