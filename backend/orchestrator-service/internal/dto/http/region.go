package httpdto

import "orchestrator-service/internal/dto"

type Region struct {
	Boundary BoundaryGeometry `json:"boundary"`

	RegionID Identifier `json:"region_id"`
}

type RegionList = []RegionSummary

type RegionSummary struct {
	Name string `json:"name"`

	RegionID Identifier `json:"region_id"`
}

type RegionFeatureCollection = dto.RegionFeatureCollection

type RegionFeature = dto.RegionFeature
