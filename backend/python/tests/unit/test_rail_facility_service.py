import json
import unittest
import networkx as nx

from graph_service.domain.models import RailConnectionStatus, RailObjectType, RailNodeKind
from graph_service.algorithms.rail_facility_service import RailFacilityService


class TestRailFacilityService(unittest.TestCase):
    """
    Тестирование сервиса железнодорожных станций (RailFacilityService):
    отбор кандидатов, отсев метрополитена, множественные точки подключения (anchor_node_ids)
    и отсутствие искусственных переходов внутри станции.
    """

    def setUp(self):
        self.service = RailFacilityService(storage_dir="data")

    def test_extract_station_candidates_from_fixture(self):
        # Загрузка фикстуры объектов Шушар
        fixture_path = "backend/python/src/graph_service/fixtures/shushary_rail_objects.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        elements = data["response"]["elements"]
        candidates = self.service.extract_station_candidates(elements)

        # Должно быть ровно 2 железнодорожные станции (метро 'Шушары' отсеяно)
        self.assertEqual(len(candidates), 2)
        names = {c.name for c in candidates}
        self.assertIn("Шушары", names)
        self.assertIn("Юный", names)

        for c in candidates:
            self.assertEqual(c.connection_status, RailConnectionStatus.NOT_CHECKED.value)
            self.assertEqual(c.anchor_node_ids, [])

    def test_subway_filtering(self):
        # Проверка различных тегов метро
        self.assertTrue(self.service.is_subway_station({"station": "subway"}))
        self.assertTrue(self.service.is_subway_station({"subway": "yes"}))
        self.assertTrue(self.service.is_subway_station({"network": "Петербургский метрополитен"}))
        self.assertFalse(self.service.is_subway_station({"railway": "station", "station": "freight"}))
        self.assertFalse(self.service.is_subway_station({"railway": "station"}))

    def test_bind_station_multiple_anchors_without_free_transfers(self):
        """
        Проверка требования PM:
        - станция может иметь несколько подтвержденных точек подключения (anchor_node_ids).
        - между точками подключения НЕ создается искусственных бесплатных рёбер.
        """
        # Создаем тестовый рельсовый граф
        graph = nx.MultiGraph()
        graph.add_node("osm_node:101", object_type="rail_node", node_kind="intermediate")
        graph.add_node("osm_node:102", object_type="rail_node", node_kind="intermediate")
        graph.add_node("osm_node:103", object_type="rail_node", node_kind="intermediate")
        # Реальное ребро между 101 и 103 (но НЕ между 101 и 102)
        graph.add_edge("osm_node:101", "osm_node:103", length_m=150.0)

        fixture_path = "backend/python/src/graph_service/fixtures/shushary_rail_objects.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        candidates = self.service.extract_station_candidates(data["response"]["elements"])
        shushary_station = next(c for c in candidates if c.name == "Шушары")

        initial_edges_count = graph.number_of_edges()

        # Привязываем 2 точки подключения к станции Шушары
        anchors_map = {
            shushary_station.facility_id: ["101", "102"]
        }
        self.service.bind_station_anchors(candidates, anchors_map, graph=graph)

        # 1. Проверяем, что станция подключена и хранит обе точки
        self.assertEqual(shushary_station.connection_status, RailConnectionStatus.CONNECTED.value)
        self.assertEqual(set(shushary_station.anchor_node_ids), {"osm_node:101", "osm_node:102"})

        # 2. Проверяем обновление типов узлов в графе
        self.assertEqual(graph.nodes["osm_node:101"]["object_type"], RailObjectType.RAIL_FACILITY.value)
        self.assertEqual(graph.nodes["osm_node:101"]["node_kind"], RailNodeKind.STATION.value)
        self.assertEqual(graph.nodes["osm_node:102"]["object_type"], RailObjectType.RAIL_FACILITY.value)

        # 3. СТРОГАЯ ПРОВЕРКА: число рёбер в графе НЕ изменилось (нет бесплатного перехода 101 <-> 102)
        self.assertEqual(graph.number_of_edges(), initial_edges_count)
        self.assertFalse(graph.has_edge("osm_node:101", "osm_node:102"))

        # 4. Проверка подсчета верифицированных станций
        self.assertEqual(self.service.get_verified_station_count(candidates), 1)


if __name__ == "__main__":
    unittest.main()
