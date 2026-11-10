package domain

import "github.com/google/uuid"

type ObjectKey string

type Region struct {
	ID       uuid.UUID
	Boundary BoundaryGeometry
}

type BoundaryGeometry struct {
	Type        string
	Coordinates []byte
}

type RegionInfo struct {
	ID   uuid.UUID
	Name string
}

type RegionRecord struct {
	ID        uuid.UUID
	ObjectKey ObjectKey
}
