package main

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
	"github.com/pressly/goose/v3"

	"orchestrator-service/config"
	kafkaproducer "orchestrator-service/internal/adapter/kafka"
	miniostorage "orchestrator-service/internal/adapter/minIO"
	"orchestrator-service/internal/adapter/postgres"
	httpcontroller "orchestrator-service/internal/controller/http"
	kafkacontroller "orchestrator-service/internal/controller/kafka"
	"orchestrator-service/internal/domain"
	"orchestrator-service/internal/usecase"
)

func RunMigrations(dsn string) error {
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return err
	}
	defer func() { _ = db.Close() }()

	return goose.Up(db, "migrations")
}

func newLogger(logLevel, appName string) *slog.Logger {
	var level slog.Level
	switch strings.ToUpper(logLevel) {
	case "DEBUG":
		level = slog.LevelDebug
	case "INFO":
		level = slog.LevelInfo
	case "WARN":
		level = slog.LevelWarn
	case "ERROR":
		level = slog.LevelError
	default:
		panic("unknown log level: " + logLevel)
	}

	options := &slog.HandlerOptions{Level: level}
	var handler slog.Handler = slog.NewTextHandler(os.Stdout, options)
	return slog.New(handler).With("service", appName)
}

func seedDemoRegion(ctx context.Context, db *pgxpool.Pool, storage *miniostorage.MinIO) (uuid.UUID, error) {
	const objectKey domain.ObjectKey = "spb.geojson"
	if err := storage.StatObject(ctx, objectKey); err != nil {
		if !errors.Is(err, domain.ErrRegionNotFound) {
			return uuid.Nil, fmt.Errorf("check demo region: %w", err)
		}
		if uploadErr := storage.FPutObject(ctx, objectKey, "testdata/spb.geojson"); uploadErr != nil {
			return uuid.Nil, fmt.Errorf("upload demo region: %w", uploadErr)
		}
	}

	var regionID uuid.UUID
	err := db.QueryRow(ctx, `INSERT INTO regions (object_key) VALUES ($1)
		ON CONFLICT (object_key) DO UPDATE SET object_key = EXCLUDED.object_key
		RETURNING id`, string(objectKey)).Scan(&regionID)
	if err != nil {
		return uuid.Nil, fmt.Errorf("register demo region: %w", err)
	}
	return regionID, nil
}

