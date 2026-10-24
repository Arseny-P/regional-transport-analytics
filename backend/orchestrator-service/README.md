# Go-бэкенд: orchestrator

Сервис пока запускает HTTP `GET /healthz`, подключается к PostgreSQL и MinIO,
создаёт бакет `regions` и инициализирует Kafka Reader/Writer. Бизнес-ручек пока нет.

## Что установить

- Для запуска в Docker: Docker Desktop с Linux containers и Compose v2.
- Для команд Makefile: GNU Make. На Windows нужен Git for Windows с `sh` в `PATH`.
- Для запуска Go на компьютере: Go 1.27.1.

Все команды ниже выполняются из корня репозитория.

## Запуск в Docker

При первом запуске создай `.env`, если его ещё нет:

```powershell
# Windows / PowerShell
Copy-Item .env.example .env
```

```sh
# Linux / Git Bash
cp .env.example .env
```

В `.env` заполни `GO_DB_NAME`, `GO_DB_USER`, `GO_DB_PASSWORD`,
`S3_ACCESS_KEY` и `S3_SECRET_KEY`. Пример содержит имена базы и пользователя
`orchestrator`; пароли замени своими. `.env` не коммитится.

```sh
make build
docker compose ps
docker compose logs -f orchestrator
```

`make build` собирает образы и запускает четыре сервиса. MinIO собирается из
исходников, поэтому первая сборка может занять несколько минут.
`make run` запускает окружение без принудительной пересборки.

Без Make та же команда запуска:

```sh
docker compose up -d --build
```

| Сервис | Адрес с компьютера | Адрес внутри Docker |
| --- | --- | --- |
| Go HTTP | `http://localhost:8080/healthz` | `orchestrator:8080` |
| PostgreSQL | `localhost:5432` | `postgres:5432` |
| Kafka | `localhost:9092` | `kafka:19092` |
| MinIO API | `localhost:9000` | `minio:9000` |
| MinIO Console | `http://localhost:9001` | `minio:9001` |

В MinIO Console используй `S3_ACCESS_KEY` как логин, `S3_SECRET_KEY` как пароль.

## Конфигурация

`config/config.go` читает YAML по `CONFIG_PATH` и переменные окружения.
Без `CONFIG_PATH` используется только окружение. Переменные имеют приоритет над YAML.

`CONFIG_PATH` выбирает источник настроек, а не способ запуска:

- Весь backend в Docker: `make build`. Путь к YAML указывать не нужно.
- Go на компьютере с YAML: укажи `CONFIG_PATH=config/config.yaml` в корневом `.env`.
- Go на компьютере без YAML: оставь `CONFIG_PATH=` пустым в `.env`.

Для Go на компьютере PostgreSQL, Kafka и MinIO должны быть доступны отдельно.
Перед запуском заполни в `.env` `DSN`, `S3_ACCESS_KEY` и `S3_SECRET_KEY`:
в примере YAML эти обязательные значения пустые. Используй локальные адреса сервисов.

Для YAML укажи в `.env`:

```dotenv
CONFIG_PATH=config/config.yaml
```

Затем из корня проекта:

```sh
make run-local
```

Путь здесь считается от `backend/orchestrator-service`, куда переходит Make.
Makefile сервиса читает корневой `.env` и передаёт его переменные Go-процессу.
Используй формат `KEY=value` без кавычек, как в `.env.example`.
При прямом запуске `go run ./cmd/app` без Make переменные задаются в терминале или IDE.

В Docker настройки читаются только из окружения, YAML не подключается.
В секции `orchestrator.environment` файла `compose.yaml` заданы
`APP_NAME`, `LOG_LEVEL`, `HTTP_ADDRESS`, `HTTP_TIMEOUT`, `SHUTDOWN_TIMEOUT`,
`DSN`, `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `KAFKA_ADDRESS`.
Их имена совпадают с `env`-тегами Go-конфига.

Compose сам читает корневой `.env` и передаёт выбранные значения контейнерам.
При `make run-local` это делает Make. Go-приложение самостоятельно `.env` не загружает;
godotenv в код приложения не добавляется.

## Команды разработки

```sh
make tools        # установить golangci-lint 2.14.0 и Goose 3.26.0 в bin сервиса
make fmt          # отформатировать Go-код
make fmt-check    # проверить форматирование без изменения файлов
make vet          # go vet
make lint         # golangci-lint
make -C backend/orchestrator-service build  # собрать только Go-приложение
```

Для этих команд нужен локальный Go. `make test` запускает имеющиеся тесты с `-race`
и требует CGO и C-компилятор. GitHub Actions запускает fmt-check, vet, линтер,
сборку и команду тестов при изменениях Go-сервиса и его инфраструктуры.

Goose установлен как CLI; SQL-миграций приложения пока нет, при старте они не запускаются.
Команды `make migrate-status`, `make migrate-up`, `make migrate-down` читают
`GOOSE_DRIVER=postgres` и `GOOSE_DBSTRING=${DSN}` из корневого `.env`.
Файл загружает сам CLI Goose через `-env ../../.env`; Go-приложение по-прежнему
не загружает `.env` самостоятельно.

## Логи и остановка

```sh
docker compose logs -f             # все сервисы
docker compose logs -f orchestrator
make stop                         # остановить окружение, сохранив данные
make run                          # запустить снова
```

Локальный Go-процесс останавливается через `Ctrl+C`. В Docker приложение получает
`SIGTERM` и завершает HTTP-запросы перед выходом.

Данные находятся в volumes PostgreSQL, Kafka и MinIO. Если намеренно нужно удалить
все данные этого окружения, для этого есть отдельная команда `make stop-volumes`.
Изменение пароля PostgreSQL в `.env` не меняет пароль в уже созданной базе.
