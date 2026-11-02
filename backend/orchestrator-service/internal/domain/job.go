package domain

import (
	"reflect"
	"slices"

	"github.com/google/uuid"
)

type Transport string

const (
	Road Transport = "road"
	Rail Transport = "rail"
	Sea  Transport = "sea"
)

type Job struct {
	JobID          uuid.UUID
	RegionID       uuid.UUID
	Status         JobStatus
	TransportTypes []Transport
	Point1         MapPoint
	Point2         MapPoint
}

type MapPoint struct {
	Latitude  float32
	Longitude float32
}

type JobStatus string

func EqualJobs(job1, job2 *Job) bool {
	return job1.RegionID == job2.RegionID && reflect.DeepEqual(job1.Point1, job2.Point1) && reflect.DeepEqual(job1.Point2, job2.Point2) &&
		slices.Equal(job1.TransportTypes, job2.TransportTypes)
}
