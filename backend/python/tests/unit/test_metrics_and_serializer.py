import unittest
import networkx as nx
from shapely.geometry import LineString

from graph_service.application.graph_serializer import GraphSerializer
from graph_service.application.metrics_service import GraphMetricsService
from graph_service.kafka.schemas import GraphPayload, MetricItem


class TestMetricsAndSerializer(unittest.TestCase):
    def setUp(self):
        self.graph = nx.MultiGraph()

        # Создаем 3 тестовых логистических узла
        self.graph.add_node("hub_1", x=30.25, y=59.90, name="Склад А", object_type="warehouse")
        self.graph.add_node("hub_2", x=30.30, y=59.92, name="Терминал Б", object_type="terminal")
        self.graph.add_node("hub_3", x=30.35, y=59.95, name="Порт В", object_type="port")

        # Геометрии дорог
        geom_1_2 = LineString([(30.25, 59.90), (30.27, 59.91), (30.30, 59.92)])
        geom_2_3 = LineString([(30.30, 59.92), (30.32, 59.93), (30.35, 59.95)])

        self.graph.add_edge(
            "hub_1",
            "hub_2",
            key="road",
            transport_mode="road",
            route_status_ab="found",
            route_status_ba="found",
            total_distance_ab_m=4500.0,
            total_distance_ba_m=4500.0,
            road_geometry_ab_wkt=geom_1_2.wkt,
        )
        self.graph.add_edge(
            "hub_2",
            "hub_3",
            key="road",
            transport_mode="road",
            route_status_ab="found",
            route_status_ba="found",
            total_distance_ab_m=5500.0,
            total_distance_ba_m=5500.0,
            road_geometry_ab_wkt=geom_2_3.wkt,
        )

    def test_graph_serializer_nodes_and_edges(self):
        payload: GraphPayload = GraphSerializer.serialize(self.graph)
        self.assertEqual(len(payload.nodes), 3)
        self.assertEqual(len(payload.edges), 2)

        # Проверка порядка координат: строго [lon, lat]
        node_map = {n.id: n for n in payload.nodes}
        self.assertEqual(node_map["hub_1"].position, [30.25, 59.90])
        self.assertEqual(node_map["hub_2"].position, [30.30, 59.92])

        # Проверка геометрии ребра
        edge = payload.edges[0]
        self.assertIsNotNone(edge.geometry)
        self.assertEqual(len(edge.geometry), 3)
        self.assertEqual(edge.geometry[0], [30.25, 59.90])
        self.assertEqual(edge.geometry[-1], [30.30, 59.92])

    def test_graph_metrics_calculation(self):
        metrics = GraphMetricsService.calculate_metrics(self.graph)
        metric_dict = {m.name: m.value for m in metrics}

        self.assertEqual(metric_dict["vertex_count"], 3.0)
        self.assertEqual(metric_dict["edge_count"], 2.0)
        self.assertEqual(metric_dict["connected_components_count"], 1.0)
        self.assertEqual(metric_dict["isolated_nodes_count"], 0.0)

        # Beta = E / V = 2 / 3 = 0.6667
        self.assertAlmostEqual(metric_dict["beta_index"], 0.6667, places=3)
        self.assertGreater(metric_dict["avg_edge_distance_km"], 0.0)
        self.assertGreater(metric_dict["diameter_km"], 0.0)

        # Все метрики должны успешно сериализоваться в JSON без ошибок finite
        for m in metrics:
            d = m.to_dict()
            self.assertIsInstance(d["value"], float)

    def test_metrics_on_empty_and_isolated_graph(self):
        empty_g = nx.MultiGraph()
        metrics_empty = GraphMetricsService.calculate_metrics(empty_g)
        self.assertEqual(len(metrics_empty), 2)

        isolated_g = nx.MultiGraph()
        isolated_g.add_node("n1", x=30.0, y=59.0)
        isolated_g.add_node("n2", x=30.1, y=59.1)
        metrics_iso = GraphMetricsService.calculate_metrics(isolated_g)
        iso_dict = {m.name: m.value for m in metrics_iso}
        self.assertEqual(iso_dict["vertex_count"], 2.0)
        self.assertEqual(iso_dict["edge_count"], 0.0)
        self.assertEqual(iso_dict["isolated_nodes_count"], 2.0)
        self.assertEqual(iso_dict["isolated_nodes_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()

