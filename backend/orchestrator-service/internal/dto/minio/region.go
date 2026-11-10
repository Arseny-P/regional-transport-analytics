package miniodto

import "orchestrator-service/internal/dto"

type Region struct {
	Type     string          `json:"type"`
	Features []RegionFeature `json:"features"`
}

type RegionFeature struct {
	Type       string         `json:"type"`
	Properties map[string]any `json:"properties"`
	Geometry   RegionGeometry `json:"geometry"`
}

type RegionGeometry = dto.BoundaryGeometry
