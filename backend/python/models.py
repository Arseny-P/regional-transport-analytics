from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class TransportMode(str, Enum):
    ROAD = "road"
    RAIL = "rail"
    SEA = "sea"


class RouteStatus(str, Enum):
    FOUND = "found"
    NOT_FOUND_IN_DATA = "not_found_in_data"
    NOT_CHECKED = "not_checked"


class VerificationStatus(str, Enum):
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    EXCLUDED = "excluded"


class TerritoryValidationError(ValueError):
    """Ошибка валидации географических координат или границ исследуемой территории."""
    pass


class FacilityValidationError(ValueError):
    """Ошибка валидации данных логистического объекта."""
    pass


@dataclass
class TerritoryBounds:
    """
    Географические границы исследуемой территории (Bounding Box).
    Координаты задаются в градусах WGS84 (EPSG:4326).
    """
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    def validate(self, max_lat_span: float = 2.0, max_lon_span: float = 2.0) -> None:
        """
        Проверяет корректность диапазонов координат, логику min < max и лимиты площади.
        """
        if not (-90.0 <= self.min_lat <= 90.0 and -90.0 <= self.max_lat <= 90.0):
            raise TerritoryValidationError(
                f"Широта (lat) должна быть в диапазоне [-90, 90]. Получено: min_lat={self.min_lat}, max_lat={self.max_lat}"
            )
        if not (-180.0 <= self.min_lon <= 180.0 and -180.0 <= self.max_lon <= 180.0):
            raise TerritoryValidationError(
                f"Долгота (lon) должна быть в диапазоне [-180, 180]. Получено: min_lon={self.min_lon}, max_lon={self.max_lon}"
            )
        if self.min_lat >= self.max_lat:
            raise TerritoryValidationError(
                f"min_lat ({self.min_lat}) должен быть строго меньше max_lat ({self.max_lat})."
            )
        if self.min_lon >= self.max_lon:
            raise TerritoryValidationError(
                f"min_lon ({self.min_lon}) должен быть строго меньше max_lon ({self.max_lon})."
            )

        lat_span = self.max_lat - self.min_lat
        lon_span = self.max_lon - self.min_lon
        if lat_span > max_lat_span or lon_span > max_lon_span:
            raise TerritoryValidationError(
                f"Размер исследуемой территории превышает допустимый лимит: "
                f"delta_lat={lat_span:.3f}° (макс {max_lat_span}°), delta_lon={lon_span:.3f}° (макс {max_lon_span}°). "
                f"Пожалуйста, сузьте границы bbox для предотвращения перегрузки памяти и Overpass API."
            )

    def to_osmnx_bbox(self) -> tuple[float, float, float, float]:
        """
        Возвращает кортеж в формате OSMnx 2.x: (left, bottom, right, top) -> (min_lon, min_lat, max_lon, max_lat).
        """
        return (self.min_lon, self.min_lat, self.max_lon, self.max_lat)

    def contains(self, lat: float, lon: float) -> bool:
        """
        Проверяет, попадает ли точка (lat, lon) внутрь границ территории.
        """
        return self.min_lat <= lat <= self.max_lat and self.min_lon <= lon <= self.max_lon

    def cache_key(self) -> str:
        """
        Формирует детерминированный строковый ключ для кэширования файлов.
        """
        return f"bbox_{self.min_lat:.4f}_{self.min_lon:.4f}_{self.max_lat:.4f}_{self.max_lon:.4f}"

    def to_dict(self) -> Dict[str, float]:
        return {
            "min_lat": self.min_lat,
            "min_lon": self.min_lon,
            "max_lat": self.max_lat,
            "max_lon": self.max_lon,
        }


