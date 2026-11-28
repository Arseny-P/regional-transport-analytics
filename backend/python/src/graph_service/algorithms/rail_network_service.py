import os
import json
import math
from typing import Dict, Any, List, Tuple, Set, Optional
import networkx as nx
import pyproj
from shapely.geometry import box, LineString, Point

from graph_service.domain.models import TerritoryBounds, RailNodeKind, RailObjectType
from graph_service.domain.errors import OfflineDataNotFoundError, OSMUnavailableError
from graph_service.config import config
from graph_service.fixtures import find_rail_fixture_files
from graph_service.http.osm_client import query_overpass_json


LIFECYCLE_TAGS = {"disused", "abandoned", "construction", "proposed", "razed", "demolished", "removed"}
SPECIAL_KIND_MAP = {
    "switch": RailNodeKind.SWITCH.value,
    "buffer_stop": RailNodeKind.BUFFER_STOP.value,
    "railway_crossing": RailNodeKind.CROSSING.value,
}


class RailNetworkService:
    """
    Сервис загрузки, фильтрации, обрезки и топологического сжатия
    железнодорожной сети OpenStreetMap.
    """

    def __init__(self, storage_dir: str = "data"):
        self.storage_dir = storage_dir
        self.geod = pyproj.Geod(ellps="WGS84")
        os.makedirs(self.storage_dir, exist_ok=True)

    @staticmethod
    def classify_way(tags: Dict[str, Any]) -> Tuple[str, str]:
        """
        Классифицирует линию OSM по правилам железнодорожной модели:
        - railway=rail без конфликта состояния -> selected
        - railway=rail с префиксом состояния -> review
        - неактивное состояние или не rail -> excluded
        """
        rw = str(tags.get("railway", "")).strip().lower()
        prefixed = [f"{st}:railway" for st in sorted(LIFECYCLE_TAGS) if tags.get(f"{st}:railway")]
        flags = [st for st in sorted(LIFECYCLE_TAGS) if str(tags.get(st, "")).lower() in {"yes", "true", "1"}]

        if rw == "rail" and prefixed:
            return "review", "active_and_lifecycle_tags"
        if rw in LIFECYCLE_TAGS or prefixed or flags:
            return "excluded", "lifecycle"
        if rw != "rail":
            return "excluded", "not_rail"
        return "selected", "rail"

    def fetch_data_from_bbox(
        self, bbox: TerritoryBounds, refetch: bool = False
    ) -> Tuple[Dict[str, Any], Dict[int, Dict[str, Any]]]:
        """
        Загружает данные путей и специальных узлов OSM для заданного BBox.
        Поддерживает оффлайн-режим (фикстуры) и кэширование на диск.
        """
        bbox.validate()
        alias = bbox.cache_key()
        ways_cache_file = os.path.join(self.storage_dir, f"{alias}_rail_ways.json")
        objs_cache_file = os.path.join(self.storage_dir, f"{alias}_rail_objects.json")

        # 1. Проверка оффлайн-режима
        if config.osm_offline_mode:
            print(f"[*] [OFFLINE] Загрузка ЖД-данных из фикстур для {alias}...")
            ways_fix, objs_fix = find_rail_fixture_files(alias=alias, custom_dir=self.storage_dir)
            if not ways_fix or not os.path.exists(ways_fix):
                raise OfflineDataNotFoundError(
                    f"Оффлайн-фикстуры ЖД-путей не найдены для территории '{alias}'. "
                    f"Проверены директории фикстур и кэша."
                )
            with open(ways_fix, "r", encoding="utf-8") as f:
                ways_data = json.load(f)

            objs_data = {"response": {"elements": []}}
            if objs_fix and os.path.exists(objs_fix):
                with open(objs_fix, "r", encoding="utf-8") as f:
                    objs_data = json.load(f)

            ways_elements = ways_data.get("response", {}).get("elements", ways_data.get("elements", []))
            objs_elements = objs_data.get("response", {}).get("elements", objs_data.get("elements", []))
            point_tags = {}
            for el in objs_elements:
                if el.get("type") == "node" and "tags" in el:
                    point_tags[el["id"]] = el["tags"]

            return {"elements": ways_elements}, point_tags, objs_elements

        # 2. Локальный кэш
        if not refetch and os.path.exists(ways_cache_file) and os.path.exists(objs_cache_file):
            print(f"[*] Загрузка ЖД-данных из локального кэша: {ways_cache_file}...")
            with open(ways_cache_file, "r", encoding="utf-8") as f:
                ways_data = json.load(f)
            with open(objs_cache_file, "r", encoding="utf-8") as f:
                objs_data = json.load(f)

            ways_elements = ways_data.get("response", {}).get("elements", ways_data.get("elements", []))
            objs_elements = objs_data.get("response", {}).get("elements", objs_data.get("elements", []))
            point_tags = {}
            for el in objs_elements:
                if el.get("type") == "node" and "tags" in el:
                    point_tags[el["id"]] = el["tags"]

            return {"elements": ways_elements}, point_tags, objs_elements

        # 3. Онлайн-запрос Overpass с ротацией зеркал
        print(f"[*] Запрос ЖД-сети Overpass для bbox: {bbox.to_dict()}...")
        bbox_ql = f"{bbox.min_lat},{bbox.min_lon},{bbox.max_lat},{bbox.max_lon}"
        ways_query = f'[out:json][timeout:45];way["railway"]({bbox_ql});out meta geom;'
        objs_query = f'[out:json][timeout:45];(node["railway"]({bbox_ql}););out meta;'

        try:
            ways_raw = query_overpass_json(ways_query)
            objs_raw = query_overpass_json(objs_query)
        except Exception as e:
            raise OSMUnavailableError(f"Ошибка загрузки данных железнодорожной сети OSM: {e}") from e

        # Сохранение в локальный кэш
        with open(ways_cache_file, "w", encoding="utf-8") as f:
            json.dump({"bbox": bbox.to_dict(), "response": ways_raw}, f, ensure_ascii=False)
        with open(objs_cache_file, "w", encoding="utf-8") as f:
            json.dump({"bbox": bbox.to_dict(), "response": objs_raw}, f, ensure_ascii=False)

        objs_elements = objs_raw.get("elements", [])
        point_tags = {}
        for el in objs_elements:
            if el.get("type") == "node" and "tags" in el:
                point_tags[el["id"]] = el["tags"]

        return {"elements": ways_raw.get("elements", [])}, point_tags, objs_elements

    def build_from_bbox(
        self,
        bbox: TerritoryBounds,
        anchors: Optional[Set[str]] = None,
        refetch: bool = False,
    ) -> Tuple[nx.MultiGraph, nx.MultiGraph]:
        """
        Строит железнодорожный граф для заданной территории:
        1. Загружает сырые пути и специальные узлы.
        2. Фильтрует пути и отсекает посторонние виды транспорта / неактивные пути.
        3. Обрезает пути строго по границе BBox с формированием граничных узлов 'boundary'.
        4. Выполняет топологическое сжатие промежуточных узлов (degree == 2).

        Возвращает кортеж (G_geom, G_simple), где:
        - G_geom: обрезанный геометрический граф до сжатия.
        - G_simple: сжатый граф с сохраненными параллельными путями и длинами.
        """
        ways_dict, point_tags, _ = self.fetch_data_from_bbox(bbox, refetch=refetch)
        elements = ways_dict.get("elements", [])

        # Отбор целевых путей
        selected_ways = {}
        for el in elements:
            if el.get("type") == "way":
                dec, _ = self.classify_way(el.get("tags", {}))
                if dec == "selected":
                    selected_ways[el["id"]] = el

        area = box(bbox.min_lon, bbox.min_lat, bbox.max_lon, bbox.max_lat)
        G_geom = nx.MultiGraph()

        def add_rail_node(graph: nx.MultiGraph, node_id: str, coordinate: Tuple[float, float], osm_id: Optional[int] = None):
            lon, lat = coordinate
            tags = point_tags.get(osm_id, {}) if osm_id is not None else {}
            boundary = area.boundary.distance(Point(lon, lat)) < 1e-9
            raw_rw = tags.get("railway")
            graph.add_node(
                node_id,
                longitude=lon,
                latitude=lat,
                object_type=RailObjectType.RAIL_NODE.value,
                node_kind=SPECIAL_KIND_MAP.get(raw_rw, RailNodeKind.BOUNDARY.value if boundary else RailNodeKind.INTERMEDIATE.value),
                classification_basis="osm_tag" if raw_rw in SPECIAL_KIND_MAP else "geometry",
                is_switch=(raw_rw == "switch"),
                is_boundary=boundary,
                has_buffer_stop=(raw_rw == "buffer_stop"),
                source_osm_id=osm_id,
                source_tags=tags,
            )

        for way_id, way in selected_ways.items():
            ids = way.get("nodes", [])
            geometry = way.get("geometry", [])
            if len(ids) != len(geometry) or any("lon" not in p or "lat" not in p for p in geometry):
                continue

            coordinates = [(p["lon"], p["lat"]) for p in geometry]
            tags = way.get("tags", {})
            signature = tuple(
                str(tags.get(k, ""))
                for k in ["gauge", "oneway", "railway:preferred_direction", "railway:bidirectional"]
            )

            for i, (osm_u, osm_v) in enumerate(zip(ids, ids[:-1] and ids[1:])):
                a, b = coordinates[i], coordinates[i + 1]
                if osm_u == osm_v or a == b:
                    continue

                clipped = LineString([a, b]).intersection(area)
                parts = [clipped] if clipped.geom_type == "LineString" else list(getattr(clipped, "geoms", []))
                for j, part in enumerate(parts):
                    if part.geom_type != "LineString" or part.is_empty or part.length == 0:
                        continue

                    coords = list(part.coords)
                    end_ids = []
                    for side, coordinate in enumerate([coords[0], coords[-1]]):
                        original = next(
                            (
                                nid
                                for nid, xy in [(osm_u, a), (osm_v, b)]
                                if abs(xy[0] - coordinate[0]) < 1e-10 and abs(xy[1] - coordinate[1]) < 1e-10
                            ),
                            None,
                        )
                        nid = f"osm_node:{original}" if original is not None else f"boundary:{way_id}:{i}:{j}:{side}"
                        add_rail_node(G_geom, nid, coordinate, original)
                        end_ids.append(nid)

                    length = sum(self.geod.inv(*c1, *c2)[2] for c1, c2 in zip(coords, coords[1:]))
                    if not math.isfinite(length) or length <= 0:
                        continue

                    segment = f"rail:{way_id}:{i}:{j}"
                    G_geom.add_edge(
                        *end_ids,
                        key=segment,
                        id=segment,
                        segment_id=segment,
                        length_m=length,
                        geometry=part,
                        geometry_from=end_ids[0],
                        source_osm_ids=[f"way/{way_id}"],
                        source_segment_ids=[segment],
                        routing_signature=signature,
                        source_tags=tags,
                    )

        # Классификация разветвлений и тупиков по топологии
        for n, data in G_geom.nodes(data=True):
            data["physical_degree"] = G_geom.degree(n)
            if data["node_kind"] == RailNodeKind.INTERMEDIATE.value:
                degree = len(set(G_geom.neighbors(n)))
                if degree >= 3:
                    data.update(node_kind=RailNodeKind.JUNCTION.value, classification_basis="topology_candidate")
                elif degree == 1:
                    data.update(node_kind=RailNodeKind.ENDPOINT.value, classification_basis="topology_candidate")

        # Топологическое сжатие промежуточных узлов
        G_simple = self.simplify_geometry(G_geom, anchors=anchors)
        return G_geom, G_simple

    def simplify_geometry(
        self, graph: nx.MultiGraph, anchors: Optional[Set[str]] = None
    ) -> nx.MultiGraph:
        """
        Сжимает цепочки промежуточных узлов (degree == 2), сохраняя общую геодезическую длину,
        геометрию LineString, специальные точки, границы и параллельные физические пути.
        """
        anchors = anchors or set()
        keep = {
            n
            for n, d in graph.nodes(data=True)
            if graph.degree(n) != 2
            or d.get("node_kind") != RailNodeKind.INTERMEDIATE.value
            or d.get("is_boundary", False)
            or n in anchors
        }

        # Сохраняем узлы, где меняется сигнатура маршрутизации (колея, направления)
        for n in graph:
            signatures = {d.get("routing_signature") for *_, d in graph.edges(n, keys=True, data=True)}
            if len(signatures) > 1:
                keep.add(n)

        # В изолированных кольцах сохраняем минимум один узел
        for component in nx.connected_components(graph):
            if not keep.intersection(component):
                keep.add(min(component))

        result = nx.MultiGraph()
        result.add_nodes_from((n, dict(graph.nodes[n])) for n in keep)
        visited = set()

        def token(u: str, v: str, k: str) -> Tuple[str, str, str]:
            return (min(u, v), max(u, v), k)

        for start in sorted(keep):
            for _, next_node, key in list(graph.edges(start, keys=True)):
                if token(start, next_node, key) in visited:
                    continue

                current, target, edge_key = start, next_node, key
                coords, source_ids, segments, length = [], set(), [], 0.0
                signature = None

                while True:
                    edge = graph[current][target][edge_key]
                    visited.add(token(current, target, edge_key))
                    part = list(edge["geometry"].coords)
                    if edge.get("geometry_from") != current:
                        part.reverse()

                    coords.extend(part if not coords else part[1:])
                    length += edge["length_m"]
                    source_ids.update(edge.get("source_osm_ids", []))
                    segments.extend(edge.get("source_segment_ids", []))
                    signature = edge.get("routing_signature")

                    current = target
                    if current in keep:
                        break

                    candidates = [
                        (v, k)
                        for _, v, k in graph.edges(current, keys=True)
                        if token(current, v, k) not in visited
                    ]
                    if len(candidates) != 1:
                        raise ValueError("Неоднозначное продолжение цепочки при геометрическом сжатии")
                    target, edge_key = candidates[0]

                new_id = f"segment:{len(result.edges)}"
                result.add_edge(
                    start,
                    current,
                    key=new_id,
                    id=new_id,
                    segment_id=new_id,
                    length_m=length,
                    geometry=LineString(coords),
                    geometry_from=start,
                    source_osm_ids=sorted(source_ids),
                    source_segment_ids=segments,
                    routing_signature=signature,
                )

        return result

    @staticmethod
    def to_routing_graph(graph: nx.MultiGraph) -> nx.MultiDiGraph:
        """
        Преобразует физический MultiGraph в направленный MultiDiGraph для поиска кратчайших путей.
        Учитывает правила одностороннего движения oneway:
        - oneway=yes/true/1: прямое направление (от geometry_from)
        - oneway=-1: обратное направление
        - иначе: дуги в обоих направлениях
        """
        routed = nx.MultiDiGraph()
        routed.add_nodes_from((n, dict(d)) for n, d in graph.nodes(data=True))

        for u, v, key, d in graph.edges(keys=True, data=True):
            signature = d.get("routing_signature", ("", "", "", ""))
            # signature: (gauge, oneway, preferred_direction, bidirectional)
            oneway_val = signature[1].lower() if len(signature) > 1 else ""

            forward_node = d.get("geometry_from", u)
            backward_node = v if forward_node == u else u
            geom = d.get("geometry")
            coords = list(geom.coords) if geom is not None else []

            directions = ["forward", "backward"]
            if oneway_val in {"yes", "true", "1"}:
                directions = ["forward"]
            elif oneway_val in {"-1"}:
                directions = ["backward"]

            edge_id = str(d.get("id", key))
            segment_id = str(d.get("segment_id", key))
            length_m = float(d.get("length_m", 0.0))

            for direction in directions:
                if direction == "forward":
                    src, dst = forward_node, backward_node
                    edge_geom = LineString(coords) if len(coords) >= 2 else None
                else:
                    src, dst = backward_node, forward_node
                    edge_geom = LineString(coords[::-1]) if len(coords) >= 2 else None

                routed.add_edge(
                    src,
                    dst,
                    key=f"{key}:{direction}",
                    id=f"{edge_id}:{direction}",
                    segment_id=segment_id,
                    length_m=length_m,
                    geometry=edge_geom,
                    source_osm_ids=d.get("source_osm_ids", []),
                    source_segment_ids=d.get("source_segment_ids", []),
                )

        return routed

    @staticmethod
    def to_centrality_digraph(graph: nx.MultiDiGraph) -> nx.DiGraph:
        """
        Формирует вспомогательный ориентированный DiGraph для точного расчета
        Betweenness Centrality. Сворачивает параллельные дуги до минимальной длины,
        вес задается в положительных целых сантиметрах (weight_cm).
        """
        result = nx.DiGraph()
        result.add_nodes_from((n, dict(d)) for n, d in graph.nodes(data=True))

        for u, v, d in graph.edges(data=True):
            weight_cm = max(1, round(d["length_m"] * 100))
            if not result.has_edge(u, v) or weight_cm < result[u][v]["weight_cm"]:
                result.add_edge(u, v, weight_cm=weight_cm, length_m=d["length_m"])

        return result