func runApp(cfg *config.Config, logger *slog.Logger) error {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	startupCtx, startupCancel := context.WithTimeout(ctx, 30*time.Second)
	defer startupCancel()

	poolConfig, err := pgxpool.ParseConfig(cfg.Postgres.DSN)
	if err != nil {
		return fmt.Errorf("invalid PostgreSQL DSN")
	}
	poolConfig.ConnConfig.ConnectTimeout = 5 * time.Second
	db, err := pgxpool.NewWithConfig(startupCtx, poolConfig)
	if err != nil {
		return fmt.Errorf("initialize PostgreSQL pool: %w", err)
	}
	defer db.Close()
	if err = db.Ping(startupCtx); err != nil {
		return fmt.Errorf("connect PostgreSQL: %w", err)
	}
	logger.Info("PostgreSQL connected")
	if err = RunMigrations(cfg.Postgres.DSN); err != nil {
		return fmt.Errorf("apply PostgreSQL migrations: %w", err)
	}
	logger.Info("PostgreSQL migrations applied")
	repository := postgres.NewDB(db)

	minioClient, err := minio.New(cfg.MinIO.Endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(cfg.MinIO.AccessKey, cfg.MinIO.SecretKey, ""),
		Secure: false,
	})
	if err != nil {
		return fmt.Errorf("initialize MinIO client: %w", err)
	}

	const regionBucket = "regions"
	exists, err := minioClient.BucketExists(startupCtx, regionBucket)
	if err != nil {
		return fmt.Errorf("check MinIO bucket: %w", err)
	}
	if !exists {
		if err = minioClient.MakeBucket(startupCtx, regionBucket, minio.MakeBucketOptions{}); err != nil {
			exists, checkErr := minioClient.BucketExists(startupCtx, regionBucket)
			if checkErr != nil || !exists {
				return fmt.Errorf("create MinIO bucket: %w", err)
			}
		}
	}
	logger.Info("MinIO ready", "bucket", regionBucket)
	storage := miniostorage.NewMinio(minioClient)
	regionID, err := seedDemoRegion(startupCtx, db, storage)
	if err != nil {
		return err
	}
	logger.Info("demo region ready", "region_id", regionID, "object_key", "spb.geojson")

	producer := kafkaproducer.NewProducer(cfg.Kafka.Address)
	defer func() {
		if closeErr := producer.Close(); closeErr != nil {
			logger.Error("failed to close Kafka producer", "error", closeErr)
		}
	}()
	logger.Info("Kafka producer initialized", "topic", "analysis.commands")
	startupCancel()

	orchestrator := usecase.NewUsecase(repository, repository, storage, logger.With("component", "analysis"))
	controller := httpcontroller.NewHTTPController(orchestrator, logger.With("component", "http"))
	worker := usecase.NewOutboxWorker(producer, repository, logger.With("component", "outbox"))
	workerCtx, stopWorker := context.WithCancel(ctx)
	var workers sync.WaitGroup
	defer func() {
		stopWorker()
		workers.Wait()
	}()
	workers.Add(1)
	go func() {
		defer workers.Done()
		worker.Run(workerCtx)
	}()
	logger.Info("outbox worker started")

	const consumerCount = 5
	for i := 0; i < consumerCount; i++ {
		consumer := kafkacontroller.NewConsumer(cfg.Kafka.Address)
		consumerLogger := logger.With("component", "inbox", "consumer_id", i+1)
		inboxWorker := usecase.NewInboxWorker(consumer, repository, producer, consumerLogger)
		workers.Add(1)
		go func() {
			defer workers.Done()
			defer func() {
				if closeErr := consumer.Close(); closeErr != nil {
					consumerLogger.Error("failed to close Kafka consumer", "error", closeErr)
				}
			}()
			inboxWorker.Run(workerCtx)
		}()
	}

	logger.Info("inbox workers started", "count", consumerCount, "topic", "analysis.results", "group_id", "analysis1")

	server := http.Server{
		Addr: cfg.HTTP.Address, Handler: controller.Routes(),
		ReadHeaderTimeout: 5 * time.Second, ReadTimeout: cfg.HTTP.TimeOut,
		WriteTimeout: cfg.HTTP.TimeOut, IdleTimeout: 60 * time.Second,
	}
	listener, err := net.Listen("tcp", server.Addr)
	if err != nil {
		return fmt.Errorf("listen HTTP: %w", err)
	}
	serverErrors := make(chan error, 1)
	go func() {
		serverErrors <- server.Serve(listener)
	}()
	logger.Info("HTTP server started", "address", server.Addr)

	select {
	case <-ctx.Done():
		logger.Info("shutdown requested")
	case err = <-serverErrors:
		return fmt.Errorf("serve HTTP: %w", err)
	}

	gracefulCtx, gracefulCancel := context.WithTimeout(context.Background(), cfg.HTTP.ShutdownTimeout)
	defer gracefulCancel()
	if err = server.Shutdown(gracefulCtx); err != nil {
		return errors.Join(fmt.Errorf("shutdown HTTP: %w", err), server.Close())
	}
	if err = <-serverErrors; !errors.Is(err, http.ErrServerClosed) {
		return fmt.Errorf("stop HTTP: %w", err)
	}
	logger.Info("HTTP server stopped")
	return nil
}

func main() {
	cfg := config.MustLoad()
	logger := newLogger(cfg.App.LogLevel, cfg.App.AppName)
	slog.SetDefault(logger)
	if err := runApp(cfg, logger); err != nil {
		logger.Error("orchestrator stopped", "error", err)
		os.Exit(1)
	}
}
