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
        Проверяет, что при врезке в ребро:
        - виртуальный узел становится точкой подключения (snap_kind='virtual_node')
        - дальние концы ребра u и v (более 250м) НЕ добавляются в access_nodes как прямые коннекторы
        - независимый перекрёсток на соседней улице в пределах max_snap_distance_m может быть добавлен
        """
        G = nx.MultiDiGraph()
        G.graph["crs"] = "epsg:4326"
        G.add_node(1, x=30.0, y=59.0)
        G.add_node(2, x=30.02, y=59.0)
        G.add_edge(1, 2, key=0, length=1000)
        G.add_edge(2, 1, key=0, length=1000)

        # Кольцо связности (далекий узел 3, ~1000м)
        G.add_node(3, x=30.01, y=59.01)
        G.add_edge(1, 3, key=0, length=600)
        G.add_edge(3, 2, key=0, length=600)

        # Склад посередине улицы (1, 2): удаление до полотна дороги ~111 м, а до узлов 1 и 2 ~580 м
        w = LogisticsNode(id="w_mid", name="Склад посреди улицы", object_type="warehouse", latitude=59.001, longitude=30.01)
        snapped = self.facility_service.snap_to_road_network(G, [w], filter_disconnected=False, max_snap_distance_m=250.0)

        node = snapped[0]
        self.assertEqual(node.snap_kind, "virtual_node")
        self.assertGreaterEqual(node.nearest_osm_node, 9_000_000_000)
        self.assertIn(node.nearest_osm_node, node.access_nodes)

        # Дальние узлы 1 и 2 (580м > 250м) не должны попадать в access_nodes
        self.assertNotIn(1, node.access_nodes)
        self.assertNotIn(2, node.access_nodes)

    def test_routing_traverses_road_and_prevents_distant_access_connector_bypass(self):
        """
        Проверяет замечание код-ревью:
        При маршрутизации от склада посреди улицы к другому складу на перекрестке 2
        маршрут ОБЯЗАН проходить по реальному дорожному полотну [virt_node, 2],
        а не перепрыгивать напрямую через прямой access_connector склад->2 в обход дороги.
        """
        from graph_service.algorithms.logistics_graph_service import LogisticsGraphService

        G = nx.MultiDiGraph()
        G.graph["crs"] = "epsg:4326"
        G.add_node(1, x=30.0, y=59.0)
        G.add_node(2, x=30.02, y=59.0)
        G.add_edge(1, 2, key=0, length=1000.0)
        G.add_edge(2, 1, key=0, length=1000.0)

        w1 = LogisticsNode(id="W1", name="Склад посередине", object_type="warehouse", latitude=59.0005, longitude=30.01)
        w2 = LogisticsNode(id="W2", name="Склад на востоке", object_type="warehouse", latitude=59.0005, longitude=30.02)

        snapped = self.facility_service.snap_to_road_network(G, [w1, w2], filter_disconnected=False, max_snap_distance_m=250.0)
        w1_snapped, w2_snapped = snapped[0], snapped[1]

        virt_node = w1_snapped.nearest_osm_node
        self.assertGreaterEqual(virt_node, 9_000_000_000)

        log_service = LogisticsGraphService()
        res = log_service._calculate_best_route(
            road_graph=G,
            start_nodes=w1_snapped.access_nodes,
            end_nodes=w2_snapped.access_nodes,
            origin_coords=(w1.longitude, w1.latitude),
            dest_coords=(w2.longitude, w2.latitude),
        )

        self.assertEqual(res["status"], "found")
        # Маршрут должен начинаться в точке врезки virt_node и идти по дороге в узел 2
        self.assertEqual(res["access_u"], virt_node)
        self.assertIn(virt_node, res["path"])
        self.assertEqual(res["path"][0], virt_node)
        self.assertEqual(res["path"][-1], w2_snapped.nearest_osm_node)


if __name__ == "__main__":
    unittest.main()
