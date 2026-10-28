import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class CommandType(str, Enum):
    START = "START"
    CANCEL = "CANCEL"


class EventType(str, Enum):
    STATUS = "STATUS"
    RESULT = "RESULT"


class TaskStatus(str, Enum):
    RUNNING = "running"
    CANCELED = "canceled"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class MapPoint:
    latitude: float
    longitude: float


@dataclass
class AreaPayload:
    first_point: MapPoint
    second_point: MapPoint

    def to_bounds(self) -> tuple[float, float, float, float]:
        """
        Возвращает кортеж (west, south, east, north) в соответствии с контрактом:
        west  = min(first_point.longitude, second_point.longitude)
        east  = max(first_point.longitude, second_point.longitude)
        south = min(first_point.latitude, second_point.latitude)
        north = max(first_point.latitude, second_point.latitude)
        """
        west = min(self.first_point.longitude, self.second_point.longitude)
        east = max(self.first_point.longitude, self.second_point.longitude)
        south = min(self.first_point.latitude, self.second_point.latitude)
        north = max(self.first_point.latitude, self.second_point.latitude)
        return (west, south, east, north)


@dataclass
class StartCommandPayload:
    area: AreaPayload
    transports: List[str] = field(default_factory=lambda: ["road"])


@dataclass
class CancelCommandPayload:
    pass


@dataclass
class StatusEventPayload:
    status: str  # "running" или "canceled"


@dataclass
class NodePayload:
    id: str
    position: List[float]  # [долгота, широта]
    attributes: Optional[Dict[str, Any]] = None


@dataclass
class EdgePayload:
    id: str
    source: str
    target: str
    geometry: Optional[List[List[float]]] = None  # [[lon, lat], ...]
    attributes: Optional[Dict[str, Any]] = None


@dataclass
class GraphPayload:
    nodes: List[NodePayload] = field(default_factory=list)
    edges: List[EdgePayload] = field(default_factory=list)


@dataclass
class MetricItem:
    name: str
    value: float


@dataclass
class ErrorPayload:
    code: str
    message: str


@dataclass
class ResultEventPayload:
    status: str  # "completed" или "failed"
    graph: Optional[GraphPayload] = None
    metrics: List[MetricItem] = field(default_factory=list)
    error: Optional[ErrorPayload] = None


@dataclass
class KafkaEnvelope:
    """
    Базовая оболочка сообщения в Kafka в соответствии с п. 3 контракта.
    """
    message_id: str
    job_id: str
    type: str
    payload: Dict[str, Any]

    @classmethod
    def create(cls, job_id: str, msg_type: str, payload: Dict[str, Any], message_id: Optional[str] = None) -> "KafkaEnvelope":
        return cls(
            message_id=message_id or str(uuid.uuid4()),
            job_id=job_id,
            type=msg_type,
            payload=payload,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "job_id": self.job_id,
            "type": self.type,
            "payload": self.payload,
        }
