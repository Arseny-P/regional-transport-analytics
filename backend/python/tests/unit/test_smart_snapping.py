import unittest
import networkx as nx
from graph_service.domain import LogisticsNode, VerificationStatus
from graph_service.algorithms import FacilityService


class TestSmartSnapping(unittest.TestCase):
    def setUp(self):
        self.facility_service = FacilityService()

    def test_filter_disconnected_islands(self):
        """
        Проверяет, что изолированные 1-2 узловые островки дорог игнорируются,
        и объект привязывается к основной связной компоненте дорожной сети.
        """
        G = nx.MultiDiGraph()
        G.graph["crs"] = "epsg:4326"

        # Изолированный островок (2 узла), координаты очень близко к объекту (59.9001, 30.3001)
        G.add_node(1, x=30.3001, y=59.9001)
        G.add_node(2, x=30.3002, y=59.9002)
        G.add_edge(1, 2, key=0, length=10)
        G.add_edge(2, 1, key=0, length=10)

        # Основная связная сеть (узлы 10..15), координаты чуть дальше (59.9010, 30.3010)
        main_nodes = [10, 11, 12, 13, 14, 15]
        for nid in main_nodes:
            G.add_node(nid, x=30.3010 + (nid - 10) * 0.001, y=59.9010)

        # Создаем кольцевой/решетчатый граф в основной сети
        for i in range(len(main_nodes)):
            u = main_nodes[i]
            v = main_nodes[(i + 1) % len(main_nodes)]
            G.add_edge(u, v, key=0, length=50)
            G.add_edge(v, u, key=0, length=50)

        # Логистический объект рядом с изолированным островком (59.9000, 30.3000)
        facility = LogisticsNode(
            id="fac_1",
            name="Тестовый склад",
            object_type="warehouse",
            latitude=59.9000,
            longitude=30.3000,
            region_ids=["ru-spb"],
            source_osm_ids=[],
            verification_status=VerificationStatus.VERIFIED.value
        )

        snapped = self.facility_service.snap_to_road_network(G, [facility], filter_disconnected=True)

        self.assertEqual(len(snapped), 1)
        # Объект должен быть привязан к основной сети (10..15), а не к изолированным узлам 1 или 2
        self.assertIn(snapped[0].nearest_osm_node, main_nodes)
        self.assertNotIn(snapped[0].nearest_osm_node, [1, 2])
        for acc in snapped[0].access_nodes:
            self.assertIn(acc, main_nodes)

    def test_one_way_dead_end_avoidance(self):
        """
        Проверяет, что при выборе основного узла предпочтение отдается
        сквозному перекрестку перед односторонним тупиком (sink/dead-end),
        даже если тупик геометрически ближе.
        """
        G = nx.MultiDiGraph()
        G.graph["crs"] = "epsg:4326"

        # Узел 1: тупик (въезд есть из 2, выезда нет: in_degree=1, out_degree=0)
        # Геометрически ближе всего к объекту (59.9001, 30.3000)
        G.add_node(1, x=30.3000, y=59.9001)

        # Узел 2: промежуточный
        G.add_node(2, x=30.3000, y=59.9003)

        # Узел 3 и 4: сквозной перекресток (in > 0, out > 0)
        # Находится чуть дальше (59.9004, 30.3000)
        G.add_node(3, x=30.3000, y=59.9004)
        G.add_node(4, x=30.3005, y=59.9004)

        # Ребра:
        # Из 3 в 2 и в 1 (одностороннее движение в тупик)
        G.add_edge(3, 2, key=0, length=20)
        G.add_edge(2, 1, key=0, length=20)

        # Двустороннее движение между 3 и 4 (сквозная улица)
        G.add_edge(3, 4, key=0, length=50)
        G.add_edge(4, 3, key=0, length=50)

        # Объект находится в (59.9000, 30.3000) - прямо у тупика 1 (~11 метров)
        facility = LogisticsNode(
            id="fac_2",
            name="Склад у тупика",
            object_type="distribution_center",
            latitude=59.9000,
            longitude=30.3000,
            region_ids=["ru-spb"],
            source_osm_ids=[],
            verification_status=VerificationStatus.VERIFIED.value
        )

        snapped = self.facility_service.snap_to_road_network(G, [facility], filter_disconnected=False)
        self.assertEqual(len(snapped), 1)

        # Тупиковый узел 1 имеет штраф +100м, поэтому основным узлом должен стать узел со сквозным выездом (2 или 3)
        self.assertNotEqual(snapped[0].nearest_osm_node, 1, "Тупиковый sink-узел не должен выбираться основным узлом")
        # При этом узел 1 может присутствовать в access_nodes как физически близкая точка
        self.assertIn(snapped[0].nearest_osm_node, [2, 3])

    def test_perpendicular_edge_splitting(self):
        """
        Проверяет, что объект напротив улицы врезается в ребро с созданием
        виртуального узла прямо на улице, а не тянется к перекрёстку в конце квартала.
        """
        G = nx.MultiDiGraph()
        G.graph["crs"] = "epsg:4326"

        # Длинная улица между двумя перекрёстками 1 и 2 (~1200м)
        G.add_node(1, x=30.000, y=59.000)
        G.add_node(2, x=30.020, y=59.000)
        G.add_edge(1, 2, key=0, length=1200, highway="residential")
        G.add_edge(2, 1, key=0, length=1200, highway="residential")

        # Добавим дополнительное кольцо для связности (более длинное, 1400м)
        G.add_node(3, x=30.010, y=59.005)
        G.add_edge(1, 3, key=0, length=700)
        G.add_edge(3, 2, key=0, length=700)

        # Объект стоит посередине квартала на удалении ~110 метров от улицы: (30.010, 59.001)
        # До перекрестков 1 и 2 расстояние около 600 метров.
        facility = LogisticsNode(
            id="fac_mid_street",
            name="Склад посреди улицы",
            object_type="warehouse",
            latitude=59.001,
            longitude=30.010,
            region_ids=["ru-spb"],
            source_osm_ids=[],
            verification_status=VerificationStatus.VERIFIED.value
        )

        snapped = self.facility_service.snap_to_road_network(G, [facility], filter_disconnected=False)
        self.assertEqual(len(snapped), 1)

        # Основным узлом должен стать виртуальный узел прямо на полотне дороги
        virt_node = snapped[0].nearest_osm_node
        self.assertGreaterEqual(virt_node, 9_000_000_000)
        self.assertTrue(G.nodes[virt_node].get("is_virtual"))
        self.assertAlmostEqual(snapped[0].osm_node_lat, 59.000, places=3)
        self.assertAlmostEqual(snapped[0].osm_node_lon, 30.010, places=3)
        # Плечо привязки перпендикулярно и составляет ~111 м, а не 600 м до угла
        self.assertLess(snapped[0].snap_distance_m, 200)

        # Проверяем, что виртуальный узел полноценно встроен в топологию графа
        path = nx.shortest_path(G, 1, virt_node, weight="length")
        self.assertEqual(path, [1, virt_node])
        path_through = nx.shortest_path(G, 1, 2, weight="length")
        self.assertIn(virt_node, path_through)

    def test_max_snap_distance_threshold(self):
        """
        Проверяет, что объекты дальше установленного порога (например, 500м в акватории)
        помечаются как изолированные и не получают доступ к дорожной сети.
        """
        G = nx.MultiDiGraph()
        G.graph["crs"] = "epsg:4326"

        # Дорога около (59.000, 30.000) - (59.000, 30.010)
        G.add_node(1, x=30.000, y=59.000)
        G.add_node(2, x=30.010, y=59.000)
        G.add_edge(1, 2, key=0, length=500)
        G.add_edge(2, 1, key=0, length=500)

        # 1. Близкий объект (~100м к северу)
        close_facility = LogisticsNode(
            id="close_hub",
            name="Близкий склад",
            object_type="warehouse",
            latitude=59.001,
            longitude=30.005,
        )

        # 2. Далекий объект в море (~700м к югу)
        far_facility = LogisticsNode(
            id="far_port_sea",
            name="Точка в заливе (Каботажная гавань)",
            object_type="port",
            latitude=58.993,
            longitude=30.005,
        )

        snapped = self.facility_service.snap_to_road_network(
            G, [close_facility, far_facility], filter_disconnected=False, max_snap_distance_m=500.0
        )

        self.assertEqual(len(snapped), 2)

        # Близкий объект успешно подключен
        self.assertFalse(snapped[0].is_isolated)
        self.assertGreater(len(snapped[0].access_nodes), 0)
        self.assertLess(snapped[0].snap_distance_m, 500.0)

        # Далекий морской объект изолирован
        self.assertTrue(snapped[1].is_isolated)
        self.assertEqual(len(snapped[1].access_nodes), 0)
        self.assertIsNone(snapped[1].nearest_osm_node)
        self.assertGreater(snapped[1].snap_distance_m, 500.0)
        self.assertIn("Превышен лимит расстояния", snapped[1].isolation_reason)


if __name__ == "__main__":
    unittest.main()