@dataclass
class LogisticsNode:
    """
    Вершина логистического графа — самостоятельный объект транспортно-логистической сети.
    Соответствует спецификации PM/Data Science.
    """
    id: str
    name: str
    object_type: str
    latitude: float
    longitude: float
    region_ids: List[str] = field(default_factory=lambda: ["ru-spb"])
    source_osm_ids: List[str] = field(default_factory=list)
    verification_status: str = VerificationStatus.CANDIDATE.value
    transport_modes: List[str] = field(default_factory=lambda: [TransportMode.ROAD.value])
    
    nearest_osm_node: Optional[int] = None
    osm_node_lat: Optional[float] = None
    osm_node_lon: Optional[float] = None
    snap_distance_m: Optional[float] = None
    access_nodes: List[int] = field(default_factory=list)  # Пул кандидатов точек подключения (въезды/выезды)

    def __getitem__(self, key: str) -> Any:
        if key == "lat":
            return self.latitude
        if key == "lon":
            return self.longitude
        if key == "type":
            return self.object_type
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "object_type": self.object_type,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "region_ids": self.region_ids,
            "source_osm_ids": self.source_osm_ids,
            "verification_status": self.verification_status,
            "transport_modes": self.transport_modes,
            "nearest_osm_node": self.nearest_osm_node,
            "osm_node_lat": self.osm_node_lat,
            "osm_node_lon": self.osm_node_lon,
            "snap_distance_m": self.snap_distance_m,
            "access_nodes": self.access_nodes,
        }


@dataclass
class LogisticsEdge:
    """
    Ребро логистического MultiGraph.
    Одно логическое ребро между парой объектов на каждый вид транспорта,
    содержащее характеристики обоих направлений (A → B и B → A).
    """
    node_a: str
    node_b: str
    node_a_name: str
    node_b_name: str
    transport_mode: str = TransportMode.ROAD.value
    
    # Направление A -> B
    distance_ab_m: Optional[float] = None
    total_distance_ab_m: Optional[float] = None
    snap_origin_ab_m: Optional[float] = None
    snap_dest_ab_m: Optional[float] = None
    duration_ab_sec: Optional[float] = None
    route_status_ab: str = RouteStatus.NOT_CHECKED.value
    osm_nodes_count_ab: int = 0
    path_osm_nodes_ab: List[int] = field(default_factory=list)
    geometry_ab_wkt: Optional[str] = None
    
    # Направление B -> A
    distance_ba_m: Optional[float] = None
    total_distance_ba_m: Optional[float] = None
    snap_origin_ba_m: Optional[float] = None
    snap_dest_ba_m: Optional[float] = None
    duration_ba_sec: Optional[float] = None
    route_status_ba: str = RouteStatus.NOT_CHECKED.value
    osm_nodes_count_ba: int = 0
    path_osm_nodes_ba: List[int] = field(default_factory=list)
    geometry_ba_wkt: Optional[str] = None
    
    connection_status: str = "candidate"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_a": self.node_a,
            "node_b": self.node_b,
            "node_a_name": self.node_a_name,
            "node_b_name": self.node_b_name,
            "transport_mode": self.transport_mode,
            "distance_ab_m": self.distance_ab_m,
            "total_distance_ab_m": self.total_distance_ab_m,
            "snap_origin_ab_m": self.snap_origin_ab_m,
            "snap_dest_ab_m": self.snap_dest_ab_m,
            "duration_ab_sec": self.duration_ab_sec,
            "route_status_ab": self.route_status_ab,
            "osm_nodes_count_ab": self.osm_nodes_count_ab,
            "geometry_ab_wkt": self.geometry_ab_wkt,
            "distance_ba_m": self.distance_ba_m,
            "total_distance_ba_m": self.total_distance_ba_m,
            "snap_origin_ba_m": self.snap_origin_ba_m,
            "snap_dest_ba_m": self.snap_dest_ba_m,
            "duration_ba_sec": self.duration_ba_sec,
            "route_status_ba": self.route_status_ba,
            "osm_nodes_count_ba": self.osm_nodes_count_ba,
            "geometry_ba_wkt": self.geometry_ba_wkt,
            "connection_status": self.connection_status,
        }

