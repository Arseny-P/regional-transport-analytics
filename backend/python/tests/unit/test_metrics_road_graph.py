import unittest
import networkx as nx
from shapely.geometry import LineString

from graph_service.application.metrics_service import GraphMetricsService
from graph_service.algorithms.logistics_graph_service import LogisticsGraphService
from graph_service.domain.models import LogisticsNode, RouteStatus


class TestMetricsRoadGraph(unittest.TestCase):
    def test_metrics_on_route_road_graph(self):
        """
        Проверяет расчет метрик на новом итоговом дорожном графе маршрутов (Спринт 4):
        вершины = склады + перекрестки + узлы дорог,
        ребра = сегменты road + коннекторы access_connector.
        """
        route_graph = nx.MultiDiGraph()
        route_graph.graph["crs"] = "epsg:4326"
        route_graph.graph["routes"] = [
            {"origin_id": "W1", "destination_id": "W2", "status": "found", "total_length_m": 1200.0},
            {"origin_id": "W2", "destination_id": "W1", "status": "found", "total_length_m": 1200.0},
            {"origin_id": "W1", "destination_id": "W_ISO", "status": "not_found_in_data"},
        ]

        # Узлы
        route_graph.add_node("W1", x=30.0, y=60.0, object_type="warehouse")
        route_graph.add_node("W2", x=30.02, y=60.0, object_type="warehouse")
        route_graph.add_node("W_ISO", x=30.09, y=60.09, object_type="warehouse", is_isolated=True)
        route_graph.add_node("10", x=30.001, y=60.0, object_type="road_node")
        route_graph.add_node("20", x=30.01, y=60.0, object_type="intersection")
        route_graph.add_node("30", x=30.019, y=60.0, object_type="road_node")

        # Дорожные сегменты
        route_graph.add_edge("10", "20", key=0, edge_type="road", length_m=500.0)
        route_graph.add_edge("20", "30", key=0, edge_type="road", length_m=500.0)
        route_graph.add_edge("30", "20", key=0, edge_type="road", length_m=500.0)
        route_graph.add_edge("20", "10", key=0, edge_type="road", length_m=500.0)

        # Коннекторы
        route_graph.add_edge("W1", "10", key="access_out", edge_type="access_connector", length_m=100.0)
        route_graph.add_edge("30", "W2", key="access_in", edge_type="access_connector", length_m=100.0)

        metrics = GraphMetricsService.calculate_metrics(route_graph)
        metric_map = {m.name: m.value for m in metrics}

        # Базовые показатели
        self.assertEqual(metric_map["vertex_count"], 6.0)
        self.assertGreater(metric_map["edge_count"], 0.0)
        self.assertIn("beta_index", metric_map)
        self.assertIn("alpha_index", metric_map)
        self.assertIn("gamma_index", metric_map)
        self.assertIn("network_density", metric_map)

        # Изолированный склад W_ISO должен быть зафиксирован
        self.assertEqual(metric_map["isolated_nodes_count"], 1.0)
        self.assertAlmostEqual(metric_map["isolated_nodes_ratio"], 1.0 / 6.0, places=3)

        # Метрики маршрутов
        self.assertEqual(metric_map["total_routes_count"], 3.0)
        self.assertEqual(metric_map["found_routes_count"], 2.0)
        self.assertAlmostEqual(metric_map["found_routes_ratio"], 2.0 / 3.0, places=3)


if __name__ == "__main__":
    unittest.main()

