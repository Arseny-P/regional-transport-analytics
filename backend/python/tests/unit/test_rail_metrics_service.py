import os
import math
import unittest
import networkx as nx

from graph_service.config import config
from graph_service.domain.models import (
    TerritoryBounds,
    RailFacility,
    RailConnectionStatus,
    RailObjectType,
    RailNodeKind,
)
from graph_service.algorithms.rail_network_service import RailNetworkService
from graph_service.application.rail_metrics_service import RailMetricsService


class TestRailMetricsService(unittest.TestCase):
    """
    Тестирование сервиса расчёта показателей железнодорожного графа (RailMetricsService):
    5 показателей MVP, точный betweenness стрелок, расстояния между станциями с несколькими точками подключения.
    """

    def setUp(self):
        self._prev_offline = config.osm_offline_mode
        config.osm_offline_mode = True
        self.network_service = RailNetworkService(storage_dir="data")
        self.shushary_bbox = TerritoryBounds(
            min_lat=59.7950,
            min_lon=30.3850,
            max_lat=59.8240,
            max_lon=30.4410,
        )

    def tearDown(self):
        config.osm_offline_mode = self._prev_offline

    def test_shushary_benchmark_metrics(self):
        """
        Проверка расчёта метрик на эталонном графе Шушар.
        """
        _, G_simple = self.network_service.build_from_bbox(self.shushary_bbox)
        metrics = RailMetricsService.calculate_metrics(G_simple)

        by_name = {}
        for m in metrics:
            by_name.setdefault(m.name, []).append(m)

        # 1. total_rail_length_km
        self.assertIn("total_rail_length_km", by_name)
        self.assertEqual(len(by_name["total_rail_length_km"]), 1)
        self.assertAlmostEqual(by_name["total_rail_length_km"][0].value, 25.750071, places=3)
        self.assertIsNone(by_name["total_rail_length_km"][0].node_id)

        # 2. station_count (без станций = 0)
        self.assertIn("station_count", by_name)
        self.assertEqual(by_name["station_count"][0].value, 0.0)
        self.assertIsNone(by_name["station_count"][0].node_id)

        # 3. switch_count
        self.assertIn("switch_count", by_name)
        self.assertEqual(by_name["switch_count"][0].value, 36.0)
        self.assertIsNone(by_name["switch_count"][0].node_id)

        # 4. betweenness_centrality для всех 36 стрелок
        self.assertIn("betweenness_centrality", by_name)
        bc_metrics = by_name["betweenness_centrality"]
        self.assertEqual(len(bc_metrics), 36)
        for m in bc_metrics:
            self.assertIsNotNone(m.node_id)
            self.assertTrue(math.isfinite(m.value))
            self.assertGreaterEqual(m.value, 0.0)
            self.assertLessEqual(m.value, 1.0)

    def test_nearest_station_distance_with_multi_anchors(self):
        """
        Проверка расчёта расстояния между станциями с несколькими точками подключения:
        - путь ищется как минимум между всеми парами точек двух станций.
        - изолированная станция не получает искусственного нуля.
        """
        graph = nx.MultiGraph()
        # Линейная сеть: a1 --500m-- a2 --1000m-- b1 --500m-- b2
        graph.add_node("u_a1", object_type="rail_facility", node_kind="station", is_switch=False)
        graph.add_node("u_a2", object_type="rail_facility", node_kind="station", is_switch=False)
        graph.add_node("u_b1", object_type="rail_facility", node_kind="station", is_switch=False)
        graph.add_node("u_b2", object_type="rail_facility", node_kind="station", is_switch=False)
        graph.add_node("u_c1", object_type="rail_facility", node_kind="station", is_switch=False)  # изолированная станция C

        graph.add_edge("u_a1", "u_a2", length_m=500.0, segment_id="seg:1")
        graph.add_edge("u_a2", "u_b1", length_m=1000.0, segment_id="seg:2")
        graph.add_edge("u_b1", "u_b2", length_m=500.0, segment_id="seg:3")

        st_a = RailFacility(
            facility_id="st:A",
            name="Станция А",
            latitude=59.9,
            longitude=30.3,
            anchor_node_ids=["u_a1", "u_a2"],
            connection_status=RailConnectionStatus.CONNECTED.value,
        )
        st_b = RailFacility(
            facility_id="st:B",
            name="Станция Б",
            latitude=59.91,
            longitude=30.31,
            anchor_node_ids=["u_b1", "u_b2"],
            connection_status=RailConnectionStatus.CONNECTED.value,
        )
        st_c = RailFacility(
            facility_id="st:C",
            name="Станция В (изолированная)",
            latitude=59.95,
            longitude=30.35,
            anchor_node_ids=["u_c1"],
            connection_status=RailConnectionStatus.CONNECTED.value,
        )

        metrics = RailMetricsService.calculate_metrics(graph, facilities=[st_a, st_b, st_c])

        st_dist_metrics = {m.node_id: m.value for m in metrics if m.name == "nearest_station_distance_m"}

        # 1. Расстояние от А до Б должно быть min(1000, 1500, 2000) = 1000.0 м
        self.assertIn("st:A", st_dist_metrics)
        self.assertEqual(st_dist_metrics["st:A"], 1000.0)

        # 2. Расстояние от Б до А также 1000.0 м
        self.assertIn("st:B", st_dist_metrics)
        self.assertEqual(st_dist_metrics["st:B"], 1000.0)

        # 3. Изолированная станция C НЕ должна иметь метрики расстояния (никаких нулей!)
        self.assertNotIn("st:C", st_dist_metrics)

        # 4. station_count равен 3
        st_cnt = next(m.value for m in metrics if m.name == "station_count")
        self.assertEqual(st_cnt, 3.0)


if __name__ == "__main__":
    unittest.main()
