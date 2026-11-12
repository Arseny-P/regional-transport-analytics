import os
import json
import unittest
import networkx as nx
import geopandas as gpd
from shapely.geometry import Polygon, Point

from graph_service.domain import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    TerritorySourceType,
    FacilitySourceType,
    LogisticsNode,
)
from graph_service.algorithms import FacilityService, LogisticsGraphService
from graph_service.application import TerritoryAnalysisService, GraphSerializer


class TestIssue64PipelineVerification(unittest.TestCase):
    """
    Интеграционная верификация алгоритма отбора складов и их подключения (#64)
    на тестовой территории.
    """

    def setUp(self):
        curr = os.path.dirname(os.path.abspath(__file__))
        while curr and not os.path.exists(os.path.join(curr, "data")):
            parent = os.path.dirname(curr)
            if parent == curr:
                break
            curr = parent
        self.data_dir = os.path.join(curr, "data")
        self.facility_service = FacilityService(storage_dir=self.data_dir)
        self.logistics_service = LogisticsGraphService(storage_dir=self.data_dir)

    def test_warehouse_selection_and_pipeline_on_test_territory(self):
        """
        Проверяет полный сквозной сценарий Спринта 4 (Issue 2):
        1. Отбор складов из OSM GeoDataFrame по правилам #64.
        2. Пространственная привязка складов к дорожной сети.
        3. Синтез дорожного графа с разделением road и access_connector.
        4. Сохранение изолированных складов с указанием причины.
        5. Сериализация в контракт Go-оркестратора.
        """
        # --- 1. Формируем тестовые объекты территории (Шушары / Пулково) ---
        # Площадка комплекса (PNK Group)
        site_poly = Polygon([(30.40, 59.80), (30.42, 59.80), (30.42, 59.82), (30.40, 59.82)])
        # Корпус 1 внутри площадки (тот же оператор PNK Group)
        bld1_poly = Polygon([(30.402, 59.802), (30.408, 59.802), (30.408, 59.808), (30.402, 59.808)])
        # Корпус 2 внутри площадки (тот же оператор PNK Group)
        bld2_poly = Polygon([(30.412, 59.802), (30.418, 59.802), (30.418, 59.808), (30.412, 59.808)])
        # Отдельный склад Ozon снаружи комплекса
        bld3_poly = Polygon([(30.430, 59.810), (30.435, 59.810), (30.435, 59.815), (30.430, 59.815)])
        # Завод без складских признаков (должен быть excluded)
        factory_poly = Polygon([(30.440, 59.810), (30.445, 59.810), (30.445, 59.815), (30.440, 59.815)])
        # Заброшенный склад (должен уйти в review)
        abandoned_pt = Point(30.450, 59.820)
        # Удаленный склад в Финском заливе (акватория, должен стать isolated из-за порога расстояния)
        sea_warehouse_pt = Point(29.800, 60.000)

        osm_features_data = [
            {"industrial": "warehouse", "name": "Логистический парк PNK", "operator": "PNK Group", "geometry": site_poly},
            {"building": "warehouse", "name": "Корпус 1", "operator": "PNK Group", "geometry": bld1_poly},
            {"building": "warehouse", "name": "Корпус 2", "operator": "PNK Group", "geometry": bld2_poly},
            {"building": "warehouse", "name": "Фулфилмент Ozon", "operator": "Ozon", "geometry": bld3_poly},
            {"building": "industrial", "name": "Завод Металлопрокат", "geometry": factory_poly},
            {"building": "warehouse", "name": "Старый заброшенный пакгауз", "disused": "yes", "geometry": abandoned_pt},
            {"building": "warehouse", "name": "Складской терминал на дамбе", "geometry": sea_warehouse_pt},
        ]

        gdf = gpd.GeoDataFrame(
            osm_features_data,
            geometry="geometry",
            crs="EPSG:4326",
            index=[
                ("way", 10001),
                ("way", 10002),
                ("way", 10003),
                ("way", 10004),
                ("way", 10005),
                ("node", 10006),
                ("node", 10007),
            ],
        )

        # Выполняем отбор по правилам #64
        selected_nodes, audit = self.facility_service.select_warehouse_nodes_from_gdf(
            gdf, region_id="ru-spb", limit=10
        )

        audit_by_id = {row["osm_id"]: row for row in audit}

        # 1. Проверяем результаты отбора
        self.assertEqual(audit_by_id["osm:way/10001"]["decision"], "selected")  # Площадка комплекса
        self.assertEqual(audit_by_id["osm:way/10002"]["decision"], "grouped")   # Корпус 1 сгруппирован
        self.assertEqual(audit_by_id["osm:way/10003"]["decision"], "grouped")   # Корпус 2 сгруппирован
        self.assertEqual(audit_by_id["osm:way/10004"]["decision"], "selected")  # Ozon отобран
        self.assertEqual(audit_by_id["osm:way/10005"]["decision"], "excluded")  # Завод исключен
        self.assertEqual(audit_by_id["osm:node/10006"]["decision"], "review")   # Заброшенный отправлен в review
        self.assertEqual(audit_by_id["osm:node/10007"]["decision"], "selected") # Терминал на дамбе отобран

        # Итого в выборку попали 3 объекта (комплекс PNK, склад Ozon, терминал на дамбе)
        self.assertEqual(len(selected_nodes), 3)

        # Проверяем суммирование площадей корпусов у комплекса
        pnk_node = next(n for n in selected_nodes if "PNK" in n.name)
        self.assertGreater(pnk_node.identification_basis["warehouse_area_m2"], 10000.0)
        self.assertIn("osm:way/10001", pnk_node.source_osm_ids)
        self.assertIn("osm:way/10002", pnk_node.source_osm_ids)
        self.assertIn("osm:way/10003", pnk_node.source_osm_ids)

        # --- 2. Строим дорожную сеть окрестности ---
        roads = nx.MultiDiGraph()
        roads.graph["crs"] = "epsg:4326"

        # Дорога между PNK и Ozon: узлы 1, 2, 3
        roads.add_node(1, x=30.41, y=59.80, street_count=2)
        roads.add_node(2, x=30.42, y=59.805, street_count=3)
        roads.add_node(3, x=30.43, y=59.81, street_count=2)

        roads.add_edge(1, 2, key=0, length=800.0, highway="primary", oneway=False, name="Московское шоссе")
        roads.add_edge(2, 1, key=0, length=800.0, highway="primary", oneway=False, name="Московское шоссе")
        roads.add_edge(2, 3, key=0, length=600.0, highway="secondary", oneway=False, name="Софийская ул.")
        roads.add_edge(3, 2, key=0, length=600.0, highway="secondary", oneway=False, name="Софийская ул.")

        # --- 3. Выполняем привязку складов с порогом расстояния 1000 м ---
        snapped = self.facility_service.snap_to_road_network(
            road_graph=roads,
            nodes=selected_nodes,
            filter_disconnected=False,
            max_snap_distance_m=1000.0,
        )

        self.assertEqual(len(snapped), 3)

        # Проверяем отчет о привязке
        snap_report = FacilityService.get_snap_report(snapped)
        report_by_name = {r["name"]: r for r in snap_report}

        pnk_rep = next(r for name, r in report_by_name.items() if "PNK" in name)
        ozon_rep = next(r for name, r in report_by_name.items() if "Ozon" in name)
        sea_rep = next(r for name, r in report_by_name.items() if "дамбе" in name)

        self.assertFalse(pnk_rep["is_isolated"])
        self.assertIsNotNone(pnk_rep["nearest_osm_node"])
        self.assertLess(pnk_rep["snap_distance_m"], 1000.0)

        self.assertFalse(ozon_rep["is_isolated"])
        self.assertIsNotNone(ozon_rep["nearest_osm_node"])

        # Терминал на дамбе (удален на десятки километров) должен быть изолирован
        self.assertTrue(sea_rep["is_isolated"])
        self.assertIsNone(sea_rep["nearest_osm_node"])
        self.assertIn("Превышен лимит расстояния", sea_rep["isolation_reason"])

        # --- 4. Строим дорожный граф маршрутов ---
        routes = self.logistics_service.calculate_all_routes(
            road_graph=roads,
            nodes=snapped,
        )

        route_road_graph = self.logistics_service.build_route_road_graph(
            road_graph=roads,
            nodes=snapped,
            routes=routes,
        )

        # Проверяем вершины графа
        node_types = {d.get("object_type") for _, d in route_road_graph.nodes(data=True)}
        self.assertIn("warehouse", node_types)
        self.assertIn("intersection", node_types)

        # Все 3 склада присутствуют в вершинах графа
        for n in snapped:
            self.assertIn(str(n.id), route_road_graph.nodes)

        # Изолированный терминал на дамбе сохранен с причиной
        sea_node_data = route_road_graph.nodes[str(sea_rep["warehouse_id"])]
        self.assertTrue(sea_node_data["is_isolated"])
        self.assertIn("Превышен лимит расстояния", sea_node_data["isolation_reason"])

        # Проверяем рёбра: дорожные участки и коннекторы разделены
        edge_types = {d.get("edge_type") for _, _, _, d in route_road_graph.edges(keys=True, data=True)}
        self.assertIn("road", edge_types)
        self.assertIn("access_connector", edge_types)

        # --- 5. Сериализация в контракт Go-оркестратора ---
        serialized_payload = GraphSerializer.serialize(route_road_graph)
        self.assertGreater(len(serialized_payload.nodes), 0)
        self.assertGreater(len(serialized_payload.edges), 0)

        # Порядок координат GeoJSON [lon, lat]
        for node in serialized_payload.nodes:
            self.assertEqual(len(node.position), 2)
            lon, lat = node.position
            self.assertTrue(-180 <= lon <= 180)
            self.assertTrue(-90 <= lat <= 90)

        # Изолированный склад содержит isolation_reason в сериализованных атрибутах
        ser_sea_node = next(n for n in serialized_payload.nodes if n.id == str(sea_rep["warehouse_id"]))
        self.assertTrue(ser_sea_node.attributes["is_isolated"])
        self.assertIn("isolation_reason", ser_sea_node.attributes)


if __name__ == "__main__":
    unittest.main()
