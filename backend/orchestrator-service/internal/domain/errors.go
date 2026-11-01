package domain

import "errors"

var (
	ErrInternalDB            = errors.New("INTERNAL_DB")
	ErrInternalServer        = errors.New("INTERNAL_SERVER")
	ErrJobConflict           = errors.New("THIS_JOB_ALREADY_EXISTS")
	ErrJobNotFound           = errors.New("JOB_NOT_FOUND")
	ErrRegionNotFound        = errors.New("REGION_NOT_FOUND")
	ErrInternalStorage       = errors.New("INTERNAL_STORAGE")
	ErrInvalidRegionData     = errors.New("INVALID_REGION_DATA")
	ErrInvalidCoordinates    = errors.New("INVALID_COORDINATES")
	ErrInvalidArea           = errors.New("INVALID_AREA")
	ErrAreaOutOfBounds       = errors.New("AREA_OUT_OF_BOUNDS")
	ErrInvalidTransports     = errors.New("INVALID_TRANSPORTS")
	ErrOutboxMessageNotFound = errors.New("OUTBOX_MESSAGE_NOT_FOUND")
)
