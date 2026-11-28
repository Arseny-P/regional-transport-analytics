# Модуль региональной транспортно-логистической аналитики (Python Worker)

Модуль отвечает за извлечение топологии транспортных сетей OpenStreetMap, построение расчетных графов, вычисление топологических метрик и асинхронную интеграцию с Go-оркестратором через Apache Kafka в микросервисной архитектуре (L3).

Поддерживает два вида транспорта:
* **Автомобильный транспорт (`transport: "road"`)**: извлечение дорожной сети, врезка складов/терминалов через виртуальные узлы и коннекторы последней мили (`access_connector`), расчет кратчайших маршрутов Door-to-Door строго по асфальту, вычисление метрик доступности, связности и транзитности перекрестков.
* **Железнодорожный транспорт (`transport: "rail"`)**: построение упрощенного физического графа железнодорожной сети (только действующие магистральные и подъездные пути `railway=rail`), топологическое сжатие промежуточных узлов степени 2 (`degree == 2`) с сохранением плавной кривизны путей, мульти-якорная привязка станций без фиктивных ребер, выделение стрелочных переводов и тупиков, расчет 5 согласованных метрик MVP (протяженность, стрелки, станции, расстояние между станциями, Betweenness Centrality стрелок).

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
Все 100 тестов (юнит, интеграционные, валидация контрактов Kafka, расчет дорожных и железнодорожных метрик) выполняются изолированно без сетевых обращений за ~5.5 секунд:
```bash
pytest tests/
```

### 3. Режимы запуска

#### А. Режим фонового микросервиса (Kafka Worker)
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

##### 1. Автомобильный анализ (`--transport road`, по умолчанию)
```bash
# Анализ территории по координатам BBox:
python main.py --bbox 59.98 29.68 60.03 29.82 --knn 2

# Анализ по названию через геокодирование:
python main.py --place "Кронштадт, Россия" --osm-pois

# Демонстрационный запуск на логистическом кластере Шушары:
python main.py --shushary --knn 3

# Прямой вызов через JSON-контракт Go (DTO):
python main.py --input-json data/example_request.json --output-json data/example_response.json
```

##### 2. Железнодорожный анализ (`--rail` или `--transport rail`)
```bash
# Анализ ЖД сети Шушар на оффлайн-фикстурах:
python main.py --rail --shushary

# Анализ произвольного ЖД узла (например, Санкт-Петербург) с загрузкой из Overpass API:
python main.py --rail --bbox 59.90 30.30 59.95 30.40 --refetch

# Анализ ЖД по названию территории:
python main.py --rail --place "Санкт-Петербург"

# При анализе автоматически формируется GeoJSON со стилизацией (стрелки, тупики, пути):
# data/bbox_..._rail.geojson (можно открыть на https://geojson.io)
```

#### В. Запуск через Docker и Docker Compose
Сервис полностью контейнеризован и интегрирован в общий `compose.yaml`:
```bash
# Сборка и запуск всего стека (Go Orchestrator, Python Worker, Kafka, Postgres, MinIO):
docker compose up -d --build

# Либо запуск только Kafka и Python воркера:
docker compose up -d kafka graph-service

# Просмотр логов воркера:
docker compose logs -f graph-service
```

---

## 🏗 Архитектура L3 (`src/graph_service/`)

В соответствии с чистой слоистой архитектурой L3, модуль разделен на следующие уровни ответственности:

```text
src/graph_service/
├── kafka/                  # Взаимодействие с Apache Kafka
│   ├── schemas.py          # DTO контракта (KafkaEnvelope, START, CANCEL, STATUS, RESULT)
│   ├── transport.py        # Абстракция транспорта (AioKafkaTransport, MockKafkaTransport)
│   ├── consumer.py         # Чтение топика analysis.commands
│   ├── producer.py         # Публикация событий в analysis.results (key=job_id)
│   └── worker.py           # Диспетчер воркера: маршрутизация road / rail, отмена задач
├── http/                   # Сетевые клиенты внешних API
│   └── osm_client.py       # Клиент с ротацией к 4 зеркалам Overpass API и геокодированием
├── domain/                 # Доменные сущности, инварианты и перечисления
│   ├── models.py           # Node, Edge, RailObjectType, RailNodeKind, RailConnectionStatus, etc.
│   └── errors.py           # Доменные исключения (InvalidParameters, UnsupportedTransport, etc.)
├── application/            # Прикладные сценарии и оркестрация
│   ├── build_graph.py      # Оркестратор TerritoryAnalysisService (run_road / run_rail)
│   ├── cancellation.py     # Потокобезопасный CancellationToken для graceful отмены
│   ├── graph_serializer.py # Сериализация графов (position [lon, lat], segment_id)
│   ├── metrics_service.py  # Расчет метрик дорожного графа маршрутов
│   └── rail_metrics_service.py # Расчет 5 метрик ЖД сети (длина, стрелки, станции, betweenness)
├── algorithms/             # Вычислительные ядра графов
│   ├── road_network_service.py    # Построение дорожной сети из OSM (OSMnx 2.x)
│   ├── facility_service.py        # Проекция складов, врезка виртуальных узлов и коннекторов
│   ├── logistics_graph_service.py # Синтез Door-to-Door мультиграфа и маршрутизация
│   ├── rail_network_service.py    # ЖД сеть: BBox-обрезка, degree-2 сжатие, экспорт в GeoJSON
│   └── rail_facility_service.py   # Выделение ЖД станций, отсев метро, multi-anchor binding
├── fixtures/               # Встроенные эталонные фикстуры для оффлайн-тестирования
│   ├── kronshtadt_roads.graphml
│   ├── kronshtadt_facilities.json
│   ├── shushary_rail_ways.json
│   └── shushary_rail_objects.json
├── db/                     # Персистентность и идемпотентность воркера
│   ├── repository.py       # Абстрактный интерфейс JobRepository
│   └── memory_repository.py # In-memory репозиторий для тестов и локального запуска
├── config.py               # Конфигурация брокера, путей, таймаутов и режима оффлайн
└── __main__.py             # Точка входа для python -m graph_service
```

