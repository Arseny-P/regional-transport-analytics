import unittest
import networkx as nx
from shapely.geometry import LineString

from graph_service.domain import LogisticsNode, RouteDetail, RouteStatus
from graph_service.algorithms import LogisticsGraphService
from graph_service.application import GraphSerializer


class TestAccessConnectorsStage3(unittest.TestCase):
    def setUp(self):
        self.service = LogisticsGraphService()

    def test_access_connector_separation_from_road_segments(self):
        """
        Проверяет, что служебные связи access_connector четко отделены
        от реальных дорожных участков (road).
        """
        # Дорожная сеть
        G = nx.MultiDiGraph()
        G.graph["crs"] = "epsg:4326"
        G.add_node(1, x=30.0, y=59.0, street_count=3)
        G.add_node(2, x=30.01, y=59.0, street_count=3)
        G.add_edge(1, 2, key=0, length=400, highway="primary", oneway=False, name="Главная ул.")
        G.add_edge(2, 1, key=0, length=400, highway="primary", oneway=False, name="Главная ул.")

        w1 = LogisticsNode(
            id="wh_1",
            name="Склад 1",
            object_type="warehouse",
            latitude=59.001,
            longitude=30.0,
            nearest_osm_node=1,
            snap_distance_m=111.0,
            access_nodes=[1],
        )
        w2 = LogisticsNode(
            id="wh_2",
            name="Склад 2",
            object_type="warehouse",
            latitude=59.001,
            longitude=30.01,
            nearest_osm_node=2,
            snap_distance_m=111.0,
            access_nodes=[2],
        )

        routes = [
            RouteDetail(
                origin_id="wh_1",
                destination_id="wh_2",
                status=RouteStatus.FOUND.value,
                road_length_m=400.0,
                total_length_m=622.0,
                node_path=[1, 2],
                edge_keys=[(1, 2, 0)],
                access_u=1,
                access_v=2,
                snap_origin_m=111.0,
                snap_dest_m=111.0,
            )
        ]

        route_graph = self.service.build_route_road_graph(G, [w1, w2], routes=routes)

        road_edges = []
        connector_edges = []
        for u, v, k, d in route_graph.edges(keys=True, data=True):
            if d.get("edge_type") == "road":
                road_edges.append((u, v, k, d))
            elif d.get("edge_type") == "access_connector":
                connector_edges.append((u, v, k, d))

        # Должен быть ровно 1 дорожный сегмент (1 -> 2)
        self.assertEqual(len(road_edges), 1)
        r_u, r_v, r_k, r_data = road_edges[0]
        self.assertEqual((r_u, r_v), ("1", "2"))
        self.assertEqual(r_data["highway"], "primary")
        self.assertEqual(r_data["name"], "Главная ул.")

        # Должны быть коннекторы последней мили
        self.assertGreater(len(connector_edges), 0)
        for _, _, _, c_data in connector_edges:
            self.assertEqual(c_data["edge_type"], "access_connector")
            self.assertIn(c_data["direction"], ["origin_to_road", "road_to_dest"])
            self.assertIn("wh_", c_data["warehouse_id"])

    def test_isolated_warehouses_preserved_with_reason(self):
        """
        Проверяет сохранение информации об изолированных складах с указанием причины:
        1. Склад в море / без дорог (не подключен к сети)
        2. Склад привязан к дороге, но нет маршрутов к другим складам
        """
        G = nx.MultiDiGraph()
        G.graph["crs"] = "epsg:4326"
        G.add_node(10, x=30.0, y=59.0, street_count=2)
        G.add_node(11, x=30.01, y=59.0, street_count=2)
        G.add_edge(10, 11, key=0, length=500)

        # Склад 1: привязан к 10
        w1 = LogisticsNode(
            id="w_connected_no_routes",
            name="Склад у дороги без маршрутов",
            object_type="warehouse",
            latitude=59.0001,
            longitude=30.0,
            nearest_osm_node=10,
            snap_distance_m=11.0,
            access_nodes=[10],
        )

        # Склад 2: изолирован из-за расстояния
        w2 = LogisticsNode(
            id="w_island",
            name="Склад на острове",
            object_type="warehouse",
            latitude=58.5,
            longitude=30.0,
            nearest_osm_node=None,
            snap_distance_m=5000.0,
            is_isolated=True,
            isolation_reason="Превышен лимит расстояния до автодороги: 5000.0 м > 500.0 м",
        )

        # Передаем пустой список маршрутов (маршруты не найдены)
        route_graph = self.service.build_route_road_graph(G, [w1, w2], routes=[])

        # 1. Проверяем наличие обоих складов в графе
        self.assertIn("w_connected_no_routes", route_graph.nodes)
        self.assertIn("w_island", route_graph.nodes)

        node_w1 = route_graph.nodes["w_connected_no_routes"]
        node_w2 = route_graph.nodes["w_island"]

        self.assertTrue(node_w1["is_isolated"])
        self.assertIsNotNone(node_w1.get("isolation_reason"))
        self.assertEqual(node_w1["nearest_osm_node"], 10)

        self.assertTrue(node_w2["is_isolated"])
        self.assertIn("Превышен лимит расстояния", node_w2["isolation_reason"])
        self.assertIsNone(node_w2["nearest_osm_node"])

        # 2. Проверяем сериализацию через GraphSerializer
        serialized = GraphSerializer.serialize(route_graph)
        nodes_by_id = {n.id: n for n in serialized.nodes}

        self.assertTrue(nodes_by_id["w_connected_no_routes"].attributes["is_isolated"])
        self.assertIn("isolation_reason", nodes_by_id["w_connected_no_routes"].attributes)
        self.assertTrue(nodes_by_id["w_island"].attributes["is_isolated"])
        self.assertIn("isolation_reason", nodes_by_id["w_island"].attributes)

    def test_multiple_warehouses_connecting_to_same_road_node(self):
        """
        Проверяет, что когда несколько складов подключаются к одному дорожному узлу,
        каждый склад имеет свои отдельные ребра access_connector.
        """
        G = nx.MultiDiGraph()
        G.graph["crs"] = "epsg:4326"
        G.add_node(99, x=30.0, y=59.0, street_count=2)
        G.add_node(100, x=30.01, y=59.0, street_count=2)
        G.add_edge(99, 100, key=0, length=500)
        G.add_edge(100, 99, key=0, length=500)

        wA = LogisticsNode(id="whA", name="Склад А", object_type="warehouse", latitude=59.0001, longitude=30.0001, nearest_osm_node=99, snap_distance_m=12.0)
        wB = LogisticsNode(id="whB", name="Склад Б", object_type="warehouse", latitude=59.0002, longitude=30.0002, nearest_osm_node=99, snap_distance_m=24.0)

        routes = [
            RouteDetail(
                origin_id="whA",
                destination_id="whB",
                status=RouteStatus.FOUND.value,
                road_length_m=0.0,
                total_length_m=36.0,
                node_path=[99],
                edge_keys=[],
                access_u=99,
                access_v=99,
                snap_origin_m=12.0,
                snap_dest_m=24.0,
            )
        ]

        route_graph = self.service.build_route_road_graph(G, [wA, wB], routes=routes)

        # Проверяем коннекторы для whA (выход на дорожный узел 99)
        out_A = route_graph.get_edge_data("whA", "99", "access_out")
        self.assertIsNotNone(out_A)
        self.assertEqual(out_A["edge_type"], "access_connector")
        self.assertEqual(out_A["warehouse_id"], "whA")

        # Проверяем коннекторы для whB (вход с дорожного узла 99)
        in_B = route_graph.get_edge_data("99", "whB", "access_in")
        self.assertIsNotNone(in_B)
        self.assertEqual(in_B["edge_type"], "access_connector")
        self.assertEqual(in_B["warehouse_id"], "whB")

        # Коннекторы полностью разделены
        self.assertNotEqual(out_A["warehouse_id"], in_B["warehouse_id"])


if __name__ == "__main__":
    unittest.main()
