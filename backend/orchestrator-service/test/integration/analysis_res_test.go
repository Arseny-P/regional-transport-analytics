package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"orchestrator-service/internal/dto"
	httpdto "orchestrator-service/internal/dto/http"
	kafkadto "orchestrator-service/internal/dto/kafka"
	"reflect"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/segmentio/kafka-go"
)

func TestIntegration(t *testing.T) {
	env := newTestEnvironment(t)
	t.Run("status", env.testStatus)
	t.Run("result", env.testAnalysisResult)
	t.Run("dlq", env.testDLQ)
}

func (env *testEnvironment) testAnalysisResult(t *testing.T) {
	jobID := env.createJob(t)
	ctx, cancel := context.WithTimeout(t.Context(), 30*time.Second)
	defer cancel()

	segmentID := "segment_1_2"
	firstNodeID, secondNodeID := "1", "2"
	graph := &dto.Graph{
		Nodes: []dto.GraphNode{
			{
				ID: "warehouse_1", Position: []float64{29.999, 60},
				Attributes: map[string]any{"object_type": "warehouse", "name": "Склад", "is_isolated": false},
			},
			{
				ID: "1", Position: []float64{30, 60},
				Attributes: map[string]any{"object_type": "road_node"},
			},
			{
				ID: "2", Position: []float64{30.01, 60},
				Attributes: map[string]any{"object_type": "intersection"},
			},
		},
		Edges: []dto.GraphEdge{
			{
				ID: "road_forward", SegmentID: &segmentID, Source: "1", Target: "2",
				Geometry:   [][]float64{{30, 60}, {30.005, 60.001}, {30.01, 60}},
				Attributes: map[string]any{"edge_type": "road", "oneway": false, "length_m": 600.0},
			},
			{
				ID: "connector", Source: "warehouse_1", Target: "1",
				Geometry:   [][]float64{{29.999, 60}, {30, 60}},
				Attributes: map[string]any{"edge_type": "access_connector"},
			},
			{
				ID: "road_reverse", SegmentID: &segmentID, Source: "2", Target: "1",
				Geometry:   [][]float64{{30.01, 60}, {30.005, 60.001}, {30, 60}},
				Attributes: map[string]any{"edge_type": "road", "oneway": false, "length_m": 600.0},
			},
		},
	}
	metrics := []dto.Metric{
		{NodeID: &firstNodeID, Name: "pagerank", Value: 0.4},
		{Name: "vertex_count", Value: 3},
		{NodeID: &secondNodeID, Name: "pagerank", Value: 0.6},
	}

	payload, err := json.Marshal(kafkadto.InboxMessage{
		MessageID: uuid.New(),
		JobID:     jobID,
		Type:      "RESULT",
		Payload:   kafkadto.AnalysisPayload{Status: "completed", Graph: graph, Metrics: metrics},
	})
	checkError(t, err, "encode result event")
	checkError(t, env.writer.WriteMessages(ctx, kafka.Message{
		Key: []byte(jobID.String()), Value: payload,
	}), "send result event")

	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	var result httpdto.AnalysisResult
	for {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet,
			env.server.URL+"/analysis/result?job_id="+jobID.String(), http.NoBody)
		checkError(t, err, "create result request")
		response, err := env.server.Client().Do(req)
		checkError(t, err, "get analysis result over HTTP")
		if response.StatusCode != http.StatusOK {
			_ = response.Body.Close()
			t.Fatalf("HTTP status = %d, want 200", response.StatusCode)
		}

		result = httpdto.AnalysisResult{}
		decodeErr := json.NewDecoder(response.Body).Decode(&result)
		checkError(t, response.Body.Close(), "close HTTP response")
		checkError(t, decodeErr, "decode HTTP result")
		if result.Status == httpdto.Completed {
			break
		}
		select {
		case <-ctx.Done():
			t.Fatalf("HTTP job status = %q, want completed: %v", result.Status, ctx.Err())
		case <-ticker.C:
		}
	}

	expected := httpdto.AnalysisResult{
		JobID: jobID.String(), Status: httpdto.Completed,
		GraphAvailable: true, MetricsAvailable: true,
		Graph: graph, Metrics: metrics,
	}
	if !reflect.DeepEqual(expected, result) {
		t.Errorf("HTTP result = %#v, want %#v", result, expected)
	}
}

