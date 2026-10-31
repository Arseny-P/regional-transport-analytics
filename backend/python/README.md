# Модуль региональной транспортно-логистической аналитики (Python Worker)

Модуль отвечает за извлечение топологии дорожной сети OpenStreetMap, расчет кратчайших автомобильных маршрутов Door-to-Door строго по асфальту с отдельными коннекторами последней мили (`access_connector`), синтез логистического мультиграфа, вычисление топологических метрик (индексы Кански, связность, диаметр) и асинхронную интеграцию с Go-оркестратором через Apache Kafka в микросервисной архитектуре (L3).

---

## 🚀 Быстрый запуск

### 1. Подготовка виртуального окружения
```bash
cd backend/python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Запуск тестов (100% оффлайн)
Все тесты (юнит, интеграционные, валидация контрактов Kafka и расчет метрик) выполняются изолированно без сетевых обращений:
```bash
pytest tests/
```

### 3. Режимы запуска

#### А. Режим фонового микросервиса (Kafka Worker — Спринт 3)
Воркер подключается к Kafka, слушает очередь команд `analysis.commands` и публикует результаты в `analysis.results`:
```bash
# Стандартный production-запуск:
python main.py --worker

# Либо через модуль:
python -m graph_service

# Локальный запуск без поднятого брокера Kafka (in-memory mock транспорт):
python main.py --worker --mock-kafka
```

#### Б. Автономный CLI-режим (Прямой анализ без Kafka)
```bash
# Анализ произвольной территории по координатам BBox:
python main.py --bbox 59.98 29.68 60.03 29.82 --knn 2

# Анализ по названию через геокодирование:
python main.py --place "Кронштадт, Россия" --osm-pois

# Демонстрационный запуск на логистическом кластере Шушары:
python main.py --shushary --knn 3

