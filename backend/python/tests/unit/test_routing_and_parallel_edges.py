import unittest
import networkx as nx
from shapely.geometry import LineString

from graph_service.domain.models import LogisticsNode, RouteDetail, RouteStatus
from graph_service.algorithms.logistics_graph_service import LogisticsGraphService


class TestRoutingAndParallelEdges(unittest.TestCase):
    def setUp(self):
        self.service = LogisticsGraphService(storage_dir="data")

    def test_parallel_edges_selection_min_length(self):
        """
        Проверяет, что при наличии параллельных рёбер MultiDiGraph
        выбирается именно ребро с минимальной длиной и соответствующей геометрией,
        а не ребро с ключом 0 по умолчанию.
        """
        road_graph = nx.MultiDiGraph()
        road_graph.graph["crs"] = "epsg:4326"

        road_graph.add_node(1, x=30.0, y=60.0)
        road_graph.add_node(2, x=30.01, y=60.0)

        # Ребро с ключом 0 — длинный объезд (длина 1500м)
        road_graph.add_edge(
            1, 2, key=0,
            length=1500.0,
            geometry=LineString([(30.0, 60.0), (30.005, 60.01), (30.01, 60.0)]),
            name="Длинный объезд",
        )
        # Ребро с ключом 1 — прямой кратчайший путь (длина 550м)
        road_graph.add_edge(
            1, 2, key=1,
            length=550.0,
            geometry=LineString([(30.0, 60.0), (30.01, 60.0)]),
            name="Прямой путь",
        )

        best_key, best_data = self.service._get_best_edge(road_graph, 1, 2)
        self.assertEqual(best_key, 1)
        self.assertEqual(best_data["length"], 550.0)
        self.assertEqual(best_data["name"], "Прямой путь")

        geom, edge_keys = self.service._extract_route_geometry_and_keys(road_graph, [1, 2])
        self.assertEqual(edge_keys, [(1, 2, 1)])
        self.assertEqual(list(geom.coords), [(30.0, 60.0), (30.01, 60.0)])

    def test_dijkstra_caching_and_route_details(self):
        """
        Проверяет работу кэша Dijkstra и корректное заполнение RouteDetail
        с сохранением ключей рёбер (u, v, key) и длин.
        """
        road_graph = nx.MultiDiGraph()
        road_graph.graph["crs"] = "epsg:4326"

        road_graph.add_node(10, x=30.0, y=60.0)
        road_graph.add_node(20, x=30.01, y=60.0)
        road_graph.add_node(30, x=30.02, y=60.0)

        road_graph.add_edge(10, 20, key="e1", length=500.0)
        road_graph.add_edge(20, 30, key="e2", length=600.0)

        fac_a = LogisticsNode(
            id="fac_a",
            name="Склад A",
            object_type="warehouse",
            latitude=60.0,
            longitude=30.0,
            nearest_osm_node=10,
            access_nodes=[10],
        )
        fac_b = LogisticsNode(
            id="fac_b",
            name="Склад B",
            object_type="warehouse",
            latitude=60.0,
            longitude=30.02,
            nearest_osm_node=30,
            access_nodes=[30],
        )

        dijkstra_cache = {}
        res = self.service._calculate_best_route(
            road_graph=road_graph,
            start_nodes=[10],
            end_nodes=[30],
            origin_coords=(30.0, 60.0),
            dest_coords=(30.02, 60.0),
            dijkstra_cache=dijkstra_cache,
        )

        self.assertEqual(res["status"], RouteStatus.FOUND.value)
        self.assertEqual(res["distance_m"], 1100.0)
        self.assertEqual(res["path"], [10, 20, 30])
        self.assertEqual(res["edge_keys"], [(10, 20, "e1"), (20, 30, "e2")])

        # Проверяем, что узел 10 закэширован
        self.assertIn(10, dijkstra_cache)
        lengths, paths = dijkstra_cache[10]
        self.assertEqual(lengths[30], 1100.0)
        self.assertEqual(paths[30], [10, 20, 30])

        # Проверяем calculate_all_routes
        routes = self.service.calculate_all_routes(road_graph, [fac_a, fac_b])
        self.assertEqual(len(routes), 2)  # A->B и B->A

        route_ab = next(r for r in routes if r.origin_id == "fac_a" and r.destination_id == "fac_b")
        self.assertEqual(route_ab.status, RouteStatus.FOUND.value)
        self.assertEqual(route_ab.node_path, [10, 20, 30])
        self.assertEqual(route_ab.edge_keys, [(10, 20, "e1"), (20, 30, "e2")])

        # B -> A не существует (так как граф односторонний 10 -> 20 -> 30)
        route_ba = next(r for r in routes if r.origin_id == "fac_b" and r.destination_id == "fac_a")
        self.assertEqual(route_ba.status, RouteStatus.NOT_FOUND_IN_DATA.value)
        self.assertEqual(route_ba.node_path, [])
        self.assertEqual(route_ba.edge_keys, [])

    def test_dijkstra_cache_memory_bounded_to_target_nodes(self):
        """
        Проверяет, что кэш Dijkstra ограничен ТОЛЬКО целевыми точками подключения складов,
        а не материализует пути ко всем вершинам большой дорожной сети.
        """
        road_graph = nx.MultiDiGraph()
        road_graph.graph["crs"] = "epsg:4326"

        # Создаем линейную цепь из 50 дорожных узлов: 1 -> 2 -> ... -> 50
        for i in range(1, 51):
            road_graph.add_node(i, x=30.0 + i * 0.001, y=60.0)
            if i > 1:
                road_graph.add_edge(i - 1, i, key=0, length=100.0)

        # Склады привязаны к узлам 1 и 5 (узлы 6..50 не являются точками подключения)
        w_start = LogisticsNode(
            id="W_START", name="Старт", object_type="warehouse",
            latitude=60.0, longitude=30.001,
            nearest_osm_node=1, access_nodes=[1],
        )
        w_end = LogisticsNode(
            id="W_END", name="Финиш", object_type="warehouse",
            latitude=60.0, longitude=30.005,
            nearest_osm_node=5, access_nodes=[5],
        )

        dijkstra_cache = {}
        res = self.service._calculate_best_route(
            road_graph=road_graph,
            start_nodes=[1],
            end_nodes=[5],
            origin_coords=(30.001, 60.0),
            dest_coords=(30.005, 60.0),
            dijkstra_cache=dijkstra_cache,
            target_nodes={1, 5},
        )

        self.assertEqual(res["status"], RouteStatus.FOUND.value)
        self.assertEqual(res["distance_m"], 400.0)
        self.assertEqual(res["path"], [1, 2, 3, 4, 5])

        # Проверяем кэш: в нем есть узел 5, но НЕТ узлов 6..50!
        cached_lengths, cached_paths = dijkstra_cache[1]
        self.assertIn(5, cached_lengths)
        self.assertIn(5, cached_paths)
        # Узлы за пределами целевого набора НЕ хранятся в кэше
        for unused_node in range(6, 51):
            self.assertNotIn(unused_node, cached_lengths)
            self.assertNotIn(unused_node, cached_paths)


if __name__ == "__main__":
    unittest.main()

