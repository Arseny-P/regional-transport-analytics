import os
import json
import unittest
import networkx as nx

from graph_service.domain import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    TerritorySourceType,
    FacilitySourceType,
    TerritoryBounds,
)
from graph_service.application import TerritoryAnalysisService
from graph_service.algorithms import LogisticsGraphService


class TestPipelineOffline(unittest.TestCase):
    def setUp(self):
        curr = os.path.dirname(os.path.abspath(__file__))
        while curr and not os.path.exists(os.path.join(curr, "data")):
            parent = os.path.dirname(curr)
            if parent == curr:
                break
            curr = parent
        self.data_dir = os.path.join(curr, "data")
        self.service = TerritoryAnalysisService(default_storage_dir=self.data_dir)
        self.logistics_service = LogisticsGraphService(storage_dir=self.data_dir)

        # Загружаем проверенные объекты Кронштадта
        points_path = os.path.join(self.data_dir, "test_logistics_points.json")
        with open(points_path, "r", encoding="utf-8") as f:
            self.points = json.load(f)

    def test_offline_pipeline_execution(self):
        """
        Проверяет сквозное выполнение анализа на локальном кэше дорожной сети без обращения к OSM.
        """
        alias = "test_offline_kronshtadt"
        req = AnalysisRequest(
            territory_type=TerritorySourceType.PLACE_NAME.value,
            place_name="Кронштадт, Россия",
            output_alias=alias,
            facility_source=FacilitySourceType.USER_DEFINED.value,
            facilities=self.points,
            knn=2,
            save_artifacts=True,
            include_geojson_payload=True,
            refetch=False,
        )

        response: AnalysisResponse = self.service.run_analysis(req)

        # 1. Проверка общего статуса
        self.assertEqual(response.status, AnalysisStatus.SUCCESS.value)
        self.assertIsNone(response.error_message)

        # 2. Проверка сводки (Summary)
        summary = response.summary
        self.assertEqual(summary["total_hubs"], 5)
        self.assertEqual(summary["isolated_hubs_count"], 0)
        self.assertGreater(summary["total_connections"], 0)
        self.assertGreater(summary["avg_route_distance_km"], 0.0)

        # 3. Проверка артефактов
        graphml_path = response.artifacts["logistics_graphml"]
        geojson_path = response.artifacts["logistics_geojson"]
        self.assertTrue(os.path.exists(graphml_path))
        self.assertTrue(os.path.exists(geojson_path))

        # 4. Проверка структуры связей (connections)
        self.assertGreater(len(response.connections), 0)
        for conn in response.connections:
            self.assertEqual(conn["route_status_ab"], "found")
            self.assertEqual(conn["route_status_ba"], "found")
            self.assertGreater(conn["total_distance_ab_km"], 0.0)
            self.assertGreater(conn["total_distance_ba_km"], 0.0)

        # 5. Проверка слоев GeoJSON
        geojson = response.geojson
        self.assertIsNotNone(geojson)
        self.assertEqual(geojson.get("type"), "FeatureCollection")
        feature_types = {f["properties"].get("feature_type") for f in geojson["features"]}
        self.assertIn("logistics_hub", feature_types)
        self.assertIn("transport_route", feature_types)
        self.assertIn("access_connector", feature_types)

        # 6. Проверка оффлайн-восстановления из GraphML
        restored_graph = self.logistics_service.load_graphml(filename=f"{alias}_logistics")
        self.assertEqual(len(restored_graph.nodes), summary["total_hubs"])
        self.assertEqual(len(restored_graph.edges), summary["total_connections"])


if __name__ == "__main__":
    unittest.main()
