package httpdto

import "encoding/json"

type Position = []float64

type BoundaryGeometry struct {
	Type        string          `json:"type"`
	Coordinates json.RawMessage `json:"coordinates"`
}
