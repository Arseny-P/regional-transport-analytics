import os
from typing import Dict, Any, Optional
import networkx as nx
import osmnx as ox
import geopandas as gpd
from models import TerritoryBounds, TerritoryValidationError

# Настройки OSMnx по умолчанию
ox.settings.log_console = False
ox.settings.use_cache = True
ox.settings.requests_timeout = 180
# Зеркало Overpass для OSMnx 2.x
ox.settings.overpass_url = "https://overpass.kumi.systems/api"



class RoadNetworkService:
    """
    Сервис загрузки, обработки и экспорта базовой дорожной сети OpenStreetMap.
    """

    def __init__(self, storage_dir: str = "data"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)

    def fetch_and_build_from_bbox(
        self,
        bbox: TerritoryBounds,
        network_type: str = "drive",
        simplify: bool = True,
    ) -> nx.MultiDiGraph:
        """
        Загружает автомобильную дорожную сеть из OSM для заданного BBox (TerritoryBounds).
        Использует формат OSMnx 2.x (left, bottom, right, top) -> (min_lon, min_lat, max_lon, max_lat).
        """
        bbox.validate()
        print(f"[*] Загрузка данных дорожной сети OSM по BBox: "
              f"lat=[{bbox.min_lat}, {bbox.max_lat}], lon=[{bbox.min_lon}, {bbox.max_lon}]...")

        try:
            graph = ox.graph_from_bbox(
                bbox=bbox.to_osmnx_bbox(),
                network_type=network_type,
                simplify=simplify,
            )
        except Exception as e:
            raise RuntimeError(f"Ошибка загрузки дорожной сети OSM для указанного BBox: {e}") from e

        if len(graph.nodes) == 0:
            raise ValueError(f"Дорожная сеть для указанного BBox пуста. Проверьте координаты территории.")

        print(f"[+] Дорожная сеть построена по BBox: {len(graph.nodes)} вершин, {len(graph.edges)} ребер.")
        return graph

    def fetch_and_build(
        self, 
        place_name: str, 
        network_type: str = "drive", 
        simplify: bool = True,
        which_result: Optional[int] = None
    ) -> nx.MultiDiGraph:
        """
        Загружает дорожную сеть из OSM и строит топологически корректный граф дорог.
        """
        print(f"[*] Загрузка данных дорожной сети OSM для: '{place_name}'...")
        kwargs = {"network_type": network_type, "simplify": simplify}
        if which_result is not None:
            kwargs["which_result"] = which_result

        graph = ox.graph_from_place(place_name, **kwargs)
        print(f"[+] Дорожная сеть построена: {len(graph.nodes)} вершин, {len(graph.edges)} ребер.")
        return graph

    def save_graphml(self, graph: nx.MultiDiGraph, filename: str) -> str:
        """
        Сохраняет дорожный граф в формате GraphML на диск.
        """
        filepath = os.path.join(self.storage_dir, f"{filename}.graphml")
        ox.save_graphml(graph, filepath=filepath)
        print(f"[+] Дорожный граф сохранен в GraphML: {filepath}")
        return filepath

    def load_graphml(self, filename: str) -> nx.MultiDiGraph:
        """
        Загружает дорожный граф из файла GraphML без обращения к интернету.
        """
        filepath = os.path.join(self.storage_dir, f"{filename}.graphml")
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Файл дорожного графа не найден: {filepath}")

        graph = ox.load_graphml(filepath=filepath)
        print(f"[+] Дорожный граф загружен из файла: {len(graph.nodes)} узлов, {len(graph.edges)} ребер.")
        return graph

    def export_to_geojson(self, graph: nx.MultiDiGraph, filename: str) -> str:
        """
        Экспортирует дорожную сеть в формат GeoJSON для отображения дорожного слоя во фронтенде.
        """
        filepath = os.path.join(self.storage_dir, f"{filename}.geojson")
        _, edges_gdf = ox.graph_to_gdfs(graph)

        columns_to_keep = ["name", "length", "highway", "maxspeed", "geometry"]
        existing_columns = [col for col in columns_to_keep if col in edges_gdf.columns]
        edges_clean = edges_gdf[existing_columns].copy()

        for col in edges_clean.columns:
            if col != "geometry":
                edges_clean[col] = edges_clean[col].astype(str)

        edges_clean.to_file(filepath, driver="GeoJSON")
        print(f"[+] GeoJSON дорожного графа сохранен в: {filepath}")
        return filepath

    def get_summary(self, graph: nx.MultiDiGraph) -> Dict[str, Any]:
        """
        Возвращает базовую статистику дорожной сети.
        """
        return {
            "total_nodes": len(graph.nodes),
            "total_edges": len(graph.edges),
            "sample_nodes": list(graph.nodes(data=True))[:3],
            "sample_edges": list(graph.edges(data=True))[:3]
        }
