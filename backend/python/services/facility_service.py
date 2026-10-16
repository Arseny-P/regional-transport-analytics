import os
import json
from typing import List, Dict, Any, Optional
import networkx as nx
import osmnx as ox
import pandas as pd
from models import LogisticsNode, VerificationStatus, TransportMode


class FacilityService:
    """
    Сервис управления логистическими объектами (хабы, склады, порты):
    загрузка, фильтрация, умный поиск в OSM и пространственная привязка (snapping) к дорожной сети.
    """

    EXCLUDE_KEYWORDS = [
        "котельная", "тэц", "трансформатор", "подстанция", "гараж", 
        "кнс", "насосная", "гск", "свалка", "шиномонтаж", "автомойка"
    ]

    def __init__(self, storage_dir: str = "data"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)

    def load_from_json(self, filepath: str) -> List[LogisticsNode]:
        """
        Загружает тестовый набор логистических объектов из JSON-файла
        и возвращает типизированный список LogisticsNode.
        """
        if not os.path.isabs(filepath):
            filepath = os.path.join(self.storage_dir, filepath)

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Файл логистических объектов не найден: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            raw_data: List[Dict[str, Any]] = json.load(f)

        nodes: List[LogisticsNode] = []
        for item in raw_data:
            node = LogisticsNode(
                id=str(item["id"]),
                name=str(item["name"]),
                object_type=str(item.get("type") or item.get("object_type", "facility")),
                latitude=float(item.get("lat") or item.get("latitude")),
                longitude=float(item.get("lon") or item.get("longitude")),
                region_ids=item.get("region_ids", ["ru-spb"]),
                source_osm_ids=item.get("source_osm_ids", []),
                verification_status=item.get("verification_status", VerificationStatus.VERIFIED.value),
                transport_modes=item.get("transport_modes", [TransportMode.ROAD.value]),
            )
            nodes.append(node)

        print(f"[+] Загружено {len(nodes)} логистических объектов из файла: {filepath}")
        return nodes

    def fetch_from_osm(
        self, 
        place_name: str, 
        tags: Optional[Dict[str, Any]] = None,
        limit: int = 15,
        region_id: str = "ru-spb"
    ) -> List[LogisticsNode]:
        """
        Автоматически находит логистические/промышленные объекты в OSM с умной фильтрацией.
        """
        if tags is None:
            tags = {
                "landuse": ["industrial", "port", "depot", "logistics"],
                "building": ["warehouse", "industrial"],
                "harbour": True,
                "amenity": ["post_office"],
                "industrial": ["warehouse", "port", "depot", "logistics"]
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

        nodes: List[LogisticsNode] = []
        for idx, row in named_gdf.iterrows():
            name = str(row.get("name") or "").strip()
            name_lower = name.lower()

            if any(kw in name_lower for kw in self.EXCLUDE_KEYWORDS):
                continue

            geom = row.geometry
            if geom.geom_type in ["Polygon", "MultiPolygon"]:
                point = geom.representative_point()
            else:
                point = geom.centroid

            obj_type = "facility"
            for tag in ["amenity", "building", "landuse", "harbour", "industrial"]:
                val = row.get(tag)
                if pd.notna(val) and val:
                    obj_type = str(val)
                    break

            osm_id_str = f"osm:{row.name}" if hasattr(row, "name") else f"osm_poi_{len(nodes) + 1}"

            nodes.append(
                LogisticsNode(
                    id=f"hub_{len(nodes) + 1}_{obj_type}",
                    name=name if name else f"Логистический комплекс #{len(nodes) + 1}",
                    object_type=obj_type,
                    latitude=round(float(point.y), 6),
                    longitude=round(float(point.x), 6),
                    region_ids=[region_id],
                    source_osm_ids=[osm_id_str],
                    verification_status=VerificationStatus.CANDIDATE.value,
                    transport_modes=[TransportMode.ROAD.value]
                )
            )

            if len(nodes) >= limit:
                break

        print(f"[+] Из OSM отфильтровано и отобрано {len(nodes)} логистических объектов-кандидатов.")
        return nodes

    def snap_to_road_network(
        self, 
        road_graph: nx.MultiDiGraph, 
        nodes: List[Any]
    ) -> List[LogisticsNode]:
        """
        Привязывает объекты к ближайшим узлам дорожной сети OSM.
        Вычисляет точное геодезическое расстояние привязки (snap_distance_m).
        """
        if not nodes:
            return []
        if "crs" not in road_graph.graph:
            road_graph.graph["crs"] = "epsg:4326"

        log_nodes: List[LogisticsNode] = []
        for n in nodes:
            if isinstance(n, LogisticsNode):
                log_nodes.append(n)
            elif isinstance(n, dict):
                log_nodes.append(
                    LogisticsNode(
                        id=str(n["id"]),
                        name=str(n["name"]),
                        object_type=str(n.get("type") or n.get("object_type", "facility")),
                        latitude=float(n.get("lat") or n.get("latitude")),
                        longitude=float(n.get("lon") or n.get("longitude")),
                        region_ids=n.get("region_ids", ["ru-spb"]),
                        source_osm_ids=n.get("source_osm_ids", []),
                        verification_status=n.get("verification_status", VerificationStatus.CANDIDATE.value),
                        transport_modes=n.get("transport_modes", [TransportMode.ROAD.value])
                    )
                )

        lons = [n.longitude for n in log_nodes]
        lats = [n.latitude for n in log_nodes]

        nearest_node_ids = ox.nearest_nodes(road_graph, X=lons, Y=lats)

        snapped_nodes: List[LogisticsNode] = []
        for node, osm_id in zip(log_nodes, nearest_node_ids):
            node_id_native = int(osm_id)
            osm_node_data = road_graph.nodes[node_id_native]
            osm_lat = float(osm_node_data.get("y"))
            osm_lon = float(osm_node_data.get("x"))

            dist_m = ox.distance.great_circle(
                lat1=node.latitude, 
                lon1=node.longitude, 
                lat2=osm_lat, 
                lon2=osm_lon
            )

            node.nearest_osm_node = node_id_native
            node.osm_node_lat = osm_lat
            node.osm_node_lon = osm_lon
            node.snap_distance_m = round(float(dist_m), 1)

            snapped_nodes.append(node)
            warning_tag = " [!] ДАЛЕКО" if dist_m > 1000 else ""
            print(f"  [Snap] '{node.name}' -> узел OSM {node_id_native} (плечо привязки: {node.snap_distance_m} м){warning_tag}")

        return snapped_nodes
