"""
Фасадный сервис GraphService для обратной совместимости.
Делегирует ответственность специализированным сервисам из пакета `services`.
"""

from typing import List, Dict, Any, Optional
import networkx as nx
from services import RoadNetworkService, FacilityService, LogisticsGraphService


class GraphService:
    """
    Фасад (Facade), объединяющий работу с дорожной сетью, объектами и логистическим графом.
    """

    def __init__(self, storage_dir: str = "data"):
        self.storage_dir = storage_dir
        self.road_service = RoadNetworkService(storage_dir=storage_dir)
        self.facility_service = FacilityService(storage_dir=storage_dir)
        self.logistics_service = LogisticsGraphService(storage_dir=storage_dir)

    # --- Дорожная сеть ---
    def fetch_and_build_graph(self, place_name: str) -> nx.MultiDiGraph:
        return self.road_service.fetch_and_build(place_name=place_name)

    def save_graph_for_ml(self, graph: nx.MultiDiGraph, filename: str) -> str:
        return self.road_service.save_graphml(graph=graph, filename=filename)

    def load_graph_from_file(self, filename: str) -> nx.MultiDiGraph:
        return self.road_service.load_graphml(filename=filename)

    def export_to_geojson_for_frontend(self, graph: nx.MultiDiGraph, filename: str) -> str:
        return self.road_service.export_to_geojson(graph=graph, filename=filename)

    def get_graph_summary(self, graph: nx.MultiDiGraph) -> Dict[str, Any]:
        return self.road_service.get_summary(graph=graph)

    # --- Логистические объекты ---
    def load_logistics_points_from_file(self, filepath: str) -> List[Dict[str, Any]]:
        return self.facility_service.load_from_json(filepath=filepath)

    def fetch_logistics_points_from_osm(
        self, 
        place_name: str, 
        tags: Optional[Dict[str, Any]] = None, 
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        return self.facility_service.fetch_from_osm(place_name=place_name, tags=tags, limit=limit)

    def snap_points_to_graph(
        self, 
        graph: nx.MultiDiGraph, 
        points: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        return self.facility_service.snap_to_road_network(road_graph=graph, points=points)

    # --- Логистический граф и маршрутизация ---
    def build_logistics_graph(
        self, 
        road_graph: nx.MultiDiGraph, 
        snapped_points: List[Dict[str, Any]]
    ) -> nx.DiGraph:
        return self.logistics_service.build_logistics_graph(road_graph=road_graph, snapped_points=snapped_points)

    def save_logistics_graph(self, log_graph: nx.DiGraph, filename: str) -> str:
        return self.logistics_service.save_graphml(log_graph=log_graph, filename=filename)

    def load_logistics_graph(self, filename: str) -> nx.DiGraph:
        return self.logistics_service.load_graphml(filename=filename)

    def export_logistics_graph_to_geojson(self, log_graph: nx.DiGraph, filename: str) -> str:
        return self.logistics_service.export_to_geojson(log_graph=log_graph, filename=filename)

    def get_logistics_graph_summary(self, log_graph: nx.DiGraph) -> Dict[str, Any]:
        return self.logistics_service.get_summary(log_graph=log_graph)