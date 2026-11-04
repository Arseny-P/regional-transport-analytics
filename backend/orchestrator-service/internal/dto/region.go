package dto

import "encoding/json"

type BoundaryGeometry struct {
	Type        string          `json:"type"`
	Coordinates json.RawMessage `json:"coordinates"`
}

type RegionFeatureCollection struct {
	Type     string          `json:"type"`
	Features []RegionFeature `json:"features"`
}

type RegionFeature struct {
	Type       string           `json:"type"`
	Geometry   BoundaryGeometry `json:"geometry"`
	Properties json.RawMessage  `json:"properties"`
}
