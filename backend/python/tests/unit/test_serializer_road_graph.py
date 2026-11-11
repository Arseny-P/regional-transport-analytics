import unittest
import networkx as nx
from shapely.geometry import LineString

from graph_service.application.graph_serializer import GraphSerializer
from graph_service.kafka.schemas import GraphPayload


class TestSerializerRoadGraph(unittest.TestCase):
    def test_serialize_route_road_graph(self):
        """
        Проверяет сериализацию итогового дорожного графа маршрутов (Спринт 4):
        - вершины: склады, перекрестки, промежуточные узлы (object_type)
        - рёбра: дорожные сегменты и коннекторы (edge_type, routes_count)
        - строгий порядок координат [lon, lat]
        """
        graph = nx.MultiDiGraph()
        graph.graph["crs"] = "epsg:4326"

        # Вершины
        graph.add_node(
            "W1",
            name="Склад Запад",
            object_type="warehouse",
            longitude=29.98,
            latitude=60.01,
            is_isolated=False,
            snap_distance_m=45.5,
        )
        graph.add_node(
            "100",
            name="intersection_100",
            object_type="intersection",
            longitude=29.99,
            latitude=60.01,
            street_count=3,
        )
        graph.add_node(
            "200",
            name="road_node_200",
            object_type="road_node",
            longitude=30.01,
            latitude=60.02,
            street_count=2,
        )

        # Рёбра
        # 1. Коннектор
        geom_conn = LineString([(29.98, 60.01), (29.99, 60.01)])
        graph.add_edge(
            "W1",
            "100",
            key="access_out",
            id="conn_W1_100",
            edge_type="access_connector",
            length_m=45.5,
            geometry=geom_conn,
            routes_count=1,
            direction="origin_to_road",
        )

        # 2. Дорожный сегмент
        geom_road = LineString([(29.99, 60.01), (30.00, 60.015), (30.01, 60.02)])
        graph.add_edge(
            "100",
            "200",
            key=0,
            id="road_100_200_0",
            edge_type="road",
            length_m=1250.0,
            geometry=geom_road,
            routes_count=3,
            highway="primary",
            oneway=True,
            name="Главная магистраль",
        )

        payload: GraphPayload = GraphSerializer.serialize(graph)

        # 1. Проверка вершин
        self.assertEqual(len(payload.nodes), 3)
        node_map = {n.id: n for n in payload.nodes}

        self.assertIn("W1", node_map)
        self.assertEqual(node_map["W1"].position, [29.98, 60.01])
        self.assertEqual(node_map["W1"].attributes["object_type"], "warehouse")
        self.assertEqual(node_map["W1"].attributes["snap_distance_m"], 45.5)

        self.assertIn("100", node_map)
        self.assertEqual(node_map["100"].position, [29.99, 60.01])
        self.assertEqual(node_map["100"].attributes["object_type"], "intersection")
        self.assertEqual(node_map["100"].attributes["street_count"], 3)

        self.assertIn("200", node_map)
        self.assertEqual(node_map["200"].position, [30.01, 60.02])
        self.assertEqual(node_map["200"].attributes["object_type"], "road_node")

        # 2. Проверка рёбер
        self.assertEqual(len(payload.edges), 2)
        edge_map = {e.id: e for e in payload.edges}

        # Проверка коннектора
        self.assertIn("conn_W1_100", edge_map)
        conn = edge_map["conn_W1_100"]
        self.assertEqual(conn.source, "W1")
        self.assertEqual(conn.target, "100")
        self.assertIsNone(conn.segment_id)
        self.assertEqual(conn.attributes["edge_type"], "access_connector")
        self.assertEqual(conn.attributes["length_m"], 45.5)
        self.assertEqual(conn.geometry, [[29.98, 60.01], [29.99, 60.01]])

        # Проверка дорожного сегмента
        self.assertIn("road_100_200_0", edge_map)
        road = edge_map["road_100_200_0"]
        self.assertEqual(road.source, "100")
        self.assertEqual(road.target, "200")
        self.assertEqual(road.segment_id, "seg_100_200")
        self.assertEqual(road.attributes["edge_type"], "road")
        self.assertEqual(road.attributes["length_m"], 1250.0)
        self.assertEqual(road.attributes["routes_count"], 3)
        self.assertEqual(road.attributes["highway"], "primary")
        self.assertEqual(road.attributes["name"], "Главная магистраль")
        self.assertEqual(len(road.geometry), 3)
        self.assertEqual(road.geometry[0], [29.99, 60.01])
        self.assertEqual(road.geometry[-1], [30.01, 60.02])

        # 3. Проверка JSON сериализации
        payload_dict = payload.to_dict()
        self.assertIn("nodes", payload_dict)
        self.assertIn("edges", payload_dict)

        # Проверка наличия/отсутствия segment_id в словаре ребер
        edge_dict_map = {e["id"]: e for e in payload_dict["edges"]}
        self.assertNotIn("segment_id", edge_dict_map["conn_W1_100"])
        self.assertEqual(edge_dict_map["road_100_200_0"]["segment_id"], "seg_100_200")

    def test_segment_id_identical_for_both_directions(self):
        """
        Проверяет, что у двух направлений одного физического участка (u -> v и v -> u)
        значение segment_id строго одинаковое.
        """
        graph = nx.MultiDiGraph()
        graph.add_node("A", x=30.0, y=60.0)
        graph.add_node("B", x=30.1, y=60.1)

        graph.add_edge("A", "B", key=0, edge_type="road", id="road_A_B_0")
        graph.add_edge("B", "A", key=0, edge_type="road", id="road_B_A_0")

        payload = GraphSerializer.serialize(graph)
        edge_dict = {e.id: e for e in payload.edges}

        self.assertEqual(edge_dict["road_A_B_0"].segment_id, "seg_A_B")
        self.assertEqual(edge_dict["road_B_A_0"].segment_id, "seg_A_B")
        self.assertEqual(edge_dict["road_A_B_0"].segment_id, edge_dict["road_B_A_0"].segment_id)

    def test_parallel_edges_mismatched_keys_and_osmid_segment_ids(self):
        """
        Проверяет сценарий из ревью: в MultiDiGraph ключи k обратных направлений не обязаны совпадать.
        Например:
        - Дорога A (100м, osmid 111): A -> B имеет k=0, а B -> A имеет k=1.
        - Дорога B (200м, osmid 222): A -> B имеет k=1, а B -> A имеет k=0.
        
        Оба направления дороги A должны получить одинаковый segment_id.
        Оба направления дороги B должны получить одинаковый segment_id.
        При этом дороги A и B должны получить разные segment_id (без ошибочной склейки).
        """
        graph = nx.MultiDiGraph()
        graph.add_node("1", x=30.0, y=60.0)
        graph.add_node("2", x=30.1, y=60.1)

        # Дорога A (100м)
        graph.add_edge("1", "2", key=0, edge_type="road", id="road_A_fwd", length_m=100.0, osmid=111)
        graph.add_edge("2", "1", key=1, edge_type="road", id="road_A_rev", length_m=100.0, osmid=111)

        # Дорога B (200м)
        graph.add_edge("1", "2", key=1, edge_type="road", id="road_B_fwd", length_m=200.0, osmid=222)
        graph.add_edge("2", "1", key=0, edge_type="road", id="road_B_rev", length_m=200.0, osmid=222)

        payload = GraphSerializer.serialize(graph)
        edge_dict = {e.id: e for e in payload.edges}

        # Направления дороги A совпадают между собой
        self.assertEqual(edge_dict["road_A_fwd"].segment_id, edge_dict["road_A_rev"].segment_id)
        # Направления дороги B совпадают между собой
        self.assertEqual(edge_dict["road_B_fwd"].segment_id, edge_dict["road_B_rev"].segment_id)
        # Дорога A и Дорога B не склеиваются ошибочно
        self.assertNotEqual(edge_dict["road_A_fwd"].segment_id, edge_dict["road_B_fwd"].segment_id)

    def test_similar_length_different_osmid_or_geometry_not_merged(self):
        """
        Проверяет сценарий из ревью:
        Два разных участка близкой длины (100м и 102м) НЕ должны получать общий segment_id:
        1. Если у них разные OSM ID (например, 100 и 102) — сопоставление запрещено.
        2. Если у них разная геометрия (прямая vs изогнутая траектория) — сопоставление запрещено.
        """
        # 1. Проверка по разным OSM ID при близкой длине (100м и 102м)
        g_osm = nx.MultiDiGraph()
        g_osm.add_node("1", x=30.0, y=60.0)
        g_osm.add_node("2", x=30.01, y=60.01)
        g_osm.add_edge("1", "2", key=0, edge_type="road", id="r_fwd_100", length_m=100.0, osmid=100)
        g_osm.add_edge("2", "1", key=0, edge_type="road", id="r_rev_102", length_m=102.0, osmid=102)

        payload_osm = GraphSerializer.serialize(g_osm)
        edge_map_osm = {e.id: e for e in payload_osm.edges}
        self.assertNotEqual(
            edge_map_osm["r_fwd_100"].segment_id,
            edge_map_osm["r_rev_102"].segment_id,
            "Участки с разными OSM ID не должны объединяться в один segment_id!"
        )

        # 2. Проверка по разной геометрии (прямая линия vs дуга)
        g_geom = nx.MultiDiGraph()
        g_geom.add_node("1", x=30.0, y=60.0)
        g_geom.add_node("2", x=30.01, y=60.01)
        g_geom.add_edge(
            "1", "2", key=0, edge_type="road", id="g_fwd_straight", length_m=100.0,
            geometry=LineString([(30.0, 60.0), (30.01, 60.01)])
        )
        g_geom.add_edge(
            "2", "1", key=0, edge_type="road", id="g_rev_curved", length_m=102.0,
            geometry=LineString([(30.01, 60.01), (30.005, 60.007), (30.0, 60.0)])
        )

        payload_geom = GraphSerializer.serialize(g_geom)
        edge_map_geom = {e.id: e for e in payload_geom.edges}
        self.assertNotEqual(
            edge_map_geom["g_fwd_straight"].segment_id,
            edge_map_geom["g_rev_curved"].segment_id,
            "Участки с расходящейся геометрией не должны объединяться в один segment_id!"
        )


if __name__ == "__main__":
    unittest.main()

