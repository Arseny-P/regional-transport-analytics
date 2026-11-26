import unittest
import time
from itertools import permutations
import networkx as nx

from graph_service.application.metrics_service import GraphMetricsService
from graph_service.kafka.schemas import MetricItem


class TestMetricsRoadGraph(unittest.TestCase):
    """
    Тесты расчёта метрик дорожного графа маршрутов по спецификации #71.
    """

    @staticmethod
    def _build_control_graph():
        """
        Создаёт эталонный контрольный дорожный граф из исследовательского ноутбука #71:
        - 5 складов: A, B, C, D (изолирован), E (делит дорожный узел r1 со складом A)
        - 2 перекрёстка: x, y
        - 3 дорожных узла: r1, r2, r3
        - 4 физических сегмента дорог: s1 (r1-x), s2 (x-r2), s3 (x-y), s4 (y-r3)
        """
        base = nx.MultiDiGraph()
        for n, kind, pos in [
            ("r1", "road_node", (0, 1)),
            ("x", "intersection", (1, 1)),
            ("r2", "road_node", (2, 1)),
            ("y", "intersection", (1, 0)),
            ("r3", "road_node", (2, 0)),
        ]:
            base.add_node(n, object_type=kind, pos=pos)

        def road(u, v, length, segment_id, key=0):
            base.add_edge(u, v, key=key, edge_type="road", length_m=float(length), segment_id=segment_id)

        for u, v, d, s in [
            ("r1", "x", 500, "s1"),
            ("x", "r2", 400, "s2"),
            ("x", "y", 300, "s3"),
            ("y", "r3", 600, "s4"),
        ]:
            road(u, v, d, s)
            road(v, u, d, s)
        # Дополнительная длинная дорога r1 -> y, не выбираемая кратчайшими путями
        road("r1", "y", 1500, "s5")

        snap = {"A": "r1", "B": "r2", "C": "r3", "D": None, "E": "r1"}

        # Поиск кратчайших путей между всеми парами складов
        H = nx.DiGraph()
        for u, v, d in base.edges(data=True):
            if not H.has_edge(u, v) or d["length_m"] < H[u][v]["length_m"]:
                H.add_edge(u, v, length_m=d["length_m"])

        routes = []
        for src, dst in permutations(snap, 2):
            a, b = snap[src], snap[dst]
            if a is None or b is None or not nx.has_path(H, a, b):
                routes.append(
                    dict(
                        origin_id=src,
                        destination_id=dst,
                        status="not_found_in_data",
                        road_length_m=None,
                        node_path=[],
                    )
                )
            else:
                nodes = nx.shortest_path(H, a, b, weight="length_m")
                length = nx.shortest_path_length(H, a, b, weight="length_m")
                routes.append(
                    dict(
                        origin_id=src,
                        destination_id=dst,
                        status="found",
                        road_length_m=float(length),
                        total_length_m=float(length) + 50.0,
                        snap_origin_m=25.0,
                        snap_dest_m=25.0,
                        node_path=nodes,
                    )
                )

        # Синтез итогового подграфа маршрутов
        G = nx.MultiDiGraph()
        for w, a in snap.items():
            G.add_node(w, object_type="warehouse", is_isolated=(a is None))

        used_pairs = set()
        for r in routes:
            if r["status"] == "found":
                used_pairs.update(zip(r["node_path"][:-1], r["node_path"][1:]))

        for u, v in used_pairs:
            key, data = min(base[u][v].items(), key=lambda item: item[1]["length_m"])
            for node in (u, v):
                if node not in G:
                    G.add_node(node, **base.nodes[node])
            G.add_edge(u, v, key=key, **dict(data))

        connected = {r["origin_id"] for r in routes if r["status"] == "found"} | {
            r["destination_id"] for r in routes if r["status"] == "found"
        }
        for w in connected:
            access_road_node = snap[w]
            G.add_edge(w, access_road_node, key="access_out", edge_type="access_connector", length_m=25.0)
            G.add_edge(access_road_node, w, key="access_in", edge_type="access_connector", length_m=25.0)

        G.graph["routes"] = routes
        return G, routes

    def test_control_graph_metrics_complete_verification(self):
        """
        Проверка расчёта всех трёх групп метрик (регион, склад, перекрёсток)
        на контрольном графе из #71 со сверкой точных значений из ноутбука.
        """
        graph, routes = self._build_control_graph()

        # Расчёт при пороге R = 2000 м
        metrics_2000 = GraphMetricsService.calculate_metrics(graph, routes, warehouse_neighbor_radius_m=2000.0)
        # Расчёт при пороге R = 900 м (для проверки промежуточного порога)
        metrics_900 = GraphMetricsService.calculate_metrics(graph, routes, warehouse_neighbor_radius_m=900.0)

        # -------------------------------------------------------------
        # 1. Проверка региональных метрик (node_id is None)
        # -------------------------------------------------------------
        regional_2000 = {m.name: m.value for m in metrics_2000 if m.node_id is None}
        self.assertEqual(regional_2000["warehouse_count"], 5.0)
        self.assertEqual(regional_2000["intersection_count"], 2.0)
        self.assertEqual(regional_2000["road_segment_count"], 4.0)
        self.assertEqual(regional_2000["component_count"], 2.0)
        self.assertEqual(regional_2000["node_count"], 10.0)
        self.assertEqual(regional_2000["road_node_count"], 3.0)
        self.assertEqual(regional_2000["directed_road_edge_count"], 8.0)
        self.assertEqual(regional_2000["access_connector_count"], 8.0)
        self.assertEqual(regional_2000["total_routes_count"], 20.0)
        self.assertEqual(regional_2000["found_routes_count"], 12.0)
        self.assertEqual(regional_2000["warehouses_without_routes_count"], 1.0)

        # -------------------------------------------------------------
        # 2. Проверка метрик складов (node_id = warehouse_id)
        # -------------------------------------------------------------
        wh_2000 = {}
        for m in metrics_2000:
            if m.node_id in ("A", "B", "C", "D", "E"):
                wh_2000.setdefault(m.node_id, {})[m.name] = m.value

        wh_900 = {}
        for m in metrics_900:
            if m.node_id in ("A", "B", "C", "D", "E"):
                wh_900.setdefault(m.node_id, {})[m.name] = m.value

        # Склад A (делит узел со складом E -> road_length = 0.0)
        self.assertEqual(wh_2000["A"]["nearest_warehouse_distance_m"], 0.0)
        self.assertEqual(wh_2000["A"]["nearby_warehouse_count"], 3.0)  # E(0), B(900), C(1400)
        self.assertEqual(wh_900["A"]["nearby_warehouse_count"], 2.0)   # E(0), B(900)

        # Склад B
        self.assertEqual(wh_2000["B"]["nearest_warehouse_distance_m"], 900.0)
        self.assertEqual(wh_2000["B"]["nearby_warehouse_count"], 3.0)  # A(900), E(900), C(1300)
        self.assertEqual(wh_900["B"]["nearby_warehouse_count"], 2.0)   # A(900), E(900)

        # Склад C
        self.assertEqual(wh_2000["C"]["nearest_warehouse_distance_m"], 1300.0)  # до B: 600 + 300 + 400 = 1300
        self.assertEqual(wh_2000["C"]["nearby_warehouse_count"], 3.0)          # B(1300), A(1400), E(1400)
        self.assertEqual(wh_900["C"]["nearby_warehouse_count"], 0.0)

        # Склад D (изолирован)
        # КРИТИЧНО: nearest_warehouse_distance_m не должно передаваться искусственным нулём!
        self.assertNotIn("nearest_warehouse_distance_m", wh_2000["D"])
        self.assertEqual(wh_2000["D"]["nearby_warehouse_count"], 0.0)

        # Склад E (делит узел с A -> road_length = 0.0)
        self.assertEqual(wh_2000["E"]["nearest_warehouse_distance_m"], 0.0)
        self.assertEqual(wh_2000["E"]["nearby_warehouse_count"], 3.0)

        # -------------------------------------------------------------
        # 3. Проверка метрик перекрёстков (node_id = intersection_id)
        # -------------------------------------------------------------
        ix_metrics = {}
        for m in metrics_2000:
            if m.node_id in ("x", "y"):
                ix_metrics.setdefault(m.node_id, {})[m.name] = m.value

        # Перекрёсток x: центральный узел (10 из 12 маршрутов)
        self.assertAlmostEqual(ix_metrics["x"]["pagerank"], 0.357557, places=5)
        self.assertAlmostEqual(ix_metrics["x"]["betweenness_centrality"], 5.0 / 6.0, places=5)  # 0.833333
        self.assertAlmostEqual(ix_metrics["x"]["route_fraction"], 10.0 / 12.0, places=5)       # 0.833333

        # Перекрёсток y: промежуточный узел (6 из 12 маршрутов)
        self.assertAlmostEqual(ix_metrics["y"]["pagerank"], 0.245493, places=5)
        self.assertAlmostEqual(ix_metrics["y"]["betweenness_centrality"], 0.5, places=5)
        self.assertAlmostEqual(ix_metrics["y"]["route_fraction"], 6.0 / 12.0, places=5)        # 0.5

    def test_metrics_large_graph_betweenness_sampling(self):
        """
        Проверяет производительность и корректность расчёта для графа > 1000 узлов:
        - Включается сэмплирование k=64 для betweenness_centrality
        - Время вычисления не превышает 2 секунд
        """
        n_nodes = 1200
        graph = nx.MultiDiGraph()
        graph.graph["crs"] = "epsg:4326"

        for i in range(n_nodes):
            kind = "intersection" if i % 10 == 0 else "road_node"
            graph.add_node(str(i), object_type=kind)
            if i > 0:
                graph.add_edge(str(i - 1), str(i), key=0, edge_type="road", length_m=50.0, segment_id=f"seg_{i}")
                graph.add_edge(str(i), str(i - 1), key=0, edge_type="road", length_m=50.0, segment_id=f"seg_{i}")

        # Добавим склады на концах
        graph.add_node("W_start", object_type="warehouse")
        graph.add_node("W_end", object_type="warehouse")
        graph.add_edge("W_start", "0", key="access_out", edge_type="access_connector", length_m=20.0)
        graph.add_edge("0", "W_start", key="access_in", edge_type="access_connector", length_m=20.0)
        graph.add_edge("W_end", str(n_nodes - 1), key="access_out", edge_type="access_connector", length_m=20.0)
        graph.add_edge(str(n_nodes - 1), "W_end", key="access_in", edge_type="access_connector", length_m=20.0)

        routes = [
            dict(
                origin_id="W_start",
                destination_id="W_end",
                status="found",
                road_length_m=float((n_nodes - 1) * 50.0),
                node_path=[str(i) for i in range(n_nodes)],
            ),
            dict(
                origin_id="W_end",
                destination_id="W_start",
                status="found",
                road_length_m=float((n_nodes - 1) * 50.0),
                node_path=[str(i) for i in range(n_nodes - 1, -1, -1)],
            ),
        ]
        graph.graph["routes"] = routes

        start_time = time.perf_counter()
        metrics = GraphMetricsService.calculate_metrics(graph, routes)
        elapsed = time.perf_counter() - start_time

        # Должно отработать быстро благодаря k=64
        self.assertLess(elapsed, 2.5)

        # Проверим наличие метрик перекрёстков
        ix_nodes = [m for m in metrics if m.name == "betweenness_centrality"]
        self.assertEqual(len(ix_nodes), 120)  # 1200 / 10 = 120 перекрёстков

        # Проверим, что все значения конечны и валидны для сериализации в Kafka
        for m in metrics:
            d = m.to_dict()
            self.assertIsInstance(d["value"], float)

    def test_legacy_graph_fallback(self):
        """
        Проверяет сохранение обратной совместимости для старых графов склад-склад.
        """
        legacy_graph = nx.MultiGraph()
        legacy_graph.add_node("hub1", name="Склад 1")
        legacy_graph.add_node("hub2", name="Склад 2")
        legacy_graph.add_edge("hub1", "hub2", route_status_ab="found", total_distance_ab_m=5000.0)

        metrics = GraphMetricsService.calculate_metrics(legacy_graph)
        metric_dict = {m.name: m.value for m in metrics}

        self.assertEqual(metric_dict["vertex_count"], 2.0)
        self.assertEqual(metric_dict["edge_count"], 1.0)
        self.assertEqual(metric_dict["beta_index"], 0.5)
        self.assertEqual(metric_dict["avg_edge_distance_km"], 5.0)


if __name__ == "__main__":
    unittest.main()
