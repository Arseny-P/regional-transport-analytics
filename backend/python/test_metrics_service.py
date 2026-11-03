import unittest
import networkx as nx

from services.metrics_service import (
    calculate_metrics_report,
    to_directed_graph,
)


class TestMetricsService(unittest.TestCase):

    def setUp(self):
        """Тестовый граф: A <-> B -> C, D изолирована."""
        self.graph = nx.MultiGraph()
        self.graph.add_nodes_from(["A", "B", "C", "D"])

        self.graph.add_edge(
            "A", "B",
            node_a="A", node_b="B",
            route_status_ab="found",
            route_status_ba="found",
            total_distance_ab_m=1500,
            total_distance_ba_m=1700,
        )

        self.graph.add_edge(
            "B", "C",
            node_a="B", node_b="C",
            route_status_ab="found",
            route_status_ba="not_found_in_data",
            total_distance_ab_m=2300,
            total_distance_ba_m="",
        )

    def test_graph_metrics(self):
        result = calculate_metrics_report(self.graph)
        metrics = result["graph_metrics"]

        self.assertEqual(metrics["node_count"], 4)
        self.assertEqual(metrics["edge_count"], 2)
        self.assertEqual(metrics["directed_route_count"], 3)
        self.assertEqual(metrics["component_count"], 2)

    def test_node_metrics(self):
        result = calculate_metrics_report(self.graph)
        nodes = result["node_metrics"]

        self.assertEqual(nodes["A"]["reachable_count"], 2)
        self.assertEqual(nodes["B"]["reachable_count"], 2)
        self.assertEqual(nodes["C"]["reachable_count"], 0)
        self.assertEqual(nodes["D"]["reachable_count"], 0)

        self.assertAlmostEqual(
            nodes["A"]["average_distance_m"], 2650
        )
        self.assertAlmostEqual(
            nodes["B"]["average_distance_m"], 2000
        )

        self.assertIsNone(nodes["C"]["average_distance_m"])
        self.assertIsNone(nodes["D"]["average_distance_m"])

        self.assertAlmostEqual(
            nodes["A"]["weighted_closeness"], 0.2516
        )
        self.assertAlmostEqual(
            nodes["B"]["weighted_closeness"], 0.3333
        )

    def test_directions(self):
        directed = to_directed_graph(self.graph)

        self.assertTrue(directed.has_edge("A", "B"))
        self.assertTrue(directed.has_edge("B", "A"))
        self.assertTrue(directed.has_edge("B", "C"))
        self.assertFalse(directed.has_edge("C", "B"))

        self.assertEqual(
            nx.shortest_path_length(
                directed, "A", "C", weight="weight"
            ),
            3800,
        )

    def test_invalid_distances(self):
        graph = nx.MultiGraph()
        graph.add_nodes_from(["A", "B"])

        graph.add_edge(
            "A", "B",
            node_a="A", node_b="B",
            route_status_ab="found",
            route_status_ba="found",
            total_distance_ab_m=-100,
            total_distance_ba_m="nan",
        )

        directed = to_directed_graph(graph)
        self.assertEqual(directed.number_of_edges(), 0)

    def test_duplicate_routes(self):
        graph = nx.MultiGraph()
        graph.add_nodes_from(["A", "B"])

        for distance in [3000, 1500, 2500]:
            graph.add_edge(
                "A", "B",
                node_a="A", node_b="B",
                route_status_ab="found",
                route_status_ba="not_found_in_data",
                total_distance_ab_m=distance,
            )

        directed = to_directed_graph(graph)

        self.assertEqual(directed.number_of_edges(), 1)
        self.assertEqual(directed["A"]["B"]["weight"], 1500)


if __name__ == "__main__":
    unittest.main()
