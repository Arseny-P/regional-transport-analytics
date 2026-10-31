from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum

from .errors import TerritoryValidationError, FacilityValidationError


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


class GraphRole(str, Enum):
    NODE_CANDIDATE = "node_candidate"
    NESTED_CANDIDATE = "nested_candidate"
    NOT_SELECTED = "not_selected"


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
    
    identification_basis: Dict[str, Any] = field(default_factory=dict)
    parent_site_id: Optional[str] = None
    graph_role: str = GraphRole.NODE_CANDIDATE.value

    nearest_osm_node: Optional[int] = None
    osm_node_lat: Optional[float] = None
    osm_node_lon: Optional[float] = None
    snap_distance_m: Optional[float] = None
    access_nodes: List[int] = field(default_factory=list)
    is_isolated: bool = False
    isolation_reason: Optional[str] = None

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
            "identification_basis": self.identification_basis,
            "parent_site_id": self.parent_site_id,
            "graph_role": self.graph_role,
            "nearest_osm_node": self.nearest_osm_node,
            "osm_node_lat": self.osm_node_lat,
            "osm_node_lon": self.osm_node_lon,
            "snap_distance_m": self.snap_distance_m,
            "access_nodes": self.access_nodes,
            "is_isolated": self.is_isolated,
            "isolation_reason": self.isolation_reason,
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
    road_geometry_ab_wkt: Optional[str] = None
    
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
    road_geometry_ba_wkt: Optional[str] = None
    
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
            "road_geometry_ab_wkt": self.road_geometry_ab_wkt,
            "distance_ba_m": self.distance_ba_m,
            "total_distance_ba_m": self.total_distance_ba_m,
            "snap_origin_ba_m": self.snap_origin_ba_m,
            "snap_dest_ba_m": self.snap_dest_ba_m,
            "duration_ba_sec": self.duration_ba_sec,
            "route_status_ba": self.route_status_ba,
            "osm_nodes_count_ba": self.osm_nodes_count_ba,
            "geometry_ba_wkt": self.geometry_ba_wkt,
            "road_geometry_ba_wkt": self.road_geometry_ba_wkt,
            "connection_status": self.connection_status,
        }


class TerritorySourceType(str, Enum):
    BBOX = "bbox"
    PLACE_NAME = "place_name"


class FacilitySourceType(str, Enum):
    USER_DEFINED = "user_defined"
    OSM = "osm"
    HYBRID = "hybrid"


class AnalysisStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    ERROR = "error"


@dataclass
class AnalysisRequest:
    """
    Входные параметры для запуска анализа территории.
    Используется в качестве контракта при вызове из Go-бэкенда.
    """
    territory_type: str = TerritorySourceType.BBOX.value
    bbox: Optional[TerritoryBounds] = None
    place_name: Optional[str] = None
    which_result: Optional[int] = None

    facility_source: str = FacilitySourceType.USER_DEFINED.value
    facilities: List[Dict[str, Any]] = field(default_factory=list)
    osm_facilities_limit: int = 100
    osm_tags: Optional[Dict[str, Any]] = None
    max_snap_distance_m: Optional[float] = None

    knn: Optional[int] = None
    output_dir: str = "data"
    output_alias: Optional[str] = None
    save_artifacts: bool = True
    include_geojson_payload: bool = True
    refetch: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnalysisRequest":
        bbox_data = data.get("bbox")
        bbox_obj = None
        if isinstance(bbox_data, dict):
            bbox_obj = TerritoryBounds(
                min_lat=float(bbox_data["min_lat"]),
                min_lon=float(bbox_data["min_lon"]),
                max_lat=float(bbox_data["max_lat"]),
                max_lon=float(bbox_data["max_lon"]),
            )
        elif isinstance(bbox_data, (list, tuple)) and len(bbox_data) == 4:
            bbox_obj = TerritoryBounds(
                min_lat=float(bbox_data[0]),
                min_lon=float(bbox_data[1]),
                max_lat=float(bbox_data[2]),
                max_lon=float(bbox_data[3]),
            )

        return cls(
            territory_type=str(data.get("territory_type", TerritorySourceType.BBOX.value)),
            bbox=bbox_obj,
            place_name=data.get("place_name"),
            which_result=data.get("which_result"),
            facility_source=str(data.get("facility_source", FacilitySourceType.USER_DEFINED.value)),
            facilities=data.get("facilities", []),
            osm_facilities_limit=int(data.get("osm_facilities_limit", 100)),
            osm_tags=data.get("osm_tags"),
            max_snap_distance_m=float(data["max_snap_distance_m"]) if data.get("max_snap_distance_m") is not None else None,
            knn=int(data["knn"]) if data.get("knn") is not None else None,
            output_dir=str(data.get("output_dir", "data")),
            output_alias=data.get("output_alias"),
            save_artifacts=bool(data.get("save_artifacts", True)),
            include_geojson_payload=bool(data.get("include_geojson_payload", True)),
            refetch=bool(data.get("refetch", False)),
        )


@dataclass
class AnalysisResponse:
    """
    Структурированный результат выполнения анализа для передачи в Go-бэкенд.
    """
    status: str = AnalysisStatus.SUCCESS.value
    territory: Dict[str, Any] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, Optional[str]] = field(default_factory=dict)
    hubs: List[Dict[str, Any]] = field(default_factory=list)
    connections: List[Dict[str, Any]] = field(default_factory=list)
    geojson: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    graph_object: Optional[Any] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "territory": self.territory,
            "summary": self.summary,
            "artifacts": self.artifacts,
            "hubs": self.hubs,
            "connections": self.connections,
            "geojson": self.geojson,
            "warnings": self.warnings,
            "error_message": self.error_message,
        }
