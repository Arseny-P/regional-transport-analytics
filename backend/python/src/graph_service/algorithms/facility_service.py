import os
import json
from typing import List, Dict, Any, Optional
import networkx as nx
import osmnx as ox
import pandas as pd
from shapely.geometry import Point, LineString
from shapely.ops import substring
from graph_service.domain.models import (
    LogisticsNode,
    VerificationStatus,
    GraphRole,
    TransportMode,
    TerritoryBounds,
)
from graph_service.domain.errors import FacilityValidationError
import geopandas as gpd
from graph_service.http.osm_client import execute_with_overpass_fallback


class FacilityService:
    """
    Сервис управления логистическими объектами (хабы, склады, порты):
    загрузка, фильтрация, умный поиск в OSM и пространственная привязка (snapping) к дорожной сети.
    """

    EXCLUDE_KEYWORDS = [
        "котельная", "тэц", "трансформатор", "подстанция", "гараж", 
        "кнс", "насосная", "гск", "свалка", "шиномонтаж", "автомойка"
    ]

    EXCLUDE_DEPOT_TYPES = {
        "bus", "tram", "subway", "trolleybus", "passengers", "metro"
    }

    LOGISTICS_KEYWORDS = [
        "склад", "терминал", "логистическ", "распределительн", "рц", "грузов",
        "порт", "логистик", "warehouse", "terminal", "logistics", "freight", "cargo"
    ]

    DEFAULT_OSM_TAGS = {
        "landuse": ["industrial", "port", "depot", "logistics"],
        "building": ["warehouse", "industrial"],
        "harbour": True,
        "amenity": ["post_office"],
        "industrial": ["warehouse", "port", "depot", "logistics"],
        "railway": ["yard", "loading_ramp"],
        "port": ["cargo"],
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
                identification_basis=item.get("identification_basis", {"source": "user_input"}),
                parent_site_id=item.get("parent_site_id"),
                graph_role=item.get("graph_role", GraphRole.NODE_CANDIDATE.value),
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

    @staticmethod
    def _format_osm_id(idx_val: Any, row: Any = None) -> str:
        """
        Форматирует ID элемента в устойчивый вид согласно спецификации PM (п. 3.4):
        osm:way/12345, osm:relation/67890, osm:node/111.
        """
        if isinstance(idx_val, tuple) and len(idx_val) == 2:
            return f"osm:{idx_val[0]}/{idx_val[1]}"
        
        elem_type = None
        if hasattr(row, "get"):
            elem_type = row.get("element_type")
        elif hasattr(row, "element_type"):
            elem_type = getattr(row, "element_type")

        if elem_type and not str(idx_val).startswith(str(elem_type)):
            return f"osm:{elem_type}/{idx_val}"
        idx_str = str(idx_val)
        if idx_str.startswith("osm:"):
            return idx_str
        return f"osm:{idx_str}"

    def _extract_nodes_from_gdf(
        self,
        gdf: Any,
        limit: int = 15,
        region_id: str = "ru-spb",
    ) -> List[LogisticsNode]:
        """
        Извлекает, классифицирует и разделяет логистические объекты на здания и территории
        согласно пунктам 3.2 и 3.3 спецификации PM.
        """
        if gdf.empty:
            return []

        # 1. Первичная фильтрация и извлечение кандидатов (п. 3.2)
        candidates: List[Dict[str, Any]] = []

        for idx, row in gdf.iterrows():
            raw_name = row.get("name")
            if pd.isna(raw_name) or str(raw_name).strip().lower() in ("nan", "none", ""):
                name = ""
            else:
                name = str(raw_name).strip()
            name_lower = name.lower()

            # Исключаем паразитные нелогистические объекты (котельные, ТЭЦ, гаражи, свалки)
            if any(kw in name_lower for kw in self.EXCLUDE_KEYWORDS):
                continue

            # Фильтрация пассажирских депо
            depot_val = str(row.get("depot") or "").strip().lower()
            if depot_val in self.EXCLUDE_DEPOT_TYPES:
                continue

            # Фильтрация пассажирских ж/д станций (п. 3.2: railway=station не доказывает грузовую функцию)
            railway_val = str(row.get("railway") or "").strip().lower()
            if railway_val == "station":
                has_cargo = (
                    pd.notna(row.get("cargo"))
                    or (pd.notna(row.get("service")) and row.get("service") in ["spur", "siding"])
                    or any(kw in name_lower for kw in ["грузов", "товарн", "сортировочн", "cargo", "freight", "yard", "ramp"])
                )
                if not has_cargo:
                    continue

            # Проверка landuse=industrial (п. 3.1 & 3.2: сам по себе не подтверждает логистическую роль)
            is_generic_industrial = (
                row.get("landuse") == "industrial"
                and pd.isna(row.get("industrial"))
                and pd.isna(row.get("building"))
                and pd.isna(row.get("harbour"))
                and pd.isna(row.get("amenity"))
                and pd.isna(row.get("railway"))
                and pd.isna(row.get("port"))
            )
            matched_kw = next((kw for kw in self.LOGISTICS_KEYWORDS if kw in name_lower), None)

            # Если объект — общая безымянная промзона без признаков логистики, не делаем из нее узел
            if is_generic_industrial and not matched_kw:
                continue

            geom = row.geometry
            if geom.geom_type in ["Polygon", "MultiPolygon"]:
                point = geom.representative_point()
            else:
                point = geom.centroid

            # Определение типа объекта и основания классификации (п. 3.2)
            obj_type = "facility"
            primary_tag = None
            tag_strength = "contextual"

            # Приоритет тегов классификации
            if pd.notna(row.get("building")):
                b_val = str(row.get("building")).strip()
                obj_type = f"building_{b_val}" if b_val != "yes" else "warehouse"
                primary_tag = f"building={b_val}"
                if b_val == "warehouse":
                    tag_strength = "strong"
            elif pd.notna(row.get("industrial")):
                ind_val = str(row.get("industrial")).strip()
                obj_type = f"industrial_{ind_val}"
                primary_tag = f"industrial={ind_val}"
                if ind_val in ["warehouse", "logistics", "port"]:
                    tag_strength = "strong"
            elif pd.notna(row.get("harbour")) or pd.notna(row.get("port")):
                obj_type = "port"
                primary_tag = "harbour=yes" if pd.notna(row.get("harbour")) else f"port={row.get('port')}"
                tag_strength = "strong"
            elif pd.notna(row.get("railway")):
                rw_val = str(row.get("railway")).strip()
                obj_type = f"railway_{rw_val}"
                primary_tag = f"railway={rw_val}"
                tag_strength = "strong" if rw_val in ["yard", "loading_ramp"] else "contextual"
            elif pd.notna(row.get("amenity")):
                am_val = str(row.get("amenity")).strip()
                obj_type = am_val
                primary_tag = f"amenity={am_val}"
            elif pd.notna(row.get("landuse")):
                lu_val = str(row.get("landuse")).strip()
                obj_type = f"landuse_{lu_val}"
                primary_tag = f"landuse={lu_val}"

            osm_id_str = self._format_osm_id(row.name if hasattr(row, "name") else idx, row)

            is_building = pd.notna(row.get("building"))
            is_site = not is_building and geom.geom_type in ["Polygon", "MultiPolygon"]

            identification_basis = {
                "matched_tag": primary_tag,
                "tag_strength": tag_strength,
                "name_matched_keyword": matched_kw,
            }

            fallback_title = "Логистический комплекс" if is_site else "Складской объект"
            display_name = name if name else f"{fallback_title} #{len(candidates) + 1} ({obj_type})"

            candidates.append({
                "row_name": row.name if hasattr(row, "name") else idx,
                "osm_id_str": osm_id_str,
                "name": display_name,
                "object_type": obj_type,
                "latitude": round(float(point.y), 6),
                "longitude": round(float(point.x), 6),
                "geometry": geom,
                "is_building": is_building,
                "is_site": is_site,
                "identification_basis": identification_basis,
                "verification_status": (
                    VerificationStatus.VERIFIED.value 
                    if tag_strength == "strong" and matched_kw 
                    else VerificationStatus.CANDIDATE.value
                ),
            })

        if not candidates:
            return []

        # 2. Разделение здания и комплекса (п. 3.3: Spatial Join)
        # Проверяем вхождение зданий в полигоны площадок/территорий
        sites = [c for c in candidates if c["is_site"]]
        nodes: List[LogisticsNode] = []

        # Формируем итоговые объекты LogisticsNode
        for c in candidates:
            parent_site_id: Optional[str] = None
            graph_role = GraphRole.NODE_CANDIDATE.value

            if c["is_building"] and sites:
                # Проверяем, находится ли здание внутри какой-либо площадки
                b_geom = c["geometry"]
                b_pt = b_geom.representative_point() if b_geom.geom_type in ["Polygon", "MultiPolygon"] else b_geom
                for s in sites:
                    s_geom = s["geometry"]
                    if s_geom.contains(b_pt) or s_geom.intersects(b_geom):
                        parent_site_id = f"hub_site_{s['osm_id_str'].replace(':', '_').replace('/', '_')}"
                        graph_role = GraphRole.NESTED_CANDIDATE.value
                        c["identification_basis"]["spatial_relation"] = f"located_within:{parent_site_id}"
                        # Добавляем отметку в родительский сайт
                        nested_list = s["identification_basis"].setdefault("contains_buildings", [])
                        nested_list.append(c["osm_id_str"])
                        break

            node_id = (
                f"hub_site_{c['osm_id_str'].replace(':', '_').replace('/', '_')}"
                if c["is_site"]
                else f"hub_{len(nodes) + 1}_{c['object_type']}"
            )

            node = LogisticsNode(
                id=node_id,
                name=c["name"],
                object_type=c["object_type"],
                latitude=c["latitude"],
                longitude=c["longitude"],
                region_ids=[region_id],
                source_osm_ids=[c["osm_id_str"]],
                verification_status=c["verification_status"],
                transport_modes=[TransportMode.ROAD.value],
                identification_basis=c["identification_basis"],
                parent_site_id=parent_site_id,
                graph_role=graph_role,
            )
            nodes.append(node)

        # Сортировка: сначала самостоятельные вершины (территории и отдельные склады), затем вложенные
        nodes.sort(key=lambda n: 0 if n.graph_role == GraphRole.NODE_CANDIDATE.value else 1)
        selected_nodes = nodes[:limit]

        print(f"[+] Из OSM отфильтровано и отобрано {len(selected_nodes)} логистических объектов "
              f"({sum(1 for n in selected_nodes if n.graph_role == GraphRole.NODE_CANDIDATE.value)} самостоятельных, "
              f"{sum(1 for n in selected_nodes if n.graph_role == GraphRole.NESTED_CANDIDATE.value)} вложенных в комплексы).")
        return selected_nodes

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
            gdf = execute_with_overpass_fallback(
                ox.features_from_bbox,
                bbox=bbox.to_osmnx_bbox(),
                tags=query_tags,
            )
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
            gdf = execute_with_overpass_fallback(
                ox.features_from_place,
                place_name,
                **kwargs,
            )
        except Exception as e:
            print(f"[-] Ошибка при запросе к OSM Overpass API: {e}")
            return []

        if gdf.empty:
            print("[-] Подходящих объектов в указанной локации не найдено.")
            return []

        return self._extract_nodes_from_gdf(gdf=gdf, limit=limit, region_id=region_id)

    def _split_edge_for_virtual_node(
        self,
        road_graph: nx.MultiDiGraph,
        u: int,
        v: int,
        key: int,
        proj_pt: Point,
        cut_dist: float,
        virtual_node_id: int,
    ) -> bool:
        """
        Врезает виртуальную вершину virtual_node_id прямо в дорожный сегмент (u, v)
        в точке перпендикулярной проекции объекта proj_pt, разбивая ребро и сохраняя
        непрерывность и направленность движения.
        """
        if not road_graph.has_edge(u, v, key):
            return False

        fwd_data = dict(road_graph[u][v][key])
        orig_len = float(fwd_data.get("length", 100.0))
        geom = fwd_data.get("geometry")
        if geom is None or not isinstance(geom, LineString):
            geom = LineString([
                (road_graph.nodes[u]["x"], road_graph.nodes[u]["y"]),
                (road_graph.nodes[v]["x"], road_graph.nodes[v]["y"])
            ])

        total_geom_len = max(geom.length, 1e-9)
        ratio = max(0.01, min(0.99, cut_dist / total_geom_len))
        len_1 = max(1.0, round(orig_len * ratio, 1))
        len_2 = max(1.0, round(orig_len - len_1, 1))

        sub_geom1 = substring(geom, 0, cut_dist)
        sub_geom2 = substring(geom, cut_dist, geom.length)

        # 1. Добавляем виртуальную вершину прямо на полотно дороги
        road_graph.add_node(
            virtual_node_id,
            x=float(proj_pt.x),
            y=float(proj_pt.y),
            osmid=virtual_node_id,
            is_virtual=True,
        )

        # 2. Прямые ребра (u -> virt) и (virt -> v)
        data_u_virt = dict(fwd_data)
        data_u_virt["length"] = len_1
        data_u_virt["geometry"] = sub_geom1
        road_graph.add_edge(u, virtual_node_id, key=0, **data_u_virt)

        data_virt_v = dict(fwd_data)
        data_virt_v["length"] = len_2
        data_virt_v["geometry"] = sub_geom2
        road_graph.add_edge(virtual_node_id, v, key=0, **data_virt_v)

        road_graph.remove_edge(u, v, key=key)

        # 3. Обратные ребра (если улица двусторонняя, v -> u)
        if road_graph.has_edge(v, u):
            for rev_k in list(road_graph[v][u].keys()):
                rev_data = dict(road_graph[v][u][rev_k])
                rev_geom = rev_data.get("geometry")
                if rev_geom is not None and isinstance(rev_geom, LineString):
                    rev_cut = rev_geom.project(proj_pt)
                    rev_sub1 = substring(rev_geom, 0, rev_cut)
                    rev_sub2 = substring(rev_geom, rev_cut, rev_geom.length)
                else:
                    rev_sub1 = LineString([
                        (road_graph.nodes[v]["x"], road_graph.nodes[v]["y"]),
                        (proj_pt.x, proj_pt.y)
                    ])
                    rev_sub2 = LineString([
                        (proj_pt.x, proj_pt.y),
                        (road_graph.nodes[u]["x"], road_graph.nodes[u]["y"])
                    ])

                data_v_virt = dict(rev_data)
                data_v_virt["length"] = len_2
                data_v_virt["geometry"] = rev_sub1
                road_graph.add_edge(v, virtual_node_id, key=rev_k, **data_v_virt)

                data_virt_u = dict(rev_data)
                data_virt_u["length"] = len_1
                data_virt_u["geometry"] = rev_sub2
                road_graph.add_edge(virtual_node_id, u, key=rev_k, **data_virt_u)

                road_graph.remove_edge(v, u, key=rev_k)

        return True

    def snap_to_road_network(
        self, 
        road_graph: nx.MultiDiGraph, 
        nodes: List[Any],
        filter_disconnected: bool = True,
        max_snap_distance_m: Optional[float] = None,
    ) -> List[LogisticsNode]:
        """
        Умная пространственная привязка (Smart Snapping) объектов к дорожной сети OSM:
        1. Выделяет основную связную компоненту дорог (Largest Connected Component),
           исключая изолированные тупики и оторванные от мира островки дорог.
        2. Анализирует ближайшие дорожные рёбра и перекрёстки (nearest_edges + nearest_nodes).
        3. Проверяет направленность движения (in_degree и out_degree) для исключения
           односторонних тупиков-ловушек (sinks/sources).
        4. Формирует устойчивый пул точек подключения (access_nodes) с разделением
           на въездные и выездные точки.
        """
        if not nodes:
            return []
        if len(road_graph.nodes) == 0:
            raise ValueError("Дорожный граф пуст, невозможно выполнить привязку объектов.")

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
                        transport_modes=n.get("transport_modes", [TransportMode.ROAD.value]),
                        identification_basis=n.get("identification_basis", {}),
                        parent_site_id=n.get("parent_site_id"),
                        graph_role=n.get("graph_role", GraphRole.NODE_CANDIDATE.value),
                    )
                )

        # 1. Определение основной связной компоненты (Largest Connected Component)
        # Исключаем изолированные островки, где проезд отрезан от остальной сети
        if filter_disconnected and len(road_graph.nodes) > 1:
            try:
                weak_components = list(nx.weakly_connected_components(road_graph))
                largest_cc = max(weak_components, key=len)
                if len(largest_cc) >= 2:
                    active_graph = road_graph.subgraph(largest_cc)
                else:
                    active_graph = road_graph
            except Exception:
                active_graph = road_graph
        else:
            active_graph = road_graph

        lons = [n.longitude for n in log_nodes]
        lats = [n.latitude for n in log_nodes]

        # 2. Поиск ближайших вершин в связной компоненте
        primary_node_ids = ox.nearest_nodes(active_graph, X=lons, Y=lats)
        if not isinstance(primary_node_ids, (list, tuple)) and not hasattr(primary_node_ids, "__iter__"):
            primary_node_ids = [primary_node_ids]

        # 3. Поиск ближайших рёбер в связной компоненте (если есть рёбра)
        nearest_edge_tuples = []
        if len(active_graph.edges) > 0:
            try:
                edge_res = ox.nearest_edges(active_graph, X=lons, Y=lats)
                if hasattr(edge_res, "tolist"):
                    edge_list = edge_res.tolist()
                elif isinstance(edge_res, (list, tuple)):
                    edge_list = list(edge_res)
                else:
                    edge_list = [edge_res]

                if len(log_nodes) == 1 and len(edge_list) > 0 and not isinstance(edge_list[0], (list, tuple)):
                    nearest_edge_tuples = [tuple(edge_list)]
                else:
                    nearest_edge_tuples = [tuple(e) if isinstance(e, (list, tuple)) else e for e in edge_list]
            except Exception:
                nearest_edge_tuples = [None] * len(log_nodes)
        else:
            nearest_edge_tuples = [None] * len(log_nodes)

        snapped_nodes: List[LogisticsNode] = []

        for idx, (node, primary_id) in enumerate(zip(log_nodes, primary_node_ids)):
            primary_id_native = int(primary_id)
            split_succeeded = False
            best_node_id = primary_id_native
            best_lat = float(road_graph.nodes[primary_id_native]["y"])
            best_lon = float(road_graph.nodes[primary_id_native]["x"])
            best_dist = ox.distance.great_circle(node.latitude, node.longitude, best_lat, best_lon)
            access_pool: List[int] = [primary_id_native]

            # 1. Попытка перпендикулярной врезки к ближайшему дорожному сегменту (Edge Splitting)
            if idx < len(nearest_edge_tuples) and nearest_edge_tuples[idx] is not None:
                e_data = nearest_edge_tuples[idx]
                if isinstance(e_data, tuple) and len(e_data) >= 2:
                    u_cand, v_cand = int(e_data[0]), int(e_data[1])
                    e_key = int(e_data[2]) if len(e_data) > 2 else 0

                    if road_graph.has_edge(u_cand, v_cand, e_key):
                        e_attrs = road_graph[u_cand][v_cand][e_key]
                        geom = e_attrs.get("geometry")
                        if geom is None or not isinstance(geom, LineString):
                            geom = LineString([
                                (road_graph.nodes[u_cand]["x"], road_graph.nodes[u_cand]["y"]),
                                (road_graph.nodes[v_cand]["x"], road_graph.nodes[v_cand]["y"])
                            ])

                        fac_pt = Point(node.longitude, node.latitude)
                        cut_dist = geom.project(fac_pt)
                        proj_pt = geom.interpolate(cut_dist)
                        proj_lon, proj_lat = float(proj_pt.x), float(proj_pt.y)

                        proj_dist_m = ox.distance.great_circle(node.latitude, node.longitude, proj_lat, proj_lon)
                        dist_to_u = ox.distance.great_circle(proj_lat, proj_lon, road_graph.nodes[u_cand]["y"], road_graph.nodes[u_cand]["x"])
                        dist_to_v = ox.distance.great_circle(proj_lat, proj_lon, road_graph.nodes[v_cand]["y"], road_graph.nodes[v_cand]["x"])

                        # Проверяем, что улица сквозная (не ведет в односторонний тупик без выезда)
                        is_bidirectional = road_graph.has_edge(v_cand, u_cand)
                        has_exit = is_bidirectional or (road_graph.out_degree(v_cand) > 0)

                        if has_exit:
                            if dist_to_u < 8.0:
                                # Проекция находится в пределах 8 метров от перекрёстка u
                                best_node_id = u_cand
                                best_lat = float(road_graph.nodes[u_cand]["y"])
                                best_lon = float(road_graph.nodes[u_cand]["x"])
                                best_dist = ox.distance.great_circle(node.latitude, node.longitude, best_lat, best_lon)
                                access_pool = [u_cand, v_cand]
                                split_succeeded = True
                            elif dist_to_v < 8.0:
                                # Проекция находится в пределах 8 метров от перекрёстка v
                                best_node_id = v_cand
                                best_lat = float(road_graph.nodes[v_cand]["y"])
                                best_lon = float(road_graph.nodes[v_cand]["x"])
                                best_dist = ox.distance.great_circle(node.latitude, node.longitude, best_lat, best_lon)
                                access_pool = [v_cand, u_cand]
                                split_succeeded = True
                            else:
                                virtual_id = 9_000_000_000 + (idx + 1)
                                if self._split_edge_for_virtual_node(road_graph, u_cand, v_cand, e_key, proj_pt, cut_dist, virtual_id):
                                    best_node_id = virtual_id
                                    best_lat = proj_lat
                                    best_lon = proj_lon
                                    best_dist = proj_dist_m
                                    access_pool = [virtual_id, u_cand, v_cand]
                                    split_succeeded = True

            # 2. Если врезка не удалась — резервный выбор из перекрёстков-кандидатов с защитой от тупиков
            if not split_succeeded:
                candidate_pool = {primary_id_native}
                if idx < len(nearest_edge_tuples) and nearest_edge_tuples[idx] is not None:
                    e_data = nearest_edge_tuples[idx]
                    if isinstance(e_data, tuple) and len(e_data) >= 2:
                        u_cand, v_cand = int(e_data[0]), int(e_data[1])
                        if u_cand in road_graph:
                            candidate_pool.add(u_cand)
                        if v_cand in road_graph:
                            candidate_pool.add(v_cand)

                nodes_to_expand = list(candidate_pool)
                for cid in nodes_to_expand:
                    if cid in road_graph:
                        for neighbor in road_graph.successors(cid):
                            candidate_pool.add(int(neighbor))
                        for predecessor in road_graph.predecessors(cid):
                            candidate_pool.add(int(predecessor))

                candidate_details = []
                for cand_id in candidate_pool:
                    if cand_id in road_graph.nodes:
                        cand_data = road_graph.nodes[cand_id]
                        c_lat = float(cand_data.get("y"))
                        c_lon = float(cand_data.get("x"))
                        d = ox.distance.great_circle(node.latitude, node.longitude, c_lat, c_lon)

                        in_deg = road_graph.in_degree(cand_id)
                        out_deg = road_graph.out_degree(cand_id)

                        is_transit = (in_deg > 0 and out_deg > 0)
                        penalty = 0.0 if is_transit else 100.0
                        score = d + penalty

                        candidate_details.append({
                            "id": cand_id,
                            "dist": d,
                            "score": score,
                            "lat": c_lat,
                            "lon": c_lon,
                            "in_deg": in_deg,
                            "out_deg": out_deg,
                            "is_transit": is_transit,
                        })

                candidate_details.sort(key=lambda x: (x["score"], x["dist"]))

                best_cand = candidate_details[0]
                best_node_id = best_cand["id"]
                best_dist = best_cand["dist"]
                best_lat = best_cand["lat"]
                best_lon = best_cand["lon"]

                access_pool = [best_node_id]
                remaining = sorted(
                    [c for c in candidate_details if c["id"] != best_node_id],
                    key=lambda x: (not x["is_transit"], x["dist"])
                )
                for c in remaining:
                    if len(access_pool) >= 5:
                        break
                    access_pool.append(c["id"])

            if max_snap_distance_m is not None and best_dist > max_snap_distance_m:
                node.nearest_osm_node = None
                node.osm_node_lat = None
                node.osm_node_lon = None
                node.snap_distance_m = round(float(best_dist), 1)
                node.access_nodes = []
                node.is_isolated = True
                node.isolation_reason = (
                    f"Превышен лимит расстояния до автодороги: {round(float(best_dist), 1)} м > {max_snap_distance_m:.1f} м "
                    f"(объект в акватории или нет подъездных путей)"
                )
                snapped_nodes.append(node)
                print(f"  [SmartSnap] '{node.name}' -> [!] ИЗОЛИРОВАН: расстояние до дорожной сети {node.snap_distance_m} м > {max_snap_distance_m:.1f} м (морская акватория / нет автодорог)")
                continue

            node.nearest_osm_node = best_node_id
            node.osm_node_lat = best_lat
            node.osm_node_lon = best_lon
            node.snap_distance_m = round(float(best_dist), 1)
            node.access_nodes = access_pool
            node.is_isolated = False
            node.isolation_reason = None
            snapped_nodes.append(node)

            warning_tag = " [!] ДАЛЕКО" if best_dist > 300 else ""
            tag = " (виртуальный узел на ребре)" if best_node_id >= 9_000_000_000 else " (перекресток)"
            print(f"  [SmartSnap] '{node.name}' -> {len(node.access_nodes)} точек подключения "
                  f"(осн. узел {best_node_id}{tag}, плечо: {node.snap_distance_m} м){warning_tag}")

        return snapped_nodes

