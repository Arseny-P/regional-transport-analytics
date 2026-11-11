package integration

import (
	"context"
	"database/sql"
	"log/slog"
	"net/http/httptest"
	kafkaproducer "orchestrator-service/internal/adapter/kafka"
	"orchestrator-service/internal/adapter/postgres"
	httpcontroller "orchestrator-service/internal/controller/http"
	kafkacontroller "orchestrator-service/internal/controller/kafka"
	"orchestrator-service/internal/domain"
	"orchestrator-service/internal/usecase"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/segmentio/kafka-go"
	"github.com/testcontainers/testcontainers-go"
	kafkacontainer "github.com/testcontainers/testcontainers-go/modules/kafka"
	pgcontainer "github.com/testcontainers/testcontainers-go/modules/postgres"
)

type testEnvironment struct {
	pool       *pgxpool.Pool
	repository *postgres.DB
	broker     string
	writer     *kafka.Writer
	server     *httptest.Server
}

func newTestEnvironment(t *testing.T) *testEnvironment {
	t.Helper()
	pool := startTestPostgres(t)
	broker := startTestKafka(t)
	env := &testEnvironment{
		pool: pool, repository: postgres.NewDB(pool), broker: broker,
		writer: &kafka.Writer{
			Addr: kafka.TCP(broker), Topic: "analysis.results",
			RequiredAcks: kafka.RequireAll, Balancer: &kafka.Hash{},
		},
	}
	cleanupResource(t, env.writer.Close)
	consumer := kafkacontroller.NewConsumer(broker)
	cleanupResource(t, consumer.Close)
	producer := kafkaproducer.NewProducer(broker)
	cleanupResource(t, producer.Close)

	orchestrator := usecase.NewUsecase(env.repository, env.repository, nil, slog.Default())
	controller := httpcontroller.NewHTTPController(orchestrator, orchestrator, nil, slog.Default())
	env.server = httptest.NewServer(controller.Routes())
	t.Cleanup(env.server.Close)

	ctx, cancel := context.WithCancel(t.Context())
	worker := usecase.NewInboxWorker(consumer, env.repository, producer, slog.Default())
	workerDone := make(chan struct{})
	go func() {
		defer close(workerDone)
		worker.Run(ctx)
	}()
	t.Cleanup(func() {
		cancel()
		select {
		case <-workerDone:
		case <-time.After(5 * time.Second):
			t.Error("inbox worker did not stop after context cancellation")
		}
	})
	return env
}

func checkError(t *testing.T, err error, operation string) {
	t.Helper()
	if err != nil {
		t.Fatalf("%s: %v", operation, err)
	}
}

func cleanupResource(t *testing.T, closeResource func() error) {
	t.Helper()
	t.Cleanup(func() {
		if err := closeResource(); err != nil {
			t.Errorf("close test resource: %v", err)
		}
	})
}

func startTestPostgres(t *testing.T) *pgxpool.Pool {
	t.Helper()
	ctx := t.Context()

	container, err := pgcontainer.Run(ctx, "postgres:17-alpine",
		pgcontainer.WithDatabase("analysis_test"),
		pgcontainer.WithUsername("test"),
		pgcontainer.WithPassword("test"),
		pgcontainer.BasicWaitStrategies(),
	)

	testcontainers.CleanupContainer(t, container)

	checkError(t, err, "start PostgreSQL")

	dsn, err := container.ConnectionString(ctx, "sslmode=disable")

	checkError(t, err, "get PostgreSQL address")

	migrationDB, err := sql.Open("pgx", dsn)

	checkError(t, err, "open migration connection")

	cleanupResource(t, migrationDB.Close)

	err = goose.Up(migrationDB, "../../migrations")

	checkError(t, err, "prepare migrations")

	pool, err := pgxpool.New(ctx, dsn)

	checkError(t, err, "create PostgreSQL pool")

	t.Cleanup(pool.Close)

	checkError(t, pool.Ping(ctx), "connect PostgreSQL")
	return pool
}

func startTestKafka(t *testing.T) string {
	t.Helper()
	ctx := t.Context()

	container, err := kafkacontainer.Run(ctx, "confluentinc/confluent-local:7.5.0")

	testcontainers.CleanupContainer(t, container)

	checkError(t, err, "start Kafka")

	brokers, err := container.Brokers(ctx)

	checkError(t, err, "get Kafka address")

	if len(brokers) == 0 {
		t.Fatal("Kafka returned no broker addresses")
	}

	transport := &kafka.Transport{}

	t.Cleanup(transport.CloseIdleConnections)

	client := &kafka.Client{Addr: kafka.TCP(brokers...), Transport: transport}

	response, err := client.CreateTopics(ctx, &kafka.CreateTopicsRequest{
		Topics: []kafka.TopicConfig{
			{Topic: "analysis.results", NumPartitions: 1, ReplicationFactor: 1},
			{Topic: "analysis.results.dlq", NumPartitions: 1, ReplicationFactor: 1},
		},
	})

	checkError(t, err, "create Kafka topics")

	for topic, topicErr := range response.Errors {
		checkError(t, topicErr, "create topic "+topic)
	}

	return brokers[0]
}

func (env *testEnvironment) createJob(t *testing.T) uuid.UUID {
	t.Helper()
	ctx := t.Context()
	regionID := uuid.New()
	_, err := env.pool.Exec(ctx, "INSERT INTO regions (id, object_key) VALUES ($1, $2)", regionID, regionID.String()+".geojson")
	checkError(t, err, "create test region")

	job := domain.Job{
		JobID: uuid.New(), RegionID: regionID, Status: "queued",
		TransportTypes: []domain.Transport{domain.Road},
		Point1:         domain.MapPoint{Latitude: 59.93, Longitude: 30.32},
		Point2:         domain.MapPoint{Latitude: 59.94, Longitude: 30.33},
	}
	checkError(t, env.repository.CreateJob(ctx, &job), "create test job")
	return job.JobID
}
