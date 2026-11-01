package miniodto

import "encoding/json"

type Region struct {
	Type     string          `json:"type"`
	Features []RegionFeature `json:"features"`
}

type RegionFeature struct {
	Type       string         `json:"type"`
	Properties map[string]any `json:"properties"`
	Geometry   RegionGeometry `json:"geometry"`
}

type RegionGeometry struct {
	Type        string          `json:"type"`
	Coordinates json.RawMessage `json:"coordinates"`
}
