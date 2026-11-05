package httpdto

import "orchestrator-service/internal/dto"

type Position = []float64

type LinearRing []Position

type PolygonCoordinates []LinearRing

type MultiPolygonCoordinates []PolygonCoordinates

type BoundaryGeometry = dto.BoundaryGeometry
