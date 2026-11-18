import math
from collections import Counter
from typing import List, Dict, Any, Optional, Set
import networkx as nx

from graph_service.config import config
from graph_service.kafka.schemas import MetricItem
from graph_service.domain.errors import MetricsCalculationError


WAREHOUSE_TYPES: Set[str] = {"warehouse", "facility", "terminal", "port"}
ROAD_NODE_TYPES: Set[str] = {"intersection", "road_node"}


class GraphMetricsService:
    """
    Сервис расчёта графовых метрик логистической транспортной сети (задачи #28, #71, #72).
    Поддерживает как новую модель дорожного графа маршрутов (#71), так и обратную совместимость
    со структурными графами склад-склад.
    """

    @classmethod
    def calculate_metrics(
        cls,
        log_graph: nx.Graph,
        routes: Optional[List[Dict[str, Any]]] = None,
        warehouse_neighbor_radius_m: Optional[float] = None,
    ) -> List[MetricItem]:
        """
        Вычисляет набор графовых метрик для заданного графа.
        Для дорожного графа маршрутов возвращает региональные метрики (node_id=None),
        метрики складов (node_id=warehouse_id) и перекрёстков (node_id=intersection_id).
        """
        try:
            if cls._is_road_graph(log_graph):
                radius_m = (
                    warehouse_neighbor_radius_m
                    if warehouse_neighbor_radius_m is not None
                    else getattr(config, "warehouse_neighbor_radius_m", 2000.0)
                )
                routes_list = routes if routes is not None else log_graph.graph.get("routes", [])
                return cls._calculate_road_graph_metrics(log_graph, routes_list, radius_m)
            else:
                return cls._calculate_legacy_metrics(log_graph)
        except Exception as err:
            raise MetricsCalculationError(f"Ошибка вычисления графовых метрик: {err}") from err

    @classmethod
    def _is_road_graph(cls, graph: nx.Graph) -> bool:
        """
        Определяет, является ли переданный граф дорожным графом маршрутов (Спринты 4-5).
        В дорожном графе обязательно присутствуют рёбра дорожной сети (road, access_connector)
        или дорожные узлы (intersection, road_node).
        """
        for _, _, data in graph.edges(data=True):
            if data.get("edge_type") in ("road", "access_connector"):
                return True
        for _, data in graph.nodes(data=True):
            if data.get("object_type") in ROAD_NODE_TYPES:
                return True
        return False

    @classmethod
    def _calculate_road_graph_metrics(
        cls,
        graph: nx.Graph,
        routes: List[Dict[str, Any]],
        radius_m: float,
    ) -> List[MetricItem]:
        """
        Расчёт полного набора метрик дорожного графа по спецификации #71.
        """
        metrics: List[MetricItem] = []

        warehouse_nodes = [
            n for n, d in graph.nodes(data=True) if d.get("object_type") in WAREHOUSE_TYPES
        ]
        intersection_nodes = [
            n for n, d in graph.nodes(data=True) if d.get("object_type") == "intersection"
        ]
        road_nodes = [
            n for n, d in graph.nodes(data=True) if d.get("object_type") == "road_node"
        ]

        # -------------------------------------------------------------
        # 1. Региональные метрики (общие для анализа, node_id=None)
        # -------------------------------------------------------------
        # Уникальные физические сегменты дорог (исключая None и коннекторы)
        segments = {
            d.get("segment_id")
            for _, _, d in graph.edges(data=True)
            if d.get("edge_type") == "road" and d.get("segment_id") is not None
        }

        # Компоненты связности
        if graph.is_directed():
            comp_count = float(nx.number_weakly_connected_components(graph))
        else:
            comp_count = float(nx.number_connected_components(graph))

        # Обязательные показатели региона по #71
        metrics.append(MetricItem(name="warehouse_count", value=float(len(warehouse_nodes))))
        metrics.append(MetricItem(name="intersection_count", value=float(len(intersection_nodes))))
        metrics.append(MetricItem(name="road_segment_count", value=float(len(segments))))
        metrics.append(MetricItem(name="component_count", value=comp_count))
        metrics.append(MetricItem(name="connected_components_count", value=comp_count))

        # Технические показатели
        metrics.append(MetricItem(name="node_count", value=float(graph.number_of_nodes())))
        metrics.append(MetricItem(name="road_node_count", value=float(len(road_nodes))))
        directed_roads = sum(1 for _, _, d in graph.edges(data=True) if d.get("edge_type") == "road")
        metrics.append(MetricItem(name="directed_road_edge_count", value=float(directed_roads)))
        connectors = sum(1 for _, _, d in graph.edges(data=True) if d.get("edge_type") == "access_connector")
        metrics.append(MetricItem(name="access_connector_count", value=float(connectors)))

        # Совместимость с фронтендом (METRIC_LABELS)
        metrics.append(MetricItem(name="vertex_count", value=float(graph.number_of_nodes())))
        metrics.append(MetricItem(name="edge_count", value=float(graph.number_of_edges())))

        if routes:
            total_r = float(len(routes))
            found_r = float(sum(1 for r in routes if isinstance(r, dict) and r.get("status") == "found"))
            metrics.append(MetricItem(name="total_routes_count", value=total_r))
            metrics.append(MetricItem(name="found_routes_count", value=found_r))

            connected_warehouses = {
                str(r.get("origin_id")) for r in routes if isinstance(r, dict) and r.get("status") == "found"
            } | {
                str(r.get("destination_id")) for r in routes if isinstance(r, dict) and r.get("status") == "found"
            }
            without_routes = float(len(set(map(str, warehouse_nodes)) - connected_warehouses))
            metrics.append(MetricItem(name="warehouses_without_routes_count", value=without_routes))

        # -------------------------------------------------------------
        # 2. Метрики складов (node_id = warehouse_id)
        # -------------------------------------------------------------
        wh_ids = list(dict.fromkeys(map(str, warehouse_nodes)))
        wh_id_set = set(wh_ids)
        wh_rows = {
            w: {
                "min_m": None,
                "checked_count": 0,
                "found_count": 0,
                "nearby_count": 0,
            }
            for w in wh_ids
        }

        seen_pairs = set()
        for r in routes:
            if not isinstance(r, dict):
                continue
            origin = str(r.get("origin_id"))
            dest = str(r.get("destination_id"))
            if origin == dest or origin not in wh_id_set or dest not in wh_id_set:
                continue

            pair = (origin, dest)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            status = r.get("status")
            row = wh_rows[origin]
            if status == "not_found_in_data":
                row["checked_count"] += 1
                continue
            if status != "found":
                continue

            row["checked_count"] += 1
            d = r.get("road_length_m")
            if d is None or not math.isfinite(float(d)) or float(d) < 0:
                continue

            dist_val = float(d)
            row["found_count"] += 1
            if row["min_m"] is None or dist_val < row["min_m"]:
                row["min_m"] = dist_val

            if dist_val <= radius_m:
                row["nearby_count"] += 1

        for w, row in wh_rows.items():
            complete = (row["checked_count"] == len(wh_ids) - 1) if len(wh_ids) > 1 else True
            if complete:
                # Если найден хотя бы один маршрут, передаём кратчайшую дистанцию.
                # Если путей нет (изолирован), None не сериализуется в 0.0, а опускается.
                if row["min_m"] is not None:
                    metrics.append(
                        MetricItem(
                            name="nearest_warehouse_distance_m",
                            value=round(row["min_m"], 4),
                            node_id=str(w),
                        )
                    )
                metrics.append(
                    MetricItem(
                        name="nearby_warehouse_count",
                        value=float(row["nearby_count"]),
                        node_id=str(w),
                    )
                )

        # -------------------------------------------------------------
        # 3. Метрики перекрёстков (node_id = intersection_id)
        # -------------------------------------------------------------
        if intersection_nodes:
            H = cls._simple_road_digraph(graph)
            n_nodes = H.number_of_nodes()

            # PageRank
            try:
                pr = nx.pagerank(H, alpha=0.85, weight=None) if n_nodes > 0 else {}
            except Exception:
                pr = {}

            # Betweenness Centrality (с переключением на сэмплирование k=64 при N > 1000)
            try:
                if n_nodes > 0:
                    k = min(64, n_nodes) if n_nodes > 1000 else None
                    bc = nx.betweenness_centrality(
                        H, k=k, normalized=True, weight="weight_cm", endpoints=False, seed=42
                    )
                else:
                    bc = {}
            except Exception:
                bc = {}

            # Доля складских маршрутов через перекрёсток
            shares = cls._intersection_route_fraction(graph, routes)

            for ix_node in intersection_nodes:
                node_str = str(ix_node)
                if ix_node in pr:
                    metrics.append(
                        MetricItem(
                            name="pagerank",
                            value=round(float(pr[ix_node]), 6),
                            node_id=node_str,
                        )
                    )
                if ix_node in bc:
                    metrics.append(
                        MetricItem(
                            name="betweenness_centrality",
                            value=round(float(bc[ix_node]), 6),
                            node_id=node_str,
                        )
                    )
                frac = shares.get(node_str)
                if frac is not None:
                    metrics.append(
                        MetricItem(
                            name="route_fraction",
                            value=round(float(frac), 6),
                            node_id=node_str,
                        )
                    )

        return metrics

    @classmethod
    def _simple_road_digraph(cls, graph: nx.Graph) -> nx.DiGraph:
        """
        Строит упрощённый направленный дорожный граф (только перекрёстки и дорожные узлы).
        Параллельные рёбра сворачиваются до минимальной длины в сантиметрах weight_cm.
        """
        road_nodes = [
            n for n, d in graph.nodes(data=True) if d.get("object_type") in ROAD_NODE_TYPES
        ]
        H = nx.DiGraph()
        for n in road_nodes:
            H.add_node(n, **graph.nodes[n])

        for u, v, d in graph.edges(data=True):
            if d.get("edge_type") != "road" or u not in H or v not in H:
                continue
            x = float(d.get("length_m", float("nan")))
            if not math.isfinite(x) or x <= 0:
                continue
            weight_cm = max(1, round(x * 100))
            if not H.has_edge(u, v) or weight_cm < H[u][v]["weight_cm"]:
                H.add_edge(u, v, weight_cm=weight_cm)

        return H

    @classmethod
    def _intersection_route_fraction(
        cls, graph: nx.Graph, routes: List[Dict[str, Any]]
    ) -> Dict[str, Optional[float]]:
        """
        Вычисляет долю найденных направленных складских маршрутов, проходящих через каждый перекрёсток.
        """
        ix = [str(n) for n, d in graph.nodes(data=True) if d.get("object_type") == "intersection"]
        if not ix:
            return {}

        road_node_ids = {
            str(n) for n, d in graph.nodes(data=True) if d.get("object_type") in ROAD_NODE_TYPES
        }
        found_routes = [r for r in routes if isinstance(r, dict) and r.get("status") == "found"]
        if not found_routes:
            return {v: None for v in ix}

        ix_set = set(ix)
        visits: Counter[str] = Counter()
        for r in found_routes:
            path = r.get("node_path")
            if not isinstance(path, (list, tuple)) or not path:
                return {v: None for v in ix}
            path_ids = set(map(str, path))
            if not path_ids <= road_node_ids:
                return {v: None for v in ix}
            visits.update(path_ids & ix_set)

        total_found = len(found_routes)
        return {v: visits[v] / total_found for v in ix}

    @classmethod
    def _calculate_legacy_metrics(cls, log_graph: nx.Graph) -> List[MetricItem]:
        """
        Расчёт метрик прежнего логистического графа склад-склад (обратная совместимость).
        """
        metrics: List[MetricItem] = []

        simple_graph = nx.Graph()
        for node, data in log_graph.nodes(data=True):
            simple_graph.add_node(node, **data)

        for u, v, data in log_graph.edges(data=True):
            status_ab = data.get("route_status_ab")
            status_ba = data.get("route_status_ba")
            is_connected = (status_ab == "found") or (status_ba == "found")

            dist_ab = data.get("total_distance_ab_m")
            dist_ba = data.get("total_distance_ba_m")
            dist_candidates = [d for d in (dist_ab, dist_ba) if d is not None and d > 0]
            weight_m = min(dist_candidates) if dist_candidates else 1000.0

            if is_connected:
                if simple_graph.has_edge(u, v):
                    if weight_m < simple_graph[u][v].get("weight", float("inf")):
                        simple_graph[u][v]["weight"] = weight_m
                else:
                    simple_graph.add_edge(u, v, weight=weight_m)

        v_count = float(simple_graph.number_of_nodes())
        e_count = float(simple_graph.number_of_edges())

        metrics.append(MetricItem(name="vertex_count", value=v_count))
        metrics.append(MetricItem(name="edge_count", value=e_count))

        if v_count == 0:
            return metrics

        connected_components = list(nx.connected_components(simple_graph))
        p_count = float(len(connected_components))
        metrics.append(MetricItem(name="connected_components_count", value=p_count))

        isolated_nodes = list(nx.isolates(simple_graph))
        isolated_count = float(len(isolated_nodes))
        metrics.append(MetricItem(name="isolated_nodes_count", value=isolated_count))

        isolated_ratio = isolated_count / v_count if v_count > 0 else 0.0
        metrics.append(MetricItem(name="isolated_nodes_ratio", value=cls._safe_float(isolated_ratio)))

        beta_index = e_count / v_count if v_count > 0 else 0.0
        metrics.append(MetricItem(name="beta_index", value=cls._safe_float(beta_index)))

        if v_count > 2 and (2 * v_count - 5) > 0:
            alpha_val = (e_count - v_count + p_count) / (2 * v_count - 5)
            alpha_val = max(0.0, min(1.0, alpha_val))
        else:
            alpha_val = 0.0
        metrics.append(MetricItem(name="alpha_index", value=cls._safe_float(alpha_val)))

        if v_count > 2:
            gamma_val = e_count / (3 * (v_count - 2))
            gamma_val = max(0.0, min(1.0, gamma_val))
        else:
            gamma_val = 0.0
        metrics.append(MetricItem(name="gamma_index", value=cls._safe_float(gamma_val)))

        avg_degree = (2.0 * e_count) / v_count if v_count > 0 else 0.0
        metrics.append(MetricItem(name="avg_degree", value=cls._safe_float(avg_degree)))

        density = (2.0 * e_count) / (v_count * (v_count - 1.0)) if v_count > 1 else 0.0
        metrics.append(MetricItem(name="network_density", value=cls._safe_float(density)))

        edge_distances_km = [
            data.get("weight", 0.0) / 1000.0 for _, _, data in simple_graph.edges(data=True)
        ]
        if edge_distances_km:
            avg_dist = sum(edge_distances_km) / len(edge_distances_km)
            max_dist = max(edge_distances_km)
        else:
            avg_dist = 0.0
            max_dist = 0.0

        metrics.append(MetricItem(name="avg_edge_distance_km", value=cls._safe_float(avg_dist)))
        metrics.append(MetricItem(name="max_edge_distance_km", value=cls._safe_float(max_dist)))

        diameter_km = 0.0
        largest_cc_nodes = max(connected_components, key=len) if connected_components else set()
        if len(largest_cc_nodes) > 1:
            subgraph = simple_graph.subgraph(largest_cc_nodes)
            try:
                max_shortest = 0.0
                for _, target_dists in nx.all_pairs_dijkstra_path_length(subgraph, weight="weight"):
                    if target_dists:
                        local_max = max(target_dists.values())
                        if local_max > max_shortest:
                            max_shortest = local_max
                diameter_km = max_shortest / 1000.0
            except Exception:
                diameter_km = 0.0

        metrics.append(MetricItem(name="diameter_km", value=cls._safe_float(diameter_km)))

        routes = log_graph.graph.get("routes")
        if routes and isinstance(routes, list):
            total_r = float(len(routes))
            found_r = float(sum(1 for r in routes if isinstance(r, dict) and r.get("status") == "found"))
            metrics.append(MetricItem(name="total_routes_count", value=total_r))
            metrics.append(MetricItem(name="found_routes_count", value=found_r))
            found_ratio = found_r / total_r if total_r > 0 else 0.0
            metrics.append(MetricItem(name="found_routes_ratio", value=cls._safe_float(found_ratio)))

        return metrics

    @staticmethod
    def _safe_float(val: float) -> float:
        if val is None or not math.isfinite(val):
            return 0.0
        return round(float(val), 4)