# Прямой вызов через JSON-контракт Go (DTO):
python main.py --input-json data/example_request.json --output-json data/example_response.json
```

---

## 🏗 Архитектура L3 (`src/graph_service/`)

В соответствии с утвержденной общесистемной архитектурой проекта, модуль организован по принципам чистой слоистой архитектуры L3:

```text
src/graph_service/
├── kafka/              # Взаимодействие с Apache Kafka
│   ├── schemas.py      # DTO контракта (KafkaEnvelope, START, CANCEL, STATUS, RESULT)
│   ├── transport.py    # Абстракция транспорта (AioKafkaTransport, MockKafkaTransport)
│   ├── consumer.py     # Чтение топика analysis.commands
│   ├── producer.py     # Публикация событий в analysis.results (key=job_id)
│   └── worker.py       # Диспетчер воркера: неблокирующий запуск и отмена задач
├── http/               # Сетевые клиенты внешних API
│   └── osm_client.py   # Каскадный клиент к 4 зеркалам Overpass OSM с авто-бэкоффом
├── domain/             # Доменные сущности и инварианты
│   ├── models.py       # LogisticsNode, LogisticsEdge, TerritoryBounds, AnalysisRequest/Response
│   └── errors.py       # Доменные исключения (InvalidParameters, UnsupportedTransport, etc.)
├── application/        # Прикладные сценарии и сервисы
│   ├── build_graph.py  # Сквозной оркестратор TerritoryAnalysisService
│   ├── cancellation.py # Потокобезопасный CancellationToken для graceful отмены
│   ├── graph_serializer.py # Конвертер MultiGraph -> контракт Go (position: [lon, lat])
│   └── metrics_service.py  # Модуль расчета графовых метрик (задача #28)
├── algorithms/         # Вычислительные ядра графов
│   ├── road_network_service.py    # Построение дорожной сети из OSM (OSMnx 2.x)
│   ├── facility_service.py        # Врезка перпендикуляров и проекция узлов (Virtual Nodes)
│   └── logistics_graph_service.py # Синтез мультиграфа Door-to-Door и маршрутизация
├── db/                 # Персистентность и идемпотентность воркера
│   ├── repository.py   # Абстрактный интерфейс JobRepository
│   └── memory_repository.py # In-memory хранилище для тестов и локального запуска
├── config.py           # Конфигурация брокера, путей и таймаутов
└── __main__.py         # Стандартная точка входа для python -m graph_service
```

---

## 📡 Контракт взаимодействия с Go через Kafka

Подробный согласованный контракт зафиксирован в документе [`kafka-go-python-contract.md`](kafka-go-python-contract.md).

### Топики и ключи
| Топик | Направление | Сообщения | Ключ сообщения (Kafka Key) |
|---|---|---|---|
| `analysis.commands` | Go ➔ Python | `START`, `CANCEL` | Строковый `job_id` |
| `analysis.results` | Python ➔ Go | `STATUS`, `RESULT` | Строковый `job_id` |

### Оболочка сообщения (Envelope)
```json
{
  "message_id": "11111111-1111-4111-8111-111111111111",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "START",
  "payload": {}
}
```

### Ключевые инварианты:
1. **Порядок координат:** во входных данных точки задаются именованными полями `latitude` и `longitude`. В исходящем графе координаты вершин `position` и геометрия ребер `geometry` строго передаются в формате GeoJSON: `[долгота, широта]` (`[lon, lat]`).
2. **Идемпотентность:** воркер сохраняет `message_id` в `db/`. При повторном получении дубликата команды `START` повторные вычисления не запускаются, а отдается сохраненный `RESULT`.
3. **Неблокирующая отмена:** расчет графа выполняется в отдельном пуле потоков через `asyncio.to_thread`. При получении `CANCEL` воркер активирует `CancellationToken`, останавливает вычисления и отправляет `STATUS: canceled`.
4. **Метрики (Задача #28):** метрики передаются массивом `{name, value}`. Значения строго проверяются на конечность (запрещены `NaN` и `Infinity`).
5. **Сохранность графа:** если сбой произошел на этапе расчета метрик, готовый граф **не уничтожается** — отправляется `status: failed` с графом и кодом ошибки `metrics_calculation_failed`.

### Стандартные коды ошибок
* `invalid_parameters` — некорректные координаты или вырожденная область (нулевая площадь).
* `unsupported_transport` — передан неподдерживаемый вид транспорта (в Спринте 3 разрешен только `["road"]`).
* `osm_unavailable` — таймаут или недоступность всех зеркал Overpass API.
* `graph_build_failed` — ошибка топологического построения графа.
* `metrics_calculation_failed` — сбой при расчете аналитических метрик графа.
* `internal_error` — непредвиденная внутренняя ошибка воркера.

---

## ⚙️ Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Адрес брокера Kafka (в Docker: `kafka:19092`) |
| `KAFKA_GROUP_ID` | `graph-service-worker` | Идентификатор Consumer Group воркера |
| `KAFKA_COMMANDS_TOPIC` | `analysis.commands` | Топик входящих команд от Go-оркестратора |
| `KAFKA_RESULTS_TOPIC` | `analysis.results` | Топик исходящих статусов и результатов |
| `DATA_DIR` | `data` | Каталог кэша графов (`.graphml`) и GeoJSON артефактов |
| `CACHE_DIR` | `cache` | Каталог кэша запросов OSMnx |

---

## 📂 Примеры эталонных сообщений
В каталоге `data/` подготовлены эталонные JSON-файлы по контракту:
* `data/example_kafka_start.json` — пример команды запуска `START`.
* `data/example_kafka_cancel.json` — пример команды отмены `CANCEL`.
* `data/example_kafka_status_running.json` — событие перехода в статус `running`.
* `data/example_kafka_result_completed.json` — успешный результат с графом `[lon, lat]` и метриками.
* `data/example_kafka_result_failed.json` — результат с ошибкой и кодом.
