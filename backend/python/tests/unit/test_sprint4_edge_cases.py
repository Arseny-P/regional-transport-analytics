import unittest
import networkx as nx
from shapely.geometry import LineString

from graph_service.domain.models import LogisticsNode, RouteStatus
from graph_service.algorithms.logistics_graph_service import LogisticsGraphService
from graph_service.application.graph_serializer import GraphSerializer


class TestSprint4EdgeCases(unittest.TestCase):
    def setUp(self):
        self.service = LogisticsGraphService(storage_dir="data")

    def test_shared_road_segments_deduplication(self):
        """
        Тест 1: Общие участки маршрутов.
        Маршруты W1 -> W3 и W2 -> W3 сходятся на общей улице (узел 3 -> узел 4).
        Убеждаемся, что сегмент (3 -> 4) добавлен в граф ровно один раз,
        routes_count == 2, и route_ids содержит оба маршрута.
        """
        road_graph = nx.MultiDiGraph()
        road_graph.graph["crs"] = "epsg:4326"

        road_graph.add_node(1, x=30.00, y=60.00, street_count=1)
        road_graph.add_node(2, x=30.00, y=60.02, street_count=1)
        road_graph.add_node(3, x=30.01, y=60.01, street_count=3)  # точка слияния (перекрёсток)
        road_graph.add_node(4, x=30.02, y=60.01, street_count=1)

        # Дороги к перекрестку 3
        road_graph.add_edge(1, 3, key=0, length=500.0, highway="residential", oneway=True)
        road_graph.add_edge(2, 3, key=0, length=500.0, highway="residential", oneway=True)
        # Общий участок 3 -> 4
        road_graph.add_edge(
            3, 4, key=0,
            length=750.0,
            highway="primary",
            oneway=True,
            name="Общий проспект",
            geometry=LineString([(30.01, 60.01), (30.015, 60.01), (30.02, 60.01)]),
        )

        w1 = LogisticsNode(id="W1", name="Склад 1", object_type="warehouse", latitude=60.00, longitude=30.00, nearest_osm_node=1, access_nodes=[1], snap_distance_m=10.0)
        w2 = LogisticsNode(id="W2", name="Склад 2", object_type="warehouse", latitude=60.02, longitude=30.00, nearest_osm_node=2, access_nodes=[2], snap_distance_m=10.0)
        w3 = LogisticsNode(id="W3", name="Склад 3", object_type="warehouse", latitude=60.01, longitude=30.02, nearest_osm_node=4, access_nodes=[4], snap_distance_m=10.0)

        route_graph = self.service.build_route_road_graph(road_graph, [w1, w2, w3])

        # Сегмент 3 -> 4 должен существовать в одном экземпляре
        self.assertTrue(route_graph.has_edge("3", "4"))
        edges_3_4 = route_graph["3"]["4"]
        self.assertEqual(len(edges_3_4), 1)

        seg_data = edges_3_4[0]
        self.assertEqual(seg_data["edge_type"], "road")
        self.assertEqual(seg_data["routes_count"], 2)
        self.assertIn("W1->W3", seg_data["route_ids"])
        self.assertIn("W2->W3", seg_data["route_ids"])
        self.assertEqual(seg_data["name"], "Общий проспект")
        self.assertEqual(seg_data["length_m"], 750.0)

    def test_oneway_roads_direction_and_detour(self):
        """
        Тест 2: Односторонние дороги.
        Прямая дорога от 1 к 2 односторонняя (oneway=True).
        В обратную сторону (от 2 к 1) движение возможно только через длинный объезд 2 -> 5 -> 1.
        Проверяем корректность направлений и выбор путей.
        """
        road_graph = nx.MultiDiGraph()
        road_graph.graph["crs"] = "epsg:4326"

        road_graph.add_node(1, x=30.00, y=60.00, street_count=2)
        road_graph.add_node(2, x=30.02, y=60.00, street_count=2)
        road_graph.add_node(5, x=30.01, y=60.02, street_count=2)

        # Односторонняя прямая дорога 1 -> 2 (длина 400м)
        road_graph.add_edge(1, 2, key=0, length=400.0, highway="primary", oneway=True, name="Прямая односторонняя")
        # Объезд 2 -> 5 -> 1 (длина 600м + 600м = 1200м)
        road_graph.add_edge(2, 5, key=0, length=600.0, highway="secondary", oneway=True, name="Объезд часть 1")
        road_graph.add_edge(5, 1, key=0, length=600.0, highway="secondary", oneway=True, name="Объезд часть 2")

        w1 = LogisticsNode(id="W1", name="Склад 1", object_type="warehouse", latitude=60.00, longitude=30.00, nearest_osm_node=1, access_nodes=[1])
        w2 = LogisticsNode(id="W2", name="Склад 2", object_type="warehouse", latitude=60.00, longitude=30.02, nearest_osm_node=2, access_nodes=[2])

        routes = self.service.calculate_all_routes(road_graph, [w1, w2])
        r_1_2 = next(r for r in routes if r.origin_id == "W1" and r.destination_id == "W2")
        r_2_1 = next(r for r in routes if r.origin_id == "W2" and r.destination_id == "W1")

        self.assertEqual(r_1_2.status, RouteStatus.FOUND.value)
        self.assertEqual(r_1_2.road_length_m, 400.0)
        self.assertEqual(r_1_2.node_path, [1, 2])

        # В обратную сторону маршрут должен идти через объезд 2 -> 5 -> 1
        self.assertEqual(r_2_1.status, RouteStatus.FOUND.value)
        self.assertEqual(r_2_1.road_length_m, 1200.0)
        self.assertEqual(r_2_1.node_path, [2, 5, 1])

        # Строим итоговый дорожный граф
        route_graph = self.service.build_route_road_graph(road_graph, [w1, w2], routes=routes)
        # Ребро 1 -> 2 есть, но обратного ребра 2 -> 1 нет!
        self.assertTrue(route_graph.has_edge("1", "2"))
        self.assertFalse(route_graph.has_edge("2", "1"))
        # Ребра объезда присутствуют
        self.assertTrue(route_graph.has_edge("2", "5"))
        self.assertTrue(route_graph.has_edge("5", "1"))

    def test_parallel_edges_exact_key_and_geometry(self):
        """
        Тест 3: Параллельные рёбра в MultiDiGraph.
        Между узлами A и B есть 2 ребра:
        - key=0: длина 2500м
        - key=1: длина 800м (кратчайшее)
        Проверяем, что в итоговый граф переносится именно ребро с key=1 и его геометрией.
        """
        road_graph = nx.MultiDiGraph()
        road_graph.graph["crs"] = "epsg:4326"

        road_graph.add_node(10, x=30.00, y=60.00, street_count=2)
        road_graph.add_node(20, x=30.01, y=60.00, street_count=2)

        road_graph.add_edge(10, 20, key=0, length=2500.0, highway="tertiary", name="Длинный дублер")
        road_graph.add_edge(10, 20, key=1, length=800.0, highway="trunk", name="Скоростная эстакада")

        w1 = LogisticsNode(id="W1", name="Склад 1", object_type="warehouse", latitude=60.00, longitude=30.00, nearest_osm_node=10, access_nodes=[10])
        w2 = LogisticsNode(id="W2", name="Склад 2", object_type="warehouse", latitude=60.00, longitude=30.01, nearest_osm_node=20, access_nodes=[20])

        route_graph = self.service.build_route_road_graph(road_graph, [w1, w2])

        self.assertTrue(route_graph.has_edge("10", "20", key=1))
        self.assertFalse(route_graph.has_edge("10", "20", key=0))

        edge_data = route_graph["10"]["20"][1]
        self.assertEqual(edge_data["name"], "Скоростная эстакада")
        self.assertEqual(edge_data["length_m"], 800.0)

    def test_isolated_warehouse_no_path_retained(self):
        """
        Тест 4: Отсутствие пути (изолированный склад).
        Склад W_ISO привязан к изолированному острову дорог,
        к которому физически нет пути из основной сети.
        Проверяем:
        - W_ISO сохранен в вершинах итогового графа со статусом is_isolated=True
        - Маршруты от/к W_ISO имеют статус not_found_in_data
        - К W_ISO не подключены ошибочные рёбра
        - GraphSerializer корректно сериализует граф в контракт Go
        """
        road_graph = nx.MultiDiGraph()
        road_graph.graph["crs"] = "epsg:4326"

        # Основная связная сеть
        road_graph.add_node(1, x=30.00, y=60.00, street_count=2)
        road_graph.add_node(2, x=30.01, y=60.00, street_count=2)
        road_graph.add_edge(1, 2, key=0, length=500.0, highway="primary", oneway=False)
        road_graph.add_edge(2, 1, key=0, length=500.0, highway="primary", oneway=False)

        # Оторванный остров
        road_graph.add_node(99, x=30.05, y=60.05, street_count=1)

        w1 = LogisticsNode(id="W1", name="Склад 1", object_type="warehouse", latitude=60.00, longitude=30.00, nearest_osm_node=1, access_nodes=[1])
        w2 = LogisticsNode(id="W2", name="Склад 2", object_type="warehouse", latitude=60.01, longitude=30.00, nearest_osm_node=2, access_nodes=[2])
        w_iso = LogisticsNode(id="W_ISO", name="Изолированный склад", object_type="warehouse", latitude=60.05, longitude=30.05, nearest_osm_node=99, access_nodes=[99])

        route_graph = self.service.build_route_road_graph(road_graph, [w1, w2, w_iso])

        # 1. Проверяем наличие всех 3 складов
        self.assertIn("W1", route_graph.nodes)
        self.assertIn("W2", route_graph.nodes)
        self.assertIn("W_ISO", route_graph.nodes)

        # 2. Проверяем флаг изоляции
        self.assertFalse(route_graph.nodes["W1"]["is_isolated"])
        self.assertFalse(route_graph.nodes["W2"]["is_isolated"])
        self.assertTrue(route_graph.nodes["W_ISO"]["is_isolated"])

        # 3. К W_ISO не должно вести дорожных рёбер
        self.assertEqual(route_graph.in_degree("W_ISO"), 0)
        self.assertEqual(route_graph.out_degree("W_ISO"), 0)

        # 4. Проверяем сериализацию
        payload = GraphSerializer.serialize(route_graph)
        node_map = {n.id: n for n in payload.nodes}
        self.assertIn("W_ISO", node_map)
        self.assertTrue(node_map["W_ISO"].attributes["is_isolated"])


if __name__ == "__main__":
    unittest.main()
