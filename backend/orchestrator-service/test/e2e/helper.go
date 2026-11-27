//go:build e2e

package e2e

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"

	httpdto "orchestrator-service/internal/dto/http"
)

const (
	baseURL        = "http://localhost:8080"
	demoRegionName = "spb.geojson"
)

func createMultipartForm(testFileName string, testFileBody []byte) (bytes.Buffer, string, error) {
	var buffer bytes.Buffer
	writer := multipart.NewWriter(&buffer)

	part, err := writer.CreateFormFile("file", testFileName)
	if err != nil {
		return bytes.Buffer{}, "", err
	}
	if _, err := part.Write(testFileBody); err != nil {
		return bytes.Buffer{}, "", err
	}

	if err := writer.Close(); err != nil {
		return bytes.Buffer{}, "", err
	}

	contentType := writer.FormDataContentType()

	return buffer, contentType, nil
}

func getDemoRegionID(ctx context.Context, client *http.Client) (string, error) {
	var regions httpdto.RegionList
	if err := requestJSON(ctx, client, http.MethodGet, "/regions", http.NoBody, "application/json", http.StatusOK, &regions); err != nil {
		return "", err
	}

	for _, region := range regions {
		if region.Name == demoRegionName && region.RegionID != "" {
			return region.RegionID, nil
		}
	}
	return "", fmt.Errorf("demo region %s not found", demoRegionName)
}

func requestJSON(
	ctx context.Context,
	client *http.Client,
	method, path string,
	body io.Reader,
	contentType string,
	wantStatus int,
	result any,
) error {
	req, err := http.NewRequestWithContext(ctx, method, baseURL+path, body)
	if err != nil {
		return err
	}
	if body != http.NoBody {
		req.Header.Set("Content-Type", contentType)
	}

	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != wantStatus {
		return fmt.Errorf("%s: unexpected HTTP status %s", path, resp.Status)
	}
	return json.NewDecoder(resp.Body).Decode(result)
}
