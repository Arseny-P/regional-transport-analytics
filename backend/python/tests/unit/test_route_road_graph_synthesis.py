import unittest
import networkx as nx
from shapely.geometry import LineString

from graph_service.domain.models import LogisticsNode, RouteStatus
from graph_service.algorithms.logistics_graph_service import LogisticsGraphService


class TestRouteRoadGraphSynthesis(unittest.TestCase):
    def setUp(self):
        self.service = LogisticsGraphService(storage_dir="data")

        # Создаем синтетическую дорожную сеть:
        # Узлы: 1, 2, 3, 4, 5, 99 (неиспользуемый узел)
        # 2 — перекрёсток (степень >= 3, street_count = 3)
        # 3 — промежуточный узел (street_count = 2)
        self.road_graph = nx.MultiDiGraph()
        self.road_graph.graph["crs"] = "epsg:4326"

        self.road_graph.add_node(1, x=30.00, y=60.00, street_count=1)
        self.road_graph.add_node(2, x=30.01, y=60.00, street_count=3)  # перекрёсток
        self.road_graph.add_node(3, x=30.02, y=60.00, street_count=2)  # обычный road_node
        self.road_graph.add_node(4, x=30.03, y=60.00, street_count=1)
        self.road_graph.add_node(5, x=30.01, y=60.01, street_count=1)  # боковое ответвление от 2
        self.road_graph.add_node(99, x=30.09, y=60.09, street_count=1)  # изолированный узел

        # Сегменты дорог
        self.road_graph.add_edge(1, 2, key=0, length=400.0, highway="secondary", oneway=True)
        self.road_graph.add_edge(2, 3, key=0, length=500.0, highway="primary", oneway=False)
        self.road_graph.add_edge(3, 2, key=0, length=500.0, highway="primary", oneway=False)
        self.road_graph.add_edge(3, 4, key=0, length=300.0, highway="secondary", oneway=True)
        self.road_graph.add_edge(2, 5, key=0, length=200.0, highway="residential", oneway=False)
        self.road_graph.add_edge(5, 2, key=0, length=200.0, highway="residential", oneway=False)
        self.road_graph.add_edge(99, 99, key=0, length=100.0, highway="service")

        # Склады:
        # Склад W1 привязан к 1
        # Склад W2 привязан к 5
        # Склад W3 привязан к 4
        # Склад W_ISO привязан к 99 (нет проезда к 1-5)
        self.w1 = LogisticsNode(
            id="W1",
            name="Склад Запад",
            object_type="warehouse",
            latitude=60.001,
            longitude=29.999,
            nearest_osm_node=1,
            access_nodes=[1],
            snap_distance_m=80.0,
        )
        self.w2 = LogisticsNode(
            id="W2",
            name="Склад Север",
            object_type="warehouse",
            latitude=60.011,
            longitude=30.01,
            nearest_osm_node=5,
            access_nodes=[5],
            snap_distance_m=90.0,
        )
        self.w3 = LogisticsNode(
            id="W3",
            name="Склад Восток",
            object_type="terminal",
            latitude=60.001,
            longitude=30.031,
            nearest_osm_node=4,
            access_nodes=[4],
            snap_distance_m=70.0,
        )
        self.w_iso = LogisticsNode(
            id="W_ISO",
            name="Изолированный склад",
            object_type="warehouse",
            latitude=60.09,
            longitude=30.09,
            nearest_osm_node=99,
            access_nodes=[99],
            snap_distance_m=50.0,
        )

    def test_route_road_graph_synthesis_structure(self):
        """
        Проверяет построение итогового дорожного графа:
        - включение складов (включая изолированный)
        - включение только использованных дорожных узлов (узел 99 не включается в дорожные узлы маршрутов)
        - классификация перекрёстков (intersection vs road_node)
        - наличие коннекторов access_connector и дорог road
        """
        all_warehouses = [self.w1, self.w2, self.w3, self.w_iso]
        route_graph = self.service.build_route_road_graph(
            road_graph=self.road_graph,
            nodes=all_warehouses,
        )

        # 1. Проверяем вершины
        self.assertIn("W1", route_graph.nodes)
        self.assertIn("W2", route_graph.nodes)
        self.assertIn("W3", route_graph.nodes)
        self.assertIn("W_ISO", route_graph.nodes)

        # Изолированный склад отмечен
        self.assertTrue(route_graph.nodes["W_ISO"]["is_isolated"])
        self.assertFalse(route_graph.nodes["W1"]["is_isolated"])

        # Узел 2 должен быть 'intersection'
        self.assertIn("2", route_graph.nodes)
        self.assertEqual(route_graph.nodes["2"]["object_type"], "intersection")

        # Узел 3 должен быть 'road_node'
        self.assertIn("3", route_graph.nodes)
        self.assertEqual(route_graph.nodes["3"]["object_type"], "road_node")

        # Неиспользованный дорожный узел 99 НЕ должен попасть в road_node (хотя склад W_ISO есть)
        self.assertNotIn("99", route_graph.nodes)

        # 2. Проверяем типы рёбер
        edge_types = {d.get("edge_type") for _, _, _, d in route_graph.edges(keys=True, data=True)}
        self.assertIn("road", edge_types)
        self.assertIn("access_connector", edge_types)

        # 3. Проверяем дедупликацию и подсчет routes_count на общем участке (1 -> 2)
        # Маршрут W1 -> W2 идет через 1 -> 2
        # Маршрут W1 -> W3 идет через 1 -> 2 -> 3 -> 4
        # Сегмент 1 -> 2 используется как минимум 2 маршрутами!
        self.assertTrue(route_graph.has_edge("1", "2"))
        edge_1_2 = route_graph["1"]["2"][0]
        self.assertEqual(edge_1_2["edge_type"], "road")
        self.assertGreaterEqual(edge_1_2["routes_count"], 2)
        self.assertIn("W1->W2", edge_1_2["route_ids"])
        self.assertIn("W1->W3", edge_1_2["route_ids"])

        # 4. Проверяем метаданные маршрутов в .graph["routes"]
        self.assertIn("routes", route_graph.graph)
        routes = route_graph.graph["routes"]
        self.assertGreater(len(routes), 0)

        # 5. Сводка графа
        summary = self.service.get_route_road_graph_summary(route_graph)
        self.assertEqual(summary["warehouses_count"], 4)
        self.assertEqual(summary["isolated_warehouses_count"], 1)
        self.assertEqual(summary["intersections_count"], 1)  # узел 2


if __name__ == "__main__":
    unittest.main()
