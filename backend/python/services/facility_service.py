import os
import json
from typing import List, Dict, Any, Optional
import networkx as nx
import osmnx as ox
import pandas as pd
from models import LogisticsNode, VerificationStatus, TransportMode, TerritoryBounds, FacilityValidationError
import geopandas as gpd


class FacilityService:
    """
    Сервис управления логистическими объектами (хабы, склады, порты):
    загрузка, фильтрация, умный поиск в OSM и пространственная привязка (snapping) к дорожной сети.
    """

    EXCLUDE_KEYWORDS = [
        "котельная", "тэц", "трансформатор", "подстанция", "гараж", 
        "кнс", "насосная", "гск", "свалка", "шиномонтаж", "автомойка"
    ]

    DEFAULT_OSM_TAGS = {
        "landuse": ["industrial", "port", "depot", "logistics"],
        "building": ["warehouse", "industrial"],
        "harbour": True,
        "amenity": ["post_office"],
        "industrial": ["warehouse", "port", "depot", "logistics"],
    }

    def __init__(self, storage_dir: str = "data"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)

    def parse_and_validate_facilities(
        self,
        facilities_data: List[Dict[str, Any]],
        territory_bounds: Optional[TerritoryBounds] = None,
        filter_outside: bool = False,
    ) -> List[LogisticsNode]:
        """
        Валидирует и преобразует произвольный пользовательский набор объектов в список LogisticsNode.
        Проверяет наличие координат, корректность диапазонов, уникальность ID и границы территории.
        """
        if not isinstance(facilities_data, list):
            raise FacilityValidationError("Набор данных логистических объектов должен быть списком (list).")

        if not facilities_data:
            raise FacilityValidationError("Передан пустой список логистических объектов.")

        nodes: List[LogisticsNode] = []
        seen_ids = set()

        for idx, item in enumerate(facilities_data, start=1):
            if not isinstance(item, dict):
                raise FacilityValidationError(f"Элемент #{idx} должен быть словарем (dict), получено: {type(item).__name__}")

            raw_id = item.get("id")
            node_id = str(raw_id).strip() if raw_id is not None and str(raw_id).strip() else f"node_{idx}"
            if node_id in seen_ids:
                node_id = f"{node_id}_{idx}"
            seen_ids.add(node_id)

            name = str(item.get("name") or f"Объект #{idx}").strip()
            obj_type = str(item.get("type") or item.get("object_type") or "facility").strip()

            lat_val = item.get("lat") if "lat" in item else item.get("latitude")
            lon_val = item.get("lon") if "lon" in item else item.get("longitude")

            if lat_val is None or lon_val is None:
                raise FacilityValidationError(f"Объект '{name}' (ID: {node_id}) не содержит обязательных координат 'lat' / 'lon'.")

            try:
                lat = float(lat_val)
                lon = float(lon_val)
            except (ValueError, TypeError):
                raise FacilityValidationError(f"Координаты объекта '{name}' (ID: {node_id}) должны быть числами. Получено: lat={lat_val}, lon={lon_val}")

            if not (-90.0 <= lat <= 90.0):
                raise FacilityValidationError(f"Широта объекта '{name}' ({lat}) вне диапазона [-90, 90].")
            if not (-180.0 <= lon <= 180.0):
                raise FacilityValidationError(f"Долгота объекта '{name}' ({lon}) вне диапазона [-180, 180].")

            if territory_bounds is not None and not territory_bounds.contains(lat, lon):
                warning_msg = f"[!] Внимание: объект '{name}' ({lat:.4f}, {lon:.4f}) находится за пределами территории {territory_bounds.to_dict()}."
                if filter_outside:
                    print(f"{warning_msg} Объект отфильтрован.")
                    continue
                else:
                    print(warning_msg)

            node = LogisticsNode(
                id=node_id,
                name=name,
                object_type=obj_type,
                latitude=round(lat, 6),
                longitude=round(lon, 6),
                region_ids=item.get("region_ids", ["custom-region"]),
                source_osm_ids=item.get("source_osm_ids", []),
                verification_status=item.get("verification_status", VerificationStatus.VERIFIED.value),
                transport_modes=item.get("transport_modes", [TransportMode.ROAD.value]),
            )
            nodes.append(node)

        if not nodes:
            raise FacilityValidationError("После валидации и фильтрации не осталось ни одного валидного объекта.")

        return nodes

    def load_from_json(self, filepath: str, territory_bounds: Optional[TerritoryBounds] = None) -> List[LogisticsNode]:
        """
        Загружает тестовый или пользовательский набор логистических объектов из JSON-файла с валидацией.
        """
        if not os.path.isabs(filepath):
            filepath = os.path.join(self.storage_dir, filepath)

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Файл логистических объектов не найден: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            raw_data: List[Dict[str, Any]] = json.load(f)

        nodes = self.parse_and_validate_facilities(raw_data, territory_bounds=territory_bounds)
        print(f"[+] Загружено и валидировано {len(nodes)} логистических объектов из файла: {filepath}")
        return nodes

    def _extract_nodes_from_gdf(
        self,
        gdf: Any,
        limit: int = 15,
        region_id: str = "ru-spb",
    ) -> List[LogisticsNode]:
        """
        Внутренний метод извлечения и фильтрации логистических объектов из GeoDataFrame OSM.
        """
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
                    transport_modes=[TransportMode.ROAD.value],
                )
            )

            if len(nodes) >= limit:
                break

        print(f"[+] Из OSM отфильтровано и отобрано {len(nodes)} логистических объектов-кандидатов.")
        return nodes

    def fetch_from_osm_bbox(
        self,
        bbox: TerritoryBounds,
        tags: Optional[Dict[str, Any]] = None,
        limit: int = 15,
        region_id: str = "custom",
    ) -> List[LogisticsNode]:
        """
        Автоматически находит логистические/промышленные объекты в OSM внутри заданного BBox.
        """
        bbox.validate()
        query_tags = tags or self.DEFAULT_OSM_TAGS

        print(f"[*] Поиск логистических объектов в OSM для BBox: "
              f"lat=[{bbox.min_lat}, {bbox.max_lat}], lon=[{bbox.min_lon}, {bbox.max_lon}]...")
        try:
            gdf = ox.features_from_bbox(bbox=bbox.to_osmnx_bbox(), tags=query_tags)
        except Exception as e:
            print(f"[-] Ошибка при запросе к OSM Overpass API по BBox: {e}")
            return []

        if gdf.empty:
            print("[-] Подходящих объектов в указанном BBox не найдено.")
            return []

        return self._extract_nodes_from_gdf(gdf=gdf, limit=limit, region_id=region_id)

    def fetch_from_osm(
        self, 
        place_name: str, 
        tags: Optional[Dict[str, Any]] = None,
        limit: int = 15,
        region_id: str = "ru-spb",
        which_result: Optional[int] = None
    ) -> List[LogisticsNode]:
        """
        Автоматически находит логистические/промышленные объекты в OSM по названию территории с умной фильтрацией.
        """
        query_tags = tags or self.DEFAULT_OSM_TAGS

        print(f"[*] Поиск логистических объектов в OSM для: '{place_name}'...")
        try:
            kwargs = {"tags": query_tags}
            if which_result is not None:
                kwargs["which_result"] = which_result
            gdf = ox.features_from_place(place_name, **kwargs)
        except Exception as e:
            print(f"[-] Ошибка при запросе к OSM Overpass API: {e}")
            return []

        if gdf.empty:
            print("[-] Подходящих объектов в указанной локации не найдено.")
            return []

        return self._extract_nodes_from_gdf(gdf=gdf, limit=limit, region_id=region_id)

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

        primary_node_ids = ox.nearest_nodes(road_graph, X=lons, Y=lats)

        snapped_nodes: List[LogisticsNode] = []
        for node, primary_id in zip(log_nodes, primary_node_ids):
            primary_id_native = int(primary_id)

            # Собираем пул кандидатов на подключение: первичный узел + его топологические соседи
            candidate_pool = {primary_id_native}
            
            # Добавляем соседей и предшественников (связанные улицы перекрестка)
            if primary_id_native in road_graph:
                for neighbor in road_graph.successors(primary_id_native):
                    candidate_pool.add(int(neighbor))
                for predecessor in road_graph.predecessors(primary_id_native):
                    candidate_pool.add(int(predecessor))

            # Считаем точные геодезические расстояния от объекта до каждого кандидата
            candidate_distances = []
            for cand_id in candidate_pool:
                if cand_id in road_graph.nodes:
                    cand_data = road_graph.nodes[cand_id]
                    c_lat = float(cand_data.get("y"))
                    c_lon = float(cand_data.get("x"))
                    d = ox.distance.great_circle(node.latitude, node.longitude, c_lat, c_lon)
                    candidate_distances.append((cand_id, d, c_lat, c_lon))

            # Сортируем по близости к объекту и берем до 5 лучших кандидатов
            candidate_distances.sort(key=lambda x: x[1])
            best_candidates = candidate_distances[:5]

            best_node_id, best_dist, best_lat, best_lon = best_candidates[0]

            node.nearest_osm_node = best_node_id
            node.osm_node_lat = best_lat
            node.osm_node_lon = best_lon
            node.snap_distance_m = round(float(best_dist), 1)
            node.access_nodes = [item[0] for item in best_candidates]

            snapped_nodes.append(node)
            warning_tag = " [!] ДАЛЕКО" if best_dist > 1000 else ""
            print(f"  [Snap] '{node.name}' -> {len(node.access_nodes)} точек подключения (осн. узел {best_node_id}, плечо: {node.snap_distance_m} м){warning_tag}")

        return snapped_nodes
