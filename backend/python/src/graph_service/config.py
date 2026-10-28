import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class OverpassSettings:
    mirrors: List[str] = field(default_factory=lambda: [
        "https://overpass-api.de/api",
        "https://overpass.kumi.systems/api",
        "https://overpass.private.coffee/api",
        "https://maps.mail.ru/osm/tools/overpass/api",
    ])
    requests_timeout_sec: int = 60


@dataclass
class KafkaSettings:
    bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    group_id: str = os.getenv("KAFKA_GROUP_ID", "graph-service-worker")
    commands_topic: str = os.getenv("KAFKA_COMMANDS_TOPIC", "analysis.commands")
    results_topic: str = os.getenv("KAFKA_RESULTS_TOPIC", "analysis.results")


@dataclass
class ServiceConfig:
    data_dir: str = os.getenv("DATA_DIR", "data")
    cache_dir: str = os.getenv("CACHE_DIR", "cache")
    default_osm_facilities_limit: int = 100
    overpass: OverpassSettings = field(default_factory=OverpassSettings)
    kafka: KafkaSettings = field(default_factory=KafkaSettings)


config = ServiceConfig()
