import math
from typing import List, Dict, Any, Optional, Set
import networkx as nx

from graph_service.domain.models import (
    RailFacility,
    RailConnectionStatus,
)
from graph_service.kafka.schemas import MetricItem
from graph_service.domain.errors import MetricsCalculationError
from graph_service.algorithms.rail_network_service import RailNetworkService


class RailMetricsService:
    """
    Сервис расчёта согласованного набора железнодорожных метрик (Спринт 6):
    - Региональные показатели (node_id=None):
      1. total_rail_length_km: Сумма длин уникальных физических участков внутри территории, км.
      2. station_count: Количество подтвержденных станций, подключенных к сети.
      3. switch_count: Количество узлов с явным тегом railway=switch.
    - Показатели станций (node_id=facility_id):
      4. nearest_station_distance_m: Минимальное направленное расстояние по рельсам до другой станции.
    - Показатели стрелок (node_id=switch_id):
      5. betweenness_centrality: Посредничество по кратчайшим путям на направленной инфраструктуре.
    """

    @classmethod
    def calculate_metrics(
        cls,
        graph: nx.MultiGraph,
        facilities: Optional[List[RailFacility]] = None,
        routing_graph: Optional[nx.MultiDiGraph] = None,
    ) -> List[MetricItem]:
        """
        Вычисляет 5 согласованных показателей железнодорожного графа MVP.
        """
        try:
            metrics: List[MetricItem] = []
            facilities_list = (
                facilities
                if facilities is not None
                else graph.graph.get("facilities", [])
            )

            # -------------------------------------------------------------
            # 1. Региональные метрики (node_id = None)
            # -------------------------------------------------------------
            # 1.1 Общая физическая длина путей
            total_rail_m = sum(d.get("length_m", 0.0) for *_, d in graph.edges(data=True))
            metrics.append(
                MetricItem(
                    name="total_rail_length_km",
                    value=round(total_rail_m / 1000.0, 6),
                    node_id=None,
                )
            )

            # 1.2 Количество проверенных станций
            connected_stations = [
                f
                for f in facilities_list
                if f.connection_status == RailConnectionStatus.CONNECTED.value
                and len(f.anchor_node_ids) > 0
            ]
            unique_station_names = {f.name for f in connected_stations}
            metrics.append(
                MetricItem(
                    name="station_count",
                    value=float(len(unique_station_names)),
                    node_id=None,
                )
            )

            # 1.3 Количество размеченных стрелок
            switch_nodes = [
                n for n, d in graph.nodes(data=True) if d.get("is_switch") is True
            ]
            metrics.append(
                MetricItem(
                    name="switch_count",
                    value=float(len(switch_nodes)),
                    node_id=None,
                )
            )

            # -------------------------------------------------------------
            # Подготовка графов для маршрутизации и центральности
            # -------------------------------------------------------------
            if routing_graph is None:
                routing_graph = RailNetworkService.to_routing_graph(graph)

            centrality_graph = RailNetworkService.to_centrality_digraph(routing_graph)

            # -------------------------------------------------------------
            # 2. Метрики станций (node_id = facility_id)
            # -------------------------------------------------------------
            if len(connected_stations) >= 2:
                for s in connected_stations:
                    min_dist_to_other = float("inf")
                    for t in connected_stations:
                        if t.facility_id == s.facility_id or t.name == s.name:
                            continue

                        # Ищем кратчайший путь между любыми парами точек подключения s и t
                        for u in s.anchor_node_ids:
                            if u not in routing_graph:
                                continue
                            for v in t.anchor_node_ids:
                                if v not in routing_graph:
                                    continue
                                try:
                                    d = nx.shortest_path_length(
                                        routing_graph,
                                        source=u,
                                        target=v,
                                        weight="length_m",
                                    )
                                    if d < min_dist_to_other:
                                        min_dist_to_other = d
                                except (nx.NetworkXNoPath, nx.NodeNotFound):
                                    continue

                    # Выдаем метрику только если путь реально найден
                    if math.isfinite(min_dist_to_other):
                        metrics.append(
                            MetricItem(
                                name="nearest_station_distance_m",
                                value=round(float(min_dist_to_other), 6),
                                node_id=str(s.facility_id),
                            )
                        )

            # -------------------------------------------------------------
            # 3. Метрики стрелочных переводов (node_id = switch_id)
            # -------------------------------------------------------------
            if switch_nodes:
                n_nodes = centrality_graph.number_of_nodes()
                if n_nodes >= 3:
                    try:
                        bc = nx.betweenness_centrality(
                            centrality_graph,
                            weight="weight_cm",
                            normalized=True,
                            endpoints=False,
                        )
                    except Exception:
                        bc = {}
                else:
                    bc = {n: 0.0 for n in centrality_graph.nodes()}

                for sw in switch_nodes:
                    val = bc.get(sw, 0.0)
                    if math.isfinite(val):
                        metrics.append(
                            MetricItem(
                                name="betweenness_centrality",
                                value=round(float(val), 6),
                                node_id=str(sw),
                            )
                        )

            return metrics

        except Exception as err:
            raise MetricsCalculationError(f"Ошибка вычисления ЖД-метрик: {err}") from err
