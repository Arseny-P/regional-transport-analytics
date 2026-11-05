package minio

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"orchestrator-service/internal/domain"
	miniodto "orchestrator-service/internal/dto/minio"

	"github.com/minio/minio-go/v7"
)

type MinIO struct {
	client *minio.Client
}

const regionBucket = "regions"

func NewMinio(client *minio.Client) *MinIO {
	return &MinIO{
		client: client,
	}
}

func (mio *MinIO) StatObject(ctx context.Context, objectKey domain.ObjectKey) error {
	_, err := mio.client.StatObject(ctx, regionBucket, string(objectKey), minio.StatObjectOptions{})
	return storageError(err)
}

func (mio *MinIO) FPutObject(ctx context.Context, objectKey domain.ObjectKey, filePath string) error {
	_, err := mio.client.FPutObject(ctx, regionBucket, string(objectKey), filePath, minio.PutObjectOptions{
		ContentType: "application/geo+json",
	})
	return storageError(err)
}

func (mio *MinIO) RemoveObject(ctx context.Context, objectKey domain.ObjectKey) error {
	err := mio.client.RemoveObject(ctx, regionBucket, string(objectKey), minio.RemoveObjectOptions{})
	return storageError(err)
}

func (mio *MinIO) GetObject(ctx context.Context, objectKey domain.ObjectKey) (miniodto.Region, error) {
	resp, err := mio.client.GetObject(ctx, regionBucket, string(objectKey), minio.GetObjectOptions{})
	if err != nil {
		return miniodto.Region{}, storageError(err)
	}

	defer func() { _ = resp.Close() }()
	var region miniodto.Region

	_, err = resp.Stat()
	if err != nil {
		return miniodto.Region{}, storageError(err)
	}
	err = json.NewDecoder(resp).Decode(&region)
	if err != nil {
		var syntaxError *json.SyntaxError
		var typeError *json.UnmarshalTypeError
		if errors.As(err, &syntaxError) || errors.As(err, &typeError) ||
			errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) {
			return miniodto.Region{}, fmt.Errorf("decode region: %w: %w", domain.ErrInvalidRegionData, err)
		}
		return miniodto.Region{}, storageError(err)
	}
	if region.Type != "FeatureCollection" || len(region.Features) == 0 {
		return miniodto.Region{}, domain.ErrInvalidRegionData
	}

	return region, nil
}

func storageError(err error) error {
	if err == nil {
		return nil
	}
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		return err
	}
	if minio.ToErrorResponse(err).Code == "NoSuchKey" {
		return domain.ErrRegionNotFound
	}

	return fmt.Errorf("MinIO request: %w: %w", domain.ErrInternalStorage, err)
}
