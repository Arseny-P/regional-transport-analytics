import os
import unittest
import networkx as nx
from shapely.geometry import LineString

from graph_service.domain.models import TerritoryBounds, RailNodeKind, RailObjectType
from graph_service.domain.errors import OfflineDataNotFoundError
from graph_service.algorithms.rail_network_service import RailNetworkService


class TestRailNetworkService(unittest.TestCase):
    """
    Тестирование алгоритмического сервиса железнодорожной сети (RailNetworkService):
    отбор линий, обрезка по BBox, топологическое сжатие, направленный граф и центральность.
    """

    def setUp(self):
        os.environ["OSM_OFFLINE_MODE"] = "true"
        self.service = RailNetworkService(storage_dir="data")
        self.shushary_bbox = TerritoryBounds(
            min_lat=59.7950,
            min_lon=30.3850,
            max_lat=59.8240,
            max_lon=30.4410,
        )

    def test_classify_way(self):
        # 1. Целевая железная дорога
        dec, rsn = self.service.classify_way({"railway": "rail"})
        self.assertEqual(dec, "selected")

        # 2. Целевая ЖД с сервисом и частным доступом (должна включаться!)
        dec, rsn = self.service.classify_way({"railway": "rail", "service": "spur", "access": "private"})
        self.assertEqual(dec, "selected")

        # 3. Метрополитен и трамвай (должны исключаться)
        dec, rsn = self.service.classify_way({"railway": "subway"})
        self.assertEqual(dec, "excluded")
        dec, rsn = self.service.classify_way({"railway": "tram"})
        self.assertEqual(dec, "excluded")
        dec, rsn = self.service.classify_way({"railway": "narrow_gauge"})
        self.assertEqual(dec, "excluded")

        # 4. Неактивные пути (disused, abandoned)
        dec, rsn = self.service.classify_way({"railway": "disused"})
        self.assertEqual(dec, "excluded")
        dec, rsn = self.service.classify_way({"railway": "rail", "disused": "yes"})
        self.assertEqual(dec, "excluded")

        # 5. Конфликт активного пути и префикса состояния
        dec, rsn = self.service.classify_way({"railway": "rail", "disused:railway": "rail"})
        self.assertEqual(dec, "review")

    def test_build_from_bbox_shushary_benchmark(self):
        """
        Проверка на эталонном полигоне Шушар:
        - 361 узел и 365 физических сегментов после обрезки (33 граничные точки).
        - 86 узлов и 90 физических сегментов после сжатия.
        - Сохранение 36 размеченных стрелок.
        - Сохранение суммарной геодезической длины (около 25.750 км).
        """
        G_geom, G_simple = self.service.build_from_bbox(self.shushary_bbox)

        # 1. Проверка геометрического графа до сжатия
        self.assertEqual(len(G_geom), 361)
        self.assertEqual(G_geom.number_of_edges(), 365)
        boundary_nodes = [n for n, d in G_geom.nodes(data=True) if d.get("is_boundary")]
        self.assertEqual(len(boundary_nodes), 33)

        # 2. Проверка сжатого графа
        self.assertEqual(len(G_simple), 86)
        self.assertEqual(G_simple.number_of_edges(), 90)

        # 3. Проверка размеченных стрелок
        switch_nodes = [n for n, d in G_simple.nodes(data=True) if d.get("is_switch")]
        self.assertEqual(len(switch_nodes), 36)

        # 4. Точное сохранение длины и компонент связности
        len_geom = sum(d["length_m"] for *_, d in G_geom.edges(data=True))
        len_simple = sum(d["length_m"] for *_, d in G_simple.edges(data=True))
        self.assertAlmostEqual(len_geom, len_simple, places=4)
        self.assertAlmostEqual(len_simple / 1000.0, 25.750071, places=3)
        self.assertEqual(
            nx.number_connected_components(G_geom),
            nx.number_connected_components(G_simple),
        )

        # 5. Проверка атрибутов вершин и рёбер
        sample_node = next(iter(G_simple.nodes(data=True)))[1]
        self.assertEqual(sample_node.get("object_type"), RailObjectType.RAIL_NODE.value)
        self.assertIn("node_kind", sample_node)

        sample_edge = next(iter(G_simple.edges(data=True)))[2]
        self.assertIn("segment_id", sample_edge)
        self.assertIn("length_m", sample_edge)
        self.assertIn("geometry", sample_edge)
        self.assertIsInstance(sample_edge["geometry"], LineString)

    def test_to_routing_graph_and_centrality(self):
        """
        Проверка преобразования в направленный граф и граф для Betweenness Centrality.
        """
        _, G_simple = self.service.build_from_bbox(self.shushary_bbox)

        # Маршрутный MultiDiGraph
        routing_g = self.service.to_routing_graph(G_simple)
        self.assertIsInstance(routing_g, nx.MultiDiGraph)
        self.assertEqual(len(routing_g), len(G_simple))
        # Так как пути двусторонние, 90 сегментов удваиваются до 180 дуг
        self.assertEqual(routing_g.number_of_edges(), 180)

        # Граф центральности DiGraph
        centrality_g = self.service.to_centrality_digraph(routing_g)
        self.assertIsInstance(centrality_g, nx.DiGraph)
        self.assertEqual(len(centrality_g), 86)
        self.assertEqual(centrality_g.number_of_edges(), 180)

        # Проверка целочисленного веса в сантиметрах
        for *_, d in centrality_g.edges(data=True):
            self.assertIn("weight_cm", d)
            self.assertIsInstance(d["weight_cm"], int)
            self.assertGreaterEqual(d["weight_cm"], 1)

    def test_offline_data_not_found_on_unknown_territory(self):
        """
        Проверка корректного выброса OfflineDataNotFoundError при отсутствии фикстур.
        """
        unknown_bbox = TerritoryBounds(
            min_lat=10.0,
            min_lon=10.0,
            max_lat=10.5,
            max_lon=10.5,
        )
        with self.assertRaises(OfflineDataNotFoundError):
            self.service.build_from_bbox(unknown_bbox)


if __name__ == "__main__":
    unittest.main()