func (env *testEnvironment) testStatus(t *testing.T) {
	jobID := env.createJob(t)
	ctx, cancel := context.WithTimeout(t.Context(), 30*time.Second)
	defer cancel()

	payload, err := json.Marshal(kafkadto.InboxMessage{
		MessageID: uuid.New(),
		JobID:     jobID,
		Type:      "STATUS",
		Payload:   kafkadto.AnalysisPayload{Status: "running"},
	})
	checkError(t, err, "encode status event")
	checkError(t, env.writer.WriteMessages(ctx, kafka.Message{
		Key: []byte(jobID.String()), Value: payload,
	}), "send status event")

	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	var result httpdto.AnalysisResult
	for {

		req, err := http.NewRequestWithContext(ctx, http.MethodGet,
			env.server.URL+"/analysis/result?job_id="+jobID.String(), http.NoBody)

		checkError(t, err, "create result request")

		response, err := env.server.Client().Do(req)

		checkError(t, err, "get analysis result over HTTP")

		if response.StatusCode != http.StatusOK {
			_ = response.Body.Close()
			t.Fatalf("HTTP status = %d, want 200", response.StatusCode)
		}

		result = httpdto.AnalysisResult{}
		decodeErr := json.NewDecoder(response.Body).Decode(&result)

		checkError(t, response.Body.Close(), "close HTTP response")

		checkError(t, decodeErr, "decode HTTP result")
		if result.Status == httpdto.Running {
			break
		}
		select {
		case <-ctx.Done():
			t.Fatalf("HTTP job status = %q, want running: %v", result.Status, ctx.Err())
		case <-ticker.C:
		}
	}

	if result.JobID != jobID.String() {
		t.Errorf("HTTP job_id = %q, want %s", result.JobID, jobID)
	}
	if result.GraphAvailable || result.MetricsAvailable {
		t.Errorf("results should be unavailable: graph=%t metrics=%t", result.GraphAvailable, result.MetricsAvailable)
	}
	if result.Graph != nil {
		t.Error("HTTP graph should be null")
	}
	if result.Metrics == nil || len(result.Metrics) != 0 {
		t.Errorf("HTTP metrics = %#v, want an empty array", result.Metrics)
	}
	if result.Error != nil {
		t.Errorf("unexpected analysis error: %+v", result.Error)
	}
}

func (env *testEnvironment) testDLQ(t *testing.T) {
	jobID := env.createJob(t)
	ctx, cancel := context.WithTimeout(t.Context(), 30*time.Second)
	defer cancel()

	reader := kafka.NewReader(kafka.ReaderConfig{
		Brokers:     []string{env.broker},
		Topic:       "analysis.results.dlq",
		GroupID:     "dlq-test-" + uuid.NewString(),
		StartOffset: kafka.FirstOffset,
	})
	cleanupResource(t, reader.Close)

	key := []byte(jobID.String())
	payload := []byte(`{"status":`)
	checkError(t, env.writer.WriteMessages(ctx, kafka.Message{
		Key: key, Value: payload,
	}), "send invalid JSON")

	message, err := reader.FetchMessage(ctx)
	checkError(t, err, "fetch DLQ message")
	var dlq kafkadto.DLQMessage
	checkError(t, json.Unmarshal(message.Value, &dlq), "decode DLQ message")

	if !bytes.Equal(dlq.Payload, payload) {
		t.Errorf("DLQ payload = %q, want %q", dlq.Payload, payload)
	}
	if !bytes.Equal(dlq.Key, key) {
		t.Errorf("DLQ source key = %q, want %q", dlq.Key, key)
	}
	if !bytes.Equal(message.Key, key) {
		t.Errorf("DLQ Kafka key = %q, want %q", message.Key, key)
	}
	if dlq.JobID == nil || *dlq.JobID != jobID {
		t.Errorf("DLQ job_id = %v, want %s", dlq.JobID, jobID)
	}
	if dlq.Error == "" {
		t.Error("DLQ error is empty")
	}
	if dlq.Topic != "analysis.results" {
		t.Errorf("DLQ source topic = %q, want analysis.results", dlq.Topic)
	}
	if dlq.Partition != 0 || dlq.Offset < 0 {
		t.Errorf("unexpected source position: partition=%d offset=%d", dlq.Partition, dlq.Offset)
	}
	job, err := env.repository.GetJob(ctx, jobID)
	checkError(t, err, "read job after invalid JSON")
	if job.Status != "queued" {
		t.Errorf("job status = %q, want queued", job.Status)
	}
}
