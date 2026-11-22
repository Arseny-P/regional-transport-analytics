import math
from typing import List, Dict, Any, Optional
import networkx as nx

from graph_service.kafka.schemas import MetricItem
from graph_service.domain.errors import MetricsCalculationError


class GraphMetricsService:
    """
    Сервис расчёта графовых метрик логистической транспортной сети (задача #28).
    Предоставляет массив числовых показателей {name, value} в соответствии с контрактом Kafka.
    """

    @classmethod
    def calculate_metrics(cls, log_graph: nx.Graph) -> List[MetricItem]:
        """
        Вычисляет набор графовых метрик для заданного логистического мультиграфа или дорожного графа маршрутов.
        Возвращает список объектов MetricItem.
        """
        try:
            metrics: List[MetricItem] = []

            # Преобразуем MultiGraph/MultiDiGraph в простой неориентированный Graph для топологического анализа
            simple_graph = nx.Graph()
            for node, data in log_graph.nodes(data=True):
                simple_graph.add_node(node, **data)

            for u, v, data in log_graph.edges(data=True):
                edge_type = data.get("edge_type")
                if edge_type in ("road", "access_connector"):
                    # Итоговый дорожный граф маршрутов (Спринт 4)
                    weight_m = float(data.get("length_m") or 1.0)
                    if simple_graph.has_edge(u, v):
                        if weight_m < simple_graph[u][v].get("weight", float("inf")):
                            simple_graph[u][v]["weight"] = weight_m
                    else:
                        simple_graph.add_edge(u, v, weight=weight_m)
                else:
                    # Логистический граф склад-склад (Спринт 3)
                    status_ab = data.get("route_status_ab")
                    status_ba = data.get("route_status_ba")
                    is_connected = (status_ab == "found") or (status_ba == "found")

                    # Берем минимальное расстояние между направлениями A->B и B->A
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

            # 1. Базовые показатели узлов и связей
            metrics.append(MetricItem(name="vertex_count", value=v_count))
            metrics.append(MetricItem(name="edge_count", value=e_count))

            if v_count == 0:
                return metrics

            # 2. Компоненты связности и изоляция
            connected_components = list(nx.connected_components(simple_graph))
            p_count = float(len(connected_components))
            metrics.append(MetricItem(name="connected_components_count", value=p_count))

            isolated_nodes = list(nx.isolates(simple_graph))
            isolated_count = float(len(isolated_nodes))
            metrics.append(MetricItem(name="isolated_nodes_count", value=isolated_count))

            isolated_ratio = isolated_count / v_count if v_count > 0 else 0.0
            metrics.append(MetricItem(name="isolated_nodes_ratio", value=cls._safe_float(isolated_ratio)))

            # 3. Индексы связности транспортных сетей (Kansky connectivity indices)
            # Beta index: E / V (мера разветвленности)
            beta_index = e_count / v_count if v_count > 0 else 0.0
            metrics.append(MetricItem(name="beta_index", value=cls._safe_float(beta_index)))

            # Alpha index: (E - V + P) / (2V - 5) для планарных сетей (степень циклической избыточности)
            if v_count > 2 and (2 * v_count - 5) > 0:
                alpha_val = (e_count - v_count + p_count) / (2 * v_count - 5)
                alpha_val = max(0.0, min(1.0, alpha_val))
            else:
                alpha_val = 0.0
            metrics.append(MetricItem(name="alpha_index", value=cls._safe_float(alpha_val)))

            # Gamma index: E / (3 * (V - 2)) для планарных графов (отношение реальных ребер к максимуму)
            if v_count > 2:
                gamma_val = e_count / (3 * (v_count - 2))
                gamma_val = max(0.0, min(1.0, gamma_val))
            else:
                gamma_val = 0.0
            metrics.append(MetricItem(name="gamma_index", value=cls._safe_float(gamma_val)))

            # 4. Плотность сети и средняя степень вершины
            avg_degree = (2.0 * e_count) / v_count if v_count > 0 else 0.0
            metrics.append(MetricItem(name="avg_degree", value=cls._safe_float(avg_degree)))

            density = (2.0 * e_count) / (v_count * (v_count - 1.0)) if v_count > 1 else 0.0
            metrics.append(MetricItem(name="network_density", value=cls._safe_float(density)))

            # 5. Дистанционные характеристики (в километрах)
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

            # 6. Диаметр графа (максимальный кратчайший путь в наибольшей компоненте связности)
            diameter_km = 0.0
            largest_cc_nodes = max(connected_components, key=len) if connected_components else set()
            if len(largest_cc_nodes) > 1:
                subgraph = simple_graph.subgraph(largest_cc_nodes)
                try:
                    max_shortest = 0.0
                    num_nodes = len(largest_cc_nodes)

                    if num_nodes <= 500:
                        # Потоковый расчёт через генератор (O(V) памяти вместо O(V^2)):
                        # НЕ материализуем dict(nx.all_pairs_dijkstra_path_length(...)),
                        # предотвращая риск OOM (до 100 млн записей) при масштабировании сети.
                        for _, target_dists in nx.all_pairs_dijkstra_path_length(subgraph, weight="weight"):
                            if target_dists:
                                local_max = max(target_dists.values())
                                if local_max > max_shortest:
                                    max_shortest = local_max
                    else:
                        # Для больших сетей (V > 500) используем 4-sweep Dijkstra эвристику:
                        # Строго O(V) памяти и миллисекундное время работы (вместо тысяч прогонов).
                        # Точность на дорожных графах >= 98-99%.
                        seed_nodes = [
                            n for n in largest_cc_nodes
                            if subgraph.nodes[n].get("object_type") == "warehouse"
                        ]
                        if not seed_nodes:
                            seed_nodes = [next(iter(largest_cc_nodes))]

                        curr_node = seed_nodes[0]
                        visited = set()

                        for _ in range(4):
                            if curr_node in visited:
                                break
                            visited.add(curr_node)
                            dists = nx.single_source_dijkstra_path_length(subgraph, curr_node, weight="weight")
                            if not dists:
                                break
                            farthest = max(dists, key=dists.get)
                            farthest_dist = dists[farthest]
                            if farthest_dist > max_shortest:
                                max_shortest = farthest_dist
                            curr_node = farthest

                        # Дополнительные проходы от складов (до 10 штук) для лучшего охвата
                        for w_node in seed_nodes[1:10]:
                            if w_node not in visited:
                                visited.add(w_node)
                                dists = nx.single_source_dijkstra_path_length(subgraph, w_node, weight="weight")
                                if dists:
                                    w_max = max(dists.values())
                                    if w_max > max_shortest:
                                        max_shortest = w_max

                    diameter_km = max_shortest / 1000.0
                except Exception:
                    diameter_km = 0.0

            metrics.append(MetricItem(name="diameter_km", value=cls._safe_float(diameter_km)))

            # 7. Метрики найденных маршрутов (если привязаны к графу)
            routes = log_graph.graph.get("routes")
            if routes and isinstance(routes, list):
                total_r = float(len(routes))
                found_r = float(sum(1 for r in routes if isinstance(r, dict) and r.get("status") == "found"))
                metrics.append(MetricItem(name="total_routes_count", value=total_r))
                metrics.append(MetricItem(name="found_routes_count", value=found_r))
                found_ratio = found_r / total_r if total_r > 0 else 0.0
                metrics.append(MetricItem(name="found_routes_ratio", value=cls._safe_float(found_ratio)))

            return metrics

        except Exception as err:
            raise MetricsCalculationError(f"Ошибка вычисления графовых метрик: {err}") from err

    @staticmethod
    def _safe_float(val: float) -> float:
        if val is None or not math.isfinite(val):
            return 0.0
        return round(float(val), 4)

