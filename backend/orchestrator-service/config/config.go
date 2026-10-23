package config

import (
	"log"
	"os"
	"time"

	"github.com/ilyakaznacheev/cleanenv"
)

type Config struct {
	App      APP          `yaml:"app"`
	HTTP     HTTP         `yaml:"http"`
	Postgres PostgresDB   `yaml:"postgres_db"`
	MinIO    MinIOStorage `yaml:"minio_storage"`
	Kafka    KafkaClient  `yaml:"kafka_client"`
}

type APP struct {
	AppName  string `yaml:"app_name" env:"APP_NAME" env-default:"orchestrator"`
	LogLevel string `yaml:"log_level" env:"LOG_LEVEL" env-default:"info"`
}

type HTTP struct {
	Address         string        `yaml:"address" env:"HTTP_ADDRESS" env-default:":8080"`
	TimeOut         time.Duration `yaml:"timeout" env:"HTTP_TIMEOUT" env-default:"30s"`
	ShutdownTimeout time.Duration `yaml:"shutdown_timeout" env:"SHUTDOWN_TIMEOUT" env-default:"10s"`
}
type PostgresDB struct {
	DSN string `yaml:"dsn" env:"DSN" env-required:"true"`
}

type MinIOStorage struct {
	Endpoint  string `yaml:"endpoint" env:"S3_ENDPOINT" env-default:"localhost:9000"`
	AccessKey string `yaml:"access_key" env:"S3_ACCESS_KEY" env-required:"true"`
	SecretKey string `yaml:"secret_key" env:"S3_SECRET_KEY" env-required:"true"`
}

type KafkaClient struct {
	Address string `yaml:"address" env:"KAFKA_ADDRESS" env-default:"localhost:9092"`
}

func MustLoad() *Config {
	configPath := os.Getenv("CONFIG_PATH")
	var cfg Config

	if configPath != "" {
		if err := cleanenv.ReadConfig(configPath, &cfg); err != nil {
			log.Fatal("failed to read config: check CONFIG_PATH, required DSN/S3 variables and duration values")
		}
	} else {
		if err := cleanenv.ReadEnv(&cfg); err != nil {
			log.Fatal("failed to read env: check required DSN/S3 variables and duration values")
		}
	}
	return &cfg
}
