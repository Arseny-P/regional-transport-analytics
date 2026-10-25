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
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
	"github.com/pressly/goose/v3"
	"github.com/segmentio/kafka-go"

	"orchestrator-service/config"
)

func RunMigrations(dsn string) error {
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return err
	}
	defer db.Close()

	return goose.Up(db, "migrations")
}

func runApp() error {
	cfg := config.MustLoad()
	var level slog.Level
	switch strings.ToUpper(cfg.App.LogLevel) {
	case "DEBUG":
		level = slog.LevelDebug
	case "INFO":
		level = slog.LevelInfo
	case "WARN":
		level = slog.LevelWarn
	case "ERROR":
		level = slog.LevelError
	default:
		panic("unknown log level: " + cfg.App.LogLevel)
	}

	options := &slog.HandlerOptions{Level: level}
	var handler slog.Handler = slog.NewTextHandler(os.Stdout, options)
	logger := slog.New(handler).With("service", cfg.App.AppName)
	slog.SetDefault(logger)

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

	kafkaWriter := &kafka.Writer{
		Addr:         kafka.TCP(cfg.Kafka.Address),
		RequiredAcks: kafka.RequireAll,
	}
	kafkaReader := kafka.NewReader(kafka.ReaderConfig{
		Brokers: []string{cfg.Kafka.Address},
		Topic:   "analysis.results",
		GroupID: "orchestrator",
	})
	defer func() {
		if closeErr := errors.Join(kafkaReader.Close(), kafkaWriter.Close()); closeErr != nil {
			logger.Error("failed to close Kafka reader/writer", "error", closeErr)
		}
	}()
	logger.Info("Kafka reader and writer initialized")
	startupCancel()

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	server := http.Server{
		Addr: cfg.HTTP.Address, Handler: mux,
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
	if err := runApp(); err != nil {
		slog.Error("orchestrator stopped", "error", err)
		os.Exit(1)
	}
}
