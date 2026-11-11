from typing import Dict, Any, List, Optional, Union, Set, Tuple
import ast
import networkx as nx
from shapely import wkt
from shapely.geometry.base import BaseGeometry
from shapely.geometry import LineString, MultiLineString

from graph_service.kafka.schemas import GraphPayload, NodePayload, EdgePayload


class GraphSerializer:
    """
    Преобразует внутренний граф (дорожный граф маршрутов MultiDiGraph или логистический MultiGraph)
    в DTO GraphPayload в строгом соответствии с контрактом Kafka и Go-оркестратора.
    """

    @classmethod
    def compute_physical_segment_ids(
        cls, graph: Union[nx.MultiGraph, nx.MultiDiGraph, nx.Graph]
    ) -> Dict[Tuple[Any, Any, Any], str]:
        """
        Сопоставляет направленные рёбра MultiDiGraph с физическими дорожными участками
        и присваивает устойчивые segment_id.

        У двух направлений одного физического участка (u -> v и v -> u) segment_id одинаковый,
        даже если ключи k в MultiDiGraph не совпадают (например, k=0 в одну сторону и k=1 в другую).
        У параллельных физических участков между теми же узлами segment_id различны.
        Подъездные коннекторы (edge_type == 'access_connector') исключаются.
        """
        def _get_osmid_set(d: Dict[str, Any]) -> Set[str]:
            raw = d.get("osmid")
            if raw is None:
                return set()
            if isinstance(raw, list):
                return {str(x) for x in raw}
            if isinstance(raw, str) and raw.startswith("["):
                try:
                    parsed = ast.literal_eval(raw)
                    if isinstance(parsed, list):
                        return {str(x) for x in parsed}
                except Exception:
                    pass
            return {str(raw)}

        # 1. Группируем дорожные рёбра по неупорядоченной паре узлов (u_min, u_max)
        node_pairs: Dict[Tuple[str, str], List[Tuple[Any, Any, Any, Dict[str, Any]]]] = {}
        for u, v, k, d in graph.edges(keys=True, data=True):
            if d.get("edge_type") == "access_connector":
                continue
            u_str, v_str = str(u), str(v)
            if u_str == v_str:
                continue
            pair = tuple(sorted([u_str, v_str]))
            node_pairs.setdefault(pair, []).append((u, v, k, d))

        edge_to_seg: Dict[Tuple[Any, Any, Any], str] = {}

        # 2. Для каждой пары узлов формируем физические сегменты (жадное сопоставление 1-к-1)
        for (u_min, u_max), edge_list in node_pairs.items():
            fwd = [(u, v, k, d) for u, v, k, d in edge_list if str(u) == u_min]
            rev = [(u, v, k, d) for u, v, k, d in edge_list if str(u) == u_max]

            unmatched_rev = list(rev)
            segments: List[List[Tuple[Any, Any, Any]]] = []

            for f_u, f_v, f_k, f_d in fwd:
                f_osms = _get_osmid_set(f_d)
                f_len = float(f_d.get("length", 0.0) or f_d.get("length_m", 0.0))
                best_match_idx = None
                best_score = -1.0

                if not f_d.get("oneway", False):
                    for r_idx, (r_u, r_v, r_k, r_d) in enumerate(unmatched_rev):
                        if r_d.get("oneway", False):
                            continue
                        r_osms = _get_osmid_set(r_d)
                        r_len = float(r_d.get("length", 0.0) or r_d.get("length_m", 0.0))

                        score = 0.0
                        # Совпадение OSM ID — признак принадлежности к одному OSM way
                        if f_osms and r_osms and (f_osms & r_osms):
                            score += 1000.0

                        # Совпадение длины
                        if f_len > 0.0 and r_len > 0.0:
                            diff_rel = abs(f_len - r_len) / max(f_len, r_len)
                            if diff_rel < 0.05:
                                score += 100.0
                            elif diff_rel < 0.25:
                                score += 40.0
                        elif len(fwd) == 1 and len(rev) == 1:
                            score += 500.0

                        if score > best_score and score >= 40.0:
                            best_score = score
                            best_match_idx = r_idx

                if best_match_idx is not None:
                    matched_r = unmatched_rev.pop(best_match_idx)
                    segments.append([(f_u, f_v, f_k), (matched_r[0], matched_r[1], matched_r[2])])
                else:
                    segments.append([(f_u, f_v, f_k)])

            # Оставшиеся обратные рёбра (односторонние или без пары)
            for r_u, r_v, r_k, r_d in unmatched_rev:
                segments.append([(r_u, r_v, r_k)])

            # 3. Детерминированная сортировка сегментов для стабильности segment_id
            def seg_sort_key(seg_edges):
                sort_items = []
                for e_u, e_v, e_k in seg_edges:
                    d = graph[e_u][e_v][e_k]
                    osms = _get_osmid_set(d)
                    min_osm = min(osms) if osms else ""
                    length_val = float(d.get("length", 0.0) or d.get("length_m", 0.0))
                    sort_items.append((min_osm, length_val, str(e_u), str(e_v), str(e_k)))
                return sorted(sort_items)

            segments.sort(key=seg_sort_key)

            # 4. Присвоение segment_id
            for idx, seg_edges in enumerate(segments):
                seg_id = f"seg_{u_min}_{u_max}" if len(segments) == 1 else f"seg_{u_min}_{u_max}_{idx}"
                for e_u, e_v, e_k in seg_edges:
                    edge_to_seg[(e_u, e_v, e_k)] = seg_id

        return edge_to_seg

    @classmethod
    def serialize(cls, log_graph: Union[nx.MultiGraph, nx.MultiDiGraph, nx.Graph]) -> GraphPayload:
        """
        Преобразует граф сети в GraphPayload:
        - Координаты вершин position: строго [lon, lat] с округлением до 6 знаков.
        - Атрибуты вершин: object_type ("warehouse", "intersection", "road_node"), name, etc.
        - Геометрия рёбер: [[lon, lat], ...] вдоль фактической геометрии дорожных сегментов/коннекторов.
        - Атрибуты рёбер: edge_type ("road" / "access_connector"), length_m, routes_count, etc.
        - segment_id: физический ID дорожного участка (одинаков для u->v и v->u).
        """
        nodes: List[NodePayload] = []
        edges: List[EdgePayload] = []

        # 0. Предварительно вычисляем сопоставление физических сегментов для дорожных рёбер
        seg_id_map = cls.compute_physical_segment_ids(log_graph)

        # 1. Сериализация вершин
        for node_id, data in log_graph.nodes(data=True):
            lon = data.get("x") or data.get("lon") or data.get("longitude")
            lat = data.get("y") or data.get("lat") or data.get("latitude")

            if lon is None or lat is None:
                continue

            node_attrs: Dict[str, Any] = {
                "name": str(data.get("name", str(node_id))),
                "object_type": str(data.get("object_type", "road_node")),
            }

            for extra_key in (
                "is_isolated",
                "isolation_reason",
                "snap_kind",
                "snap_distance_m",
                "nearest_osm_node",
                "street_count",
                "highway",
                "original_lat",
                "original_lon",
                "snapped_road_node",
            ):
                if extra_key in data and data[extra_key] is not None:
                    node_attrs[extra_key] = data[extra_key]

            nodes.append(
                NodePayload(
                    id=str(node_id),
                    position=[round(float(lon), 6), round(float(lat), 6)],
                    attributes=node_attrs,
                )
            )

        # 2. Сериализация рёбер
        edge_idx = 0
        for u, v, k, data in log_graph.edges(keys=True, data=True):
            edge_idx += 1
            edge_id = str(data.get("id") or f"e_{u}_{v}_{k}_{edge_idx}")

            # Извлечение геометрии
            geom_coords: Optional[List[List[float]]] = None

            raw_geom = data.get("geometry")
            if raw_geom is not None and isinstance(raw_geom, (LineString, MultiLineString)):
                if isinstance(raw_geom, LineString):
                    geom_coords = [[round(pt[0], 6), round(pt[1], 6)] for pt in raw_geom.coords]
                elif isinstance(raw_geom, MultiLineString):
                    geom_coords = []
                    for line in raw_geom.geoms:
                        geom_coords.extend([[round(pt[0], 6), round(pt[1], 6)] for pt in line.coords])
            else:
                wkt_str = (
                    data.get("geometry_wkt")
                    or data.get("road_geometry_ab_wkt")
                    or data.get("geometry_ab_wkt")
                    or data.get("road_geom_wkt")
                )
                if wkt_str:
                    geom_coords = cls._parse_wkt_to_coords(wkt_str)

            # Если геометрии нет или менее 2 точек, используем отрезок между координатами узлов
            if not geom_coords or len(geom_coords) < 2:
                node_u_data = log_graph.nodes.get(u, {})
                node_v_data = log_graph.nodes.get(v, {})
                u_lon = node_u_data.get("x") or node_u_data.get("lon") or node_u_data.get("longitude")
                u_lat = node_u_data.get("y") or node_u_data.get("lat") or node_u_data.get("latitude")
                v_lon = node_v_data.get("x") or node_v_data.get("lon") or node_v_data.get("longitude")
                v_lat = node_v_data.get("y") or node_v_data.get("lat") or node_v_data.get("latitude")
                if u_lon is not None and u_lat is not None and v_lon is not None and v_lat is not None:
                    geom_coords = [
                        [round(float(u_lon), 6), round(float(u_lat), 6)],
                        [round(float(v_lon), 6), round(float(v_lat), 6)],
                    ]

            # Формирование атрибутов ребра
            edge_attrs: Dict[str, Any] = {
                "transport_mode": data.get("transport_mode", "road"),
            }

            if "edge_type" in data:
                edge_attrs["edge_type"] = data["edge_type"]
                if "length_m" in data and data["length_m"] is not None:
                    try:
                        edge_attrs["length_m"] = round(float(data["length_m"]), 2)
                    except (ValueError, TypeError):
                        pass
                if "routes_count" in data and data["routes_count"] is not None:
                    try:
                        edge_attrs["routes_count"] = int(data["routes_count"])
                    except (ValueError, TypeError):
                        pass
                for opt_key in ("highway", "name", "oneway", "maxspeed", "warehouse_id", "road_node_id", "direction"):
                    if opt_key in data and data[opt_key] is not None and data[opt_key] != "":
                        edge_attrs[opt_key] = data[opt_key]
                if "route_ids" in data and data["route_ids"]:
                    edge_attrs["route_ids"] = list(data["route_ids"])
            else:
                # Обратная совместимость с логистическим графом склад-склад
                for st_key in ("route_status_ab", "route_status_ba"):
                    if st_key in data and data[st_key]:
                        edge_attrs[st_key] = data[st_key]
                for num_attr in ("total_distance_ab_m", "total_distance_ba_m", "distance_ab_m", "distance_ba_m"):
                    val = data.get(num_attr)
                    if val is not None:
                        try:
                            edge_attrs[num_attr] = round(float(val), 2)
                        except (ValueError, TypeError):
                            pass
                for str_attr in ("node_a_name", "node_b_name"):
                    if str_attr in data and data[str_attr]:
                        edge_attrs[str_attr] = data[str_attr]

            # segment_id: у двух направлений одного физического участка дорог значение одинаковое.
            # У access_connector поле отсутствует.
            segment_id = data.get("segment_id")
            if not segment_id and data.get("edge_type") != "access_connector":
                segment_id = seg_id_map.get((u, v, k))
            elif data.get("edge_type") == "access_connector":
                segment_id = None

            edges.append(
                EdgePayload(
                    id=edge_id,
                    source=str(u),
                    target=str(v),
                    segment_id=segment_id,
                    geometry=geom_coords,
                    attributes=edge_attrs,
                )
            )

        return GraphPayload(nodes=nodes, edges=edges)

    @staticmethod
    def _parse_wkt_to_coords(wkt_str: str) -> Optional[List[List[float]]]:
        """
        Преобразует WKT строку геометрии в список координат [[lon, lat], ...].
        """
        try:
            geom: BaseGeometry = wkt.loads(wkt_str)
            coords: List[List[float]] = []
            if geom.geom_type == "LineString":
                coords = [[round(pt[0], 6), round(pt[1], 6)] for pt in geom.coords]
            elif geom.geom_type == "MultiLineString":
                for line in geom.geoms:
                    coords.extend([[round(pt[0], 6), round(pt[1], 6)] for pt in line.coords])
            return coords if len(coords) >= 2 else None
        except Exception:
            return None

