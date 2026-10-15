import os
import json
from typing import List, Dict, Any, Optional
import networkx as nx
import osmnx as ox


class FacilityService:
    """
    Сервис управления логистическими объектами (хабы, склады, порты):
    загрузка, поиск в OSM и пространственная привязка (snapping) к дорожной сети.
    """

    def __init__(self, storage_dir: str = "data"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)

    def load_from_json(self, filepath: str) -> List[Dict[str, Any]]:
        """
        Загружает проверенный тестовый набор логистических объектов из JSON-файла.
        """
        if not os.path.isabs(filepath):
            filepath = os.path.join(self.storage_dir, filepath)

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Файл логистических объектов не найден: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            points: List[Dict[str, Any]] = json.load(f)

        print(f"[+] Загружено {len(points)} логистических объектов из файла: {filepath}")
        return points

    def fetch_from_osm(
        self, 
        place_name: str, 
        tags: Optional[Dict[str, Any]] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Автоматически находит логистические/промышленные объекты в OSM по тегам.
        Извлекает центроиды геометрий и возвращает список объектов.
        """
        if tags is None:
            tags = {
                "landuse": ["industrial", "port"],
                "building": ["warehouse", "industrial"],
                "harbour": True,
                "amenity": ["post_office"]
            }

        print(f"[*] Поиск логистических объектов в OSM для: '{place_name}'...")
        try:
            gdf = ox.features_from_place(place_name, tags)
        except Exception as e:
            print(f"[-] Ошибка при запросе к OSM Overpass API: {e}")
            return []

        if gdf.empty:
            print("[-] Подходящих объектов в указанной локации не найдено.")
            return []

        named_gdf = gdf[gdf["name"].notna()].copy() if "name" in gdf.columns else gdf.copy()
        if named_gdf.empty:
            named_gdf = gdf.copy()

        import pandas as pd

        points: List[Dict[str, Any]] = []
        for idx, row in named_gdf.head(limit).iterrows():
            centroid = row.geometry.centroid
            name = str(row.get("name") or f"Логистический объект #{len(points)+1}")
            
            # Извлекаем первый валидный тег типа
            obj_type = "facility"
            for tag in ["amenity", "building", "landuse", "harbour", "industrial"]:
                val = row.get(tag)
                if pd.notna(val) and val:
                    obj_type = str(val)
                    break
            
            points.append({
                "id": f"osm_poi_{len(points)+1}",
                "name": name,
                "lat": round(centroid.y, 6),
                "lon": round(centroid.x, 6),
                "type": obj_type
            })

        print(f"[+] Из OSM получено {len(points)} объектов.")
        return points

    def snap_to_road_network(
        self, 
        road_graph: nx.MultiDiGraph, 
        points: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Привязывает (snapping) координаты логистических объектов к ближайшим узлам дорожной сети OSM.
        Добавляет поля 'nearest_osm_node', 'osm_node_lat', 'osm_node_lon'.
        """
        if not points:
            return []

        lons = [p["lon"] for p in points]
        lats = [p["lat"] for p in points]

        nearest_node_ids = ox.nearest_nodes(road_graph, X=lons, Y=lats)

        snapped_points: List[Dict[str, Any]] = []
        for point, node_id in zip(points, nearest_node_ids):
            point_copy = dict(point)
            node_id_native = int(node_id)
            node_data = road_graph.nodes[node_id_native]
            point_copy["nearest_osm_node"] = node_id_native
            point_copy["osm_node_lat"] = float(node_data.get("y"))
            point_copy["osm_node_lon"] = float(node_data.get("x"))
            snapped_points.append(point_copy)
            print(f"  [Snap] '{point_copy['name']}' -> узел OSM {node_id_native}")

        return snapped_points
