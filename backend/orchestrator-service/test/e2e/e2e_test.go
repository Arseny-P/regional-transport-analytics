//go:build e2e

package e2e

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"testing"
	"time"

	httpdto "orchestrator-service/internal/dto/http"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
)

const (
	testRegionName        = "test.geojson"
	testRegionCoordinates = `[[[30,59],[31,59],[31,60],[30,60],[30,59]]]`
)

func TestAddRegionE2E(t *testing.T) {
	client := &http.Client{Timeout: 10 * time.Second}
	regionID := uploadTestRegion(t, client)

	var stored httpdto.Region
	err := requestJSON(t.Context(), client, http.MethodGet, "/regions/"+regionID, http.NoBody, "", http.StatusOK, &stored)
	require.NoError(t, err)
	require.Equal(t, "Polygon", stored.Boundary.Type)
	require.JSONEq(t, testRegionCoordinates, string(stored.Boundary.Coordinates))
}

func TestUploadedRegionInListE2E(t *testing.T) {
	client := &http.Client{Timeout: 10 * time.Second}
	regionID := uploadTestRegion(t, client)

	var regions httpdto.RegionList
	err := requestJSON(t.Context(), client, http.MethodGet, "/regions", http.NoBody, "", http.StatusOK, &regions)
	require.NoError(t, err)
	require.Contains(t, regions, httpdto.RegionSummary{RegionID: regionID, Name: testRegionName})
}

func uploadTestRegion(t *testing.T, client *http.Client) string {
	t.Helper()

	testFileBody := []byte(`{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {},
      "geometry": {
        "type": "Polygon",
        "coordinates": ` + testRegionCoordinates + `
      }
    }
  ]
}`)
	body, contentType, err := createMultipartForm(testRegionName, testFileBody)
	require.NoError(t, err)

	var created httpdto.Region
	err = requestJSON(t.Context(), client, http.MethodPost, "/regions", &body, contentType, http.StatusCreated, &created)
	require.NoError(t, err)

	return created.RegionID
}

func TestCreateAnalysisE2E(t *testing.T) {
	client := &http.Client{Timeout: 10 * time.Second}

	createAnalysis(t.Context(), t, client)
}

func TestFullFlow(t *testing.T) {
	client := &http.Client{Timeout: 10 * time.Second}

	ctx, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	jobID := createAnalysis(ctx, t, client)
	query := "?job_id=" + jobID

	flowCtx, stopHeartbeat := context.WithCancelCause(ctx)
	heartbeatDone := make(chan struct{})
	go func() {
		defer close(heartbeatDone)
		if err := keepAnalysisAlive(flowCtx, client, jobID); err != nil {
			stopHeartbeat(err)
		}
	}()
	defer func() {
		stopHeartbeat(nil)
		<-heartbeatDone
	}()

	resultTicker := time.NewTicker(time.Second)
	defer resultTicker.Stop()

	for {
		var result httpdto.AnalysisResult
		err := requestJSON(flowCtx, client, http.MethodGet, "/analysis/result"+query+"&is_road=true", http.NoBody, "application/json", http.StatusOK, &result)
		require.NoError(t, context.Cause(flowCtx))
		require.NoError(t, err)
		require.Equal(t, jobID, result.JobID)
		for _, work := range result.WorkingStatuses {
			if work.Error != nil {
				t.Fatalf("%s: %s: %s", work.TransportType, work.Error.Code, work.Error.Message)
			}
		}

		switch result.Status {
		case httpdto.Completed:
			checkAnalysisResult(t, &result)
			return
		case httpdto.Queued, httpdto.Running:
		default:
			t.Fatalf("unexpected job status %q", result.Status)
		}

		select {
		case <-flowCtx.Done():
			t.Fatal(context.Cause(flowCtx))
		case <-resultTicker.C:
		}
	}
}

func createAnalysis(ctx context.Context, t *testing.T, client *http.Client) string {
	t.Helper()

	regionID, err := getDemoRegionID(ctx, client)
	require.NoError(t, err)

	req := httpdto.CreateAnalysisJSONRequestBody{
		RegionID: regionID,
		Area: httpdto.AnalysisArea{
			FirstPoint:  httpdto.MapPoint{Latitude: 59.97, Longitude: 29.70},
			SecondPoint: httpdto.MapPoint{Latitude: 60.03, Longitude: 29.85},
		},
		Transports: []string{"road"},
	}
	body, err := json.Marshal(req)
	require.NoError(t, err)

	jobID := uuid.NewString()

	var receipt httpdto.AnalysisReceipt

	err = requestJSON(ctx, client, http.MethodPost, "/analysis?job_id="+jobID, bytes.NewReader(body), "application/json", http.StatusAccepted, &receipt)

	require.NoError(t, err)
	require.Equal(t, jobID, receipt.JobID)
	require.Contains(t, []httpdto.JobState{httpdto.Queued, httpdto.Running}, receipt.Status)
	return jobID
}

func keepAnalysisAlive(ctx context.Context, client *http.Client, jobID string) error {
	path := "/analysis/heartbeat?job_id=" + jobID
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	for {
		var status httpdto.AnalysisStatus
		requestCtx, cancel := context.WithTimeout(ctx, 4*time.Second)
		err := requestJSON(requestCtx, client, http.MethodPost, path, http.NoBody, "application/json", http.StatusOK, &status)
		cancel()
		if err != nil {
			return err
		}
		if status.JobID != jobID {
			return fmt.Errorf("heartbeat returned job ID %q, want %q", status.JobID, jobID)
		}
		if status.Error != nil {
			return fmt.Errorf("heartbeat %s: %s", status.Error.Code, status.Error.Message)
		}

		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
		}
	}
}

func checkAnalysisResult(t *testing.T, result *httpdto.AnalysisResult) {
	t.Helper()

	require.NotNil(t, result.Graph)
	require.NotEmpty(t, result.Graph.Nodes)
	require.NotEmpty(t, result.Graph.Edges)

	nodes := make(map[string]struct{}, len(result.Graph.Nodes))
	const warehouseID = "hub_kad_logistics"
	for _, node := range result.Graph.Nodes {
		nodes[node.ID] = struct{}{}
		if node.ID == warehouseID {
			require.Equal(t, "warehouse", node.Attributes["object_type"])
		}
	}
	require.Contains(t, nodes, warehouseID)

	hasRoad := false
	for _, edge := range result.Graph.Edges {
		require.Contains(t, nodes, edge.Source, "edge %s source", edge.ID)
		require.Contains(t, nodes, edge.Target, "edge %s target", edge.ID)
		if edge.Attributes["edge_type"] == "road" {
			hasRoad = true
			require.NotNil(t, edge.SegmentID, "edge %s", edge.ID)
			require.NotEmpty(t, *edge.SegmentID, "edge %s", edge.ID)
			require.GreaterOrEqual(t, len(edge.Geometry), 2, "edge %s geometry", edge.ID)
		}
	}
	require.True(t, hasRoad, "expected a road edge in the offline graph")

	if len(result.Metrics) > 0 {
		require.Len(t, result.WorkingStatuses, 1)
		require.True(t, result.WorkingStatuses[0].MetricsAvailable)
	}
	for _, metric := range result.Metrics {
		require.NotEmpty(t, metric.Name)
		if metric.NodeID != nil {
			require.Contains(t, nodes, *metric.NodeID, "metric %s node_id", metric.Name)
		}
	}

}
