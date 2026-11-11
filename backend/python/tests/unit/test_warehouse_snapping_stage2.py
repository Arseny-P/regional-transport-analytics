import unittest
import networkx as nx
from graph_service.domain import LogisticsNode, VerificationStatus
from graph_service.algorithms import FacilityService


class TestWarehouseSnappingStage2(unittest.TestCase):
    def setUp(self):
        self.facility_service = FacilityService()

    def test_invalid_or_missing_coordinates_isolated(self):
        """
        Проверяет, что склады с отсутствующими или некорректными координатами
        не ломают сервис и корректно помечаются как изолированные с указанием причины.
        """
        G = nx.MultiDiGraph()
        G.graph["crs"] = "epsg:4326"
        G.add_node(1, x=30.0, y=59.0)
        G.add_node(2, x=30.01, y=59.0)
        G.add_edge(1, 2, key=0, length=500)
        G.add_edge(2, 1, key=0, length=500)

        nodes = [
            LogisticsNode(
                id="w_none_coords",
                name="Склад без координат",
                object_type="warehouse",
                latitude=None,  # type: ignore
                longitude=30.0,
            ),
            LogisticsNode(
                id="w_invalid_lat",
                name="Склад с некорректной широтой",
                object_type="warehouse",
                latitude=120.0,
                longitude=30.0,
            ),
            LogisticsNode(
                id="w_valid",
                name="Валидный склад",
                object_type="warehouse",
                latitude=59.001,
                longitude=30.005,
            ),
        ]

        snapped = self.facility_service.snap_to_road_network(G, nodes, filter_disconnected=False)
        self.assertEqual(len(snapped), 3)

        by_id = {n.id: n for n in snapped}
        # w_none_coords
        self.assertTrue(by_id["w_none_coords"].is_isolated)
        self.assertIsNone(by_id["w_none_coords"].nearest_osm_node)
        self.assertEqual(by_id["w_none_coords"].snap_kind, "unconnected")
        self.assertIn("некорректны координаты", by_id["w_none_coords"].isolation_reason)

        # w_invalid_lat
        self.assertTrue(by_id["w_invalid_lat"].is_isolated)
        self.assertIsNone(by_id["w_invalid_lat"].nearest_osm_node)
        self.assertEqual(by_id["w_invalid_lat"].snap_kind, "unconnected")

        # w_valid
        self.assertFalse(by_id["w_valid"].is_isolated)
        self.assertIsNotNone(by_id["w_valid"].nearest_osm_node)
        self.assertIn(by_id["w_valid"].snap_kind, ["virtual_node", "osm_node"])

    def test_snap_report_and_summary_generation(self):
        """
        Проверяет формирование отчета get_snap_report и сводки get_snap_summary.
        """
        G = nx.MultiDiGraph()
        G.graph["crs"] = "epsg:4326"
        G.add_node(1, x=30.0, y=59.0)
        G.add_node(2, x=30.01, y=59.0)
        G.add_edge(1, 2, key=0, length=500)
        G.add_edge(2, 1, key=0, length=500)

        nodes = [
            LogisticsNode(
                id="w1",
                name="Склад 1",
                object_type="warehouse",
                latitude=59.001,
                longitude=30.005,
            ),
            LogisticsNode(
                id="w_far",
                name="Далекий склад",
                object_type="warehouse",
                latitude=59.05,
                longitude=30.005,
            ),
        ]

        snapped = self.facility_service.snap_to_road_network(G, nodes, filter_disconnected=False, max_snap_distance_m=500.0)
        
        # 1. Проверяем get_snap_report
        report = FacilityService.get_snap_report(snapped)
        self.assertEqual(len(report), 2)
        r1 = next(r for r in report if r["warehouse_id"] == "w1")
        r_far = next(r for r in report if r["warehouse_id"] == "w_far")

        self.assertFalse(r1["is_isolated"])
        self.assertIsNotNone(r1["nearest_osm_node"])
        self.assertGreater(r1["options_count"], 0)
        self.assertIn(r1["snap_kind"], ["virtual_node", "osm_node"])

        self.assertTrue(r_far["is_isolated"])
        self.assertIsNone(r_far["nearest_osm_node"])
        self.assertEqual(r_far["options_count"], 0)
        self.assertEqual(r_far["snap_kind"], "unconnected")
        self.assertIn("Превышен лимит расстояния", r_far["isolation_reason"])

        # 2. Проверяем get_snap_summary
        summary = FacilityService.get_snap_summary(snapped)
        self.assertEqual(summary["total_warehouses"], 2)
        self.assertEqual(summary["connected_count"], 1)
        self.assertEqual(summary["isolated_count"], 1)
        self.assertEqual(summary["unique_primary_nodes"], 1)
        self.assertGreater(summary["avg_snap_distance_m"], 0.0)

    def test_multiple_warehouses_shared_snap_node(self):
        """
        Проверяет, что несколько складов могут подключаться к одной и той же точке,
        сохраняя свои уникальные ID, расстояния и фиксируя общие направления.
        """
        G = nx.MultiDiGraph()
        G.graph["crs"] = "epsg:4326"
        G.add_node(100, x=30.0, y=59.0)
        G.add_node(200, x=30.01, y=59.0)
        G.add_edge(100, 200, key=0, length=500)
        G.add_edge(200, 100, key=0, length=500)

        # Два склада в непосредственной близости от узла 100 (< 8м от перекрестка)
        wA = LogisticsNode(id="wA", name="Склад A", object_type="warehouse", latitude=59.00005, longitude=30.00005)
        wB = LogisticsNode(id="wB", name="Склад B", object_type="warehouse", latitude=59.00006, longitude=30.00008)

        snapped = self.facility_service.snap_to_road_network(G, [wA, wB], filter_disconnected=False)
        self.assertEqual(len(snapped), 2)
        self.assertEqual(snapped[0].nearest_osm_node, snapped[1].nearest_osm_node)

        summary = FacilityService.get_snap_summary(snapped)
        self.assertEqual(summary["connected_count"], 2)
        self.assertEqual(summary["unique_primary_nodes"], 1)
        # 2 склада на одном узле дают 2 * (2 - 1) = 2 направления
        self.assertEqual(summary["shared_primary_node_directions"], 2)

    def test_multiple_access_options_on_edge_split(self):
        """
        Проверяет, что при врезке в ребро виртуальный узел становится основным,
        а смежные дорожные узлы u и v добавляются как альтернативные варианты (access_nodes).
        """
        G = nx.MultiDiGraph()
        G.graph["crs"] = "epsg:4326"
        G.add_node(1, x=30.0, y=59.0)
        G.add_node(2, x=30.02, y=59.0)
        G.add_edge(1, 2, key=0, length=1000)
        G.add_edge(2, 1, key=0, length=1000)

        # Кольцо связности
        G.add_node(3, x=30.01, y=59.01)
        G.add_edge(1, 3, key=0, length=600)
        G.add_edge(3, 2, key=0, length=600)

        # Склад посередине улицы (1, 2)
        w = LogisticsNode(id="w_mid", name="Склад посреди улицы", object_type="warehouse", latitude=59.001, longitude=30.01)
        snapped = self.facility_service.snap_to_road_network(G, [w], filter_disconnected=False)

        node = snapped[0]
        self.assertEqual(node.snap_kind, "virtual_node")
        self.assertGreaterEqual(node.nearest_osm_node, 9_000_000_000)
        # В access_nodes должен быть не только виртуальный узел, но и исходные узлы 1 и 2
        self.assertIn(node.nearest_osm_node, node.access_nodes)
        self.assertIn(1, node.access_nodes)
        self.assertIn(2, node.access_nodes)
        self.assertGreaterEqual(len(node.access_nodes), 3)


if __name__ == "__main__":
    unittest.main()
