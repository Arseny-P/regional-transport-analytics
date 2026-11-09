FROM python:3.11-slim

# Системные переменные окружения Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app/src:/app"

# Установка системных библиотек (SSL-сертификаты для Overpass OSM, libgomp для scipy/scikit-learn)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Создание непривилегированного пользователя для безопасной работы внутри контейнера
RUN groupadd -g 10001 appuser && \
    useradd -u 10001 -g appuser -s /bin/bash -m appuser

# Кэширование слоя зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода приложения, тестов и эталонных данных
COPY pyproject.toml .
COPY src/ ./src/
COPY main.py .
COPY data/ ./data/
COPY tests/ ./tests/

# Подготовка каталогов для артефактов и кэша OSM с правами доступа для appuser
RUN mkdir -p /app/data /app/cache && \
    chown -R appuser:appuser /app

USER appuser

# Значения переменных окружения по умолчанию для работы в сети docker compose
ENV KAFKA_BOOTSTRAP_SERVERS="kafka:19092" \
    KAFKA_GROUP_ID="graph-service-worker" \
    KAFKA_COMMANDS_TOPIC="analysis.commands" \
    KAFKA_RESULTS_TOPIC="analysis.results" \
    DATA_DIR="/app/data" \
    CACHE_DIR="/app/cache"

# Точка входа по умолчанию: запуск фонового воркера Kafka
CMD ["python", "-m", "graph_service"]

