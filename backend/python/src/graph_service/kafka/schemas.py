import math
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


class ErrorCode(str, Enum):
    INVALID_PARAMETERS = "invalid_parameters"
    UNSUPPORTED_TRANSPORT = "unsupported_transport"
    OSM_UNAVAILABLE = "osm_unavailable"
    GRAPH_BUILD_FAILED = "graph_build_failed"
    METRICS_CALCULATION_FAILED = "metrics_calculation_failed"
    INTERNAL_ERROR = "internal_error"


SUPPORTED_TRANSPORTS = {"road"}


@dataclass
class MapPoint:
    latitude: float
    longitude: float

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MapPoint":
        if "latitude" not in data or "longitude" not in data:
            raise ValueError("Точка должна содержать поля 'latitude' и 'longitude'")
        lat = float(data["latitude"])
        lon = float(data["longitude"])
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"Широта {lat} выходит за диапазон [-90, 90]")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"Долгота {lon} выходит за диапазон [-180, 180]")
        return cls(latitude=lat, longitude=lon)

    def to_dict(self) -> Dict[str, Any]:
        return {"latitude": self.latitude, "longitude": self.longitude}


@dataclass
class AreaPayload:
    first_point: MapPoint
    second_point: MapPoint

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AreaPayload":
        if "first_point" not in data or "second_point" not in data:
            raise ValueError("Area должна содержать 'first_point' и 'second_point'")
        p1 = MapPoint.from_dict(data["first_point"])
        p2 = MapPoint.from_dict(data["second_point"])

        if p1.latitude == p2.latitude:
            raise ValueError("Широты противоположных углов должны различаться (нулевая площадь)")
        if p1.longitude == p2.longitude:
            raise ValueError("Долготы противоположных углов должны различаться (нулевая площадь)")

        return cls(first_point=p1, second_point=p2)

    def to_bounds(self) -> tuple[float, float, float, float]:
        """
        Возвращает кортеж (west, south, east, north) в соответствии с п. 4 контракта:
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "first_point": self.first_point.to_dict(),
            "second_point": self.second_point.to_dict(),
        }


@dataclass
class StartCommandPayload:
    area: AreaPayload
    transports: List[str] = field(default_factory=lambda: ["road"])

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StartCommandPayload":
        if not isinstance(data, dict):
            raise ValueError("Payload команды START должен быть объектом JSON")
        if "area" not in data:
            raise ValueError("Поле 'area' обязательно в payload команды START")

        area = AreaPayload.from_dict(data["area"])
        transports = data.get("transports", ["road"])
        if not isinstance(transports, list) or len(transports) == 0:
            raise ValueError("Поле 'transports' должно быть непустым списком")

        return cls(area=area, transports=transports)

    def validate_transports(self) -> None:
        """
        Проверяет, поддерживаются ли все указанные виды транспорта.
        В Sprint 3 поддерживается исключительно 'road'.
        """
        unsupported = set(self.transports) - SUPPORTED_TRANSPORTS
        if unsupported:
            raise ValueError(
                f"Неподдерживаемые виды транспорта: {sorted(list(unsupported))}. "
                f"Поддерживается только: {sorted(list(SUPPORTED_TRANSPORTS))}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "area": self.area.to_dict(),
            "transports": list(self.transports),
        }


@dataclass
class CancelCommandPayload:
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]] = None) -> "CancelCommandPayload":
        return cls()

    def to_dict(self) -> Dict[str, Any]:
        return {}


@dataclass
class StatusEventPayload:
    status: str  # "running" или "canceled"

    def to_dict(self) -> Dict[str, Any]:
        return {"status": self.status}


@dataclass
class NodePayload:
    id: str
    position: List[float]  # строго [долгота, широта]
    attributes: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "id": str(self.id),
            "position": [float(self.position[0]), float(self.position[1])],
        }
        if self.attributes:
            res["attributes"] = self.attributes
        return res


@dataclass
class EdgePayload:
    id: str
    source: str
    target: str
    geometry: Optional[List[List[float]]] = None  # [[lon, lat], ...]
    attributes: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "id": str(self.id),
            "source": str(self.source),
            "target": str(self.target),
        }
        if self.geometry is not None:
            res["geometry"] = [
                [float(pt[0]), float(pt[1])] for pt in self.geometry
            ]
        if self.attributes:
            res["attributes"] = self.attributes
        return res


@dataclass
class GraphPayload:
    nodes: List[NodePayload] = field(default_factory=list)
    edges: List[EdgePayload] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }


@dataclass
class MetricItem:
    name: str
    value: float

    def to_dict(self) -> Dict[str, Any]:
        # Защита от NaN / Infinity по контракту
        val = float(self.value)
        if not math.isfinite(val):
            raise ValueError(f"Метрика '{self.name}' содержит недопустимое нечисловое значение: {self.value}")
        return {"name": self.name, "value": round(val, 4)}


@dataclass
class ErrorPayload:
    code: str
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
        }


@dataclass
class ResultEventPayload:
    status: str  # "completed" или "failed"
    graph: Optional[GraphPayload] = None
    metrics: List[MetricItem] = field(default_factory=list)
    error: Optional[ErrorPayload] = None

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "status": self.status,
            "graph": self.graph.to_dict() if self.graph is not None else None,
            "metrics": [m.to_dict() for m in self.metrics],
        }
        if self.error:
            res["error"] = self.error.to_dict()
        return res


@dataclass
class KafkaEnvelope:
    """
    Базовая оболочка сообщения в Kafka в соответствии с п. 3 контракта.
    Kafka key — строковый job_id.
    """
    message_id: str
    job_id: str
    type: str
    payload: Dict[str, Any]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KafkaEnvelope":
        if not isinstance(data, dict):
            raise ValueError("Сообщение Kafka должно быть объектом JSON")
        for req_field in ("message_id", "job_id", "type", "payload"):
            if req_field not in data:
                raise ValueError(f"В конверте Kafka отсутствует обязательное поле: '{req_field}'")
        return cls(
            message_id=str(data["message_id"]),
            job_id=str(data["job_id"]),
            type=str(data["type"]),
            payload=data["payload"] if isinstance(data["payload"], dict) else {},
        )

    @classmethod
    def create(
        cls,
        job_id: str,
        msg_type: str,
        payload: Dict[str, Any],
        message_id: Optional[str] = None,
    ) -> "KafkaEnvelope":
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