---

## 🚆 Особенности модели железнодорожного графа (Спринт 6)

1. **Топологическое упрощение (Degree-2 Simplification):**
   - Узлы со степенью 2 на прямых и криволинейных участках путей сжимаются в единые физические сегменты `G_simple`.
   - В топологии графа остаются только стрелочные переводы (`switch`, степень $\ge 3$), тупики (`buffer_stop`, степень $= 1$), граничные узлы BBox (`boundary_entry`) и подтвержденные узлы станций.
   - Точные географические координаты сжатых точек сохраняются в поле `geometry` ребра в формате GeoJSON `[[lon, lat], ...]`.
2. **Сериализация ЖД ребер:**
   - В отличие от дорог, ребра железнодорожной сети **не содержат атрибут `edge_type`**.
   - Обе встречные направленные дуги одного физического пути сохраняют идентичный `segment_id`.
3. **Мульти-якорные станции (Multi-Anchor Station Binding):**
   - Станция представляет собой единый логический объект `rail_facility`, но может подключаться к нескольким путям через список `anchor_node_ids`.
   - **Строгий запрет «бесплатных соединений»:** искусственные рёбра между точками подключения станции не создаются. Перемещение между путями возможно только по реальным рельсам.
4. **Метрики ЖД сети MVP:**
   - `total_rail_length_km` — общая физическая длина путей (км).
   - `station_count` — число подтвержденных станций.
   - `switch_count` — количество стрелочных переводов.
   - `nearest_station_distance_m` — кратчайшее расстояние между станциями по рельсам (с перебором пар якорей).
   - `betweenness_centrality` — посредничество стрелок на графе центральности с весами в сантиметрах (`weight_cm`).

---

## 📡 Контракт взаимодействия с Go через Kafka

Подробный контракт зафиксирован в документе [`kafka-go-python-contract.md`](kafka-go-python-contract.md).

### Топики и ключи
| Топик | Направление | Сообщения | Ключ сообщения (Kafka Key) |
|---|---|---|---|
| `analysis.commands` | Go ➔ Python | `START`, `CANCEL` | Строковый `job_id` |
| `analysis.results` | Python ➔ Go | `STATUS`, `RESULT` | Строковый `job_id` |

### Поддерживаемые режимы транспорта
* Поле `transports: ["road"]` или `transport: "road"` — автомобильный анализ.
* Поле `transports: ["rail"]` или `transport: "rail"` — железнодорожный анализ.
* Запрос смешанных режимов (`["road", "rail"]`, `["all"]`) или неподдерживаемых видов транспорта возвращает ошибку `INVALID_TRANSPORT_MODE`.

### Ключевые инварианты:
1. **Порядок координат:** во входных данных координаты задаются именованными полями `latitude` и `longitude`. В исходящем графе координаты вершин `position` и геометрия ребер `geometry` строго передаются в формате GeoJSON: `[долгота, широта]` (`[lon, lat]`).
2. **Идемпотентность:** воркер сохраняет `message_id` в `db/`. При повторном получении дубликата команды `START` повторные вычисления не запускаются, а отдается сохраненный `RESULT`.
3. **Неблокирующая отмена:** вычисления выполняются в пуле потоков через `asyncio.to_thread`. При получении `CANCEL` воркер активирует `CancellationToken` и отправляет `STATUS: canceled`.
4. **Метрики:** метрики передаются массивом `{name, value, node_id}`. Числовые значения округляются до 6 знаков (`round(val, 6)`), запрещены `NaN` и `Infinity`.
5. **Сохранность графа:** если сбой произошел на этапе расчета метрик, готовый граф не уничтожается — отправляется `status: failed` с сохраненным графом и кодом ошибки `metrics_calculation_failed`.

---

## ⚙️ Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Адрес брокера Kafka (в Docker: `kafka:19092`) |
| `KAFKA_GROUP_ID` | `graph-service-worker` | Идентификатор Consumer Group воркера |
| `KAFKA_COMMANDS_TOPIC` | `analysis.commands` | Топик входящих команд от Go-оркестратора |
| `KAFKA_RESULTS_TOPIC` | `analysis.results` | Топик исходящих статусов и результатов |
| `OSM_OFFLINE_MODE` | `false` | Принудительный оффлайн-режим (работа только по локальным фикстурам) |
| `DATA_DIR` | `data` | Каталог кэша графов (`.graphml`) и GeoJSON артефактов |
| `CACHE_DIR` | `cache` | Каталог кэша запросов OSMnx / Overpass |

---

## 📂 Примеры эталонных сообщений
В каталоге `data/` подготовлены эталонные JSON-файлы:
* `data/example_kafka_start.json` — пример команды запуска `START` (road).
* `data/example_kafka_cancel.json` — пример команды отмены `CANCEL`.
* `data/example_kafka_status_running.json` — событие перехода в статус `running`.
* `data/example_kafka_result_completed.json` — результат дорожного анализа.
* `data/example_kafka_result_rail_completed.json` — результат железнодорожного анализа.
* `data/example_rail_graph_response.json` — пример REST/RPC ответа ЖД графа для фронтенда.
* `data/example_kafka_result_failed.json` — результат с ошибкой и кодом.
