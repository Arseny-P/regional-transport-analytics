package dto

type MapPoint struct {
	Latitude  float32 `json:"latitude"`
	Longitude float32 `json:"longitude"`
}

type AnalysisArea struct {
	FirstPoint  MapPoint `json:"first_point"`
	SecondPoint MapPoint `json:"second_point"`
}

type Graph struct {
	Nodes []GraphNode `json:"nodes"`
	Edges []GraphEdge `json:"edges"`
}

type GraphNode struct {
	ID         string         `json:"id"`
	Position   []float32      `json:"position"`
	Attributes map[string]any `json:"attributes,omitempty"`
}

type GraphEdge struct {
	ID         string         `json:"id"`
	Source     string         `json:"source"`
	Target     string         `json:"target"`
	Geometry   [][]float32    `json:"geometry,omitempty"`
	Attributes map[string]any `json:"attributes,omitempty"`
}

type Metric struct {
	Name  string  `json:"name"`
	Value float32 `json:"value"`
}
