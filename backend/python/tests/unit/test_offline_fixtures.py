import os
import unittest
from unittest.mock import patch

from graph_service.config import config
from graph_service.domain.models import (
    AnalysisRequest,
    AnalysisStatus,
    TerritorySourceType,
    FacilitySourceType,
    TerritoryBounds,
)
from graph_service.domain.errors import OfflineDataNotFoundError
from graph_service.application.build_graph import TerritoryAnalysisService
from graph_service.fixtures import find_fixture_files


class TestOfflineFixtures(unittest.TestCase):
    """
    Тесты для оффлайн-режима воркера и поиска фикстур (для E2E в CI).
    """

    def setUp(self):
        self.service = TerritoryAnalysisService()
        self.kronshtadt_bbox = TerritoryBounds(
            min_lat=59.9700,
            min_lon=29.7000,
            max_lat=60.0300,
            max_lon=29.8500,
        )

    def test_find_fixture_files_helper(self):
        """
        Проверяет, что хелпер find_fixture_files корректно находит фикстуры дорог и объектов.
        """
        road_path, fac_path = find_fixture_files("bbox_59.9700_29.7000_60.0300_29.8500")
        self.assertIsNotNone(road_path)
        self.assertIsNotNone(fac_path)
        self.assertTrue(os.path.exists(road_path))
        self.assertTrue(os.path.exists(fac_path))

    def test_analysis_runs_completely_offline_with_fixtures(self):
        """
        Проверяет, что при OSM_OFFLINE_MODE=True полный анализ территории
        выполняется успешно без единого обращения к внешнему Overpass API.
        """
        req = AnalysisRequest(
            territory_type=TerritorySourceType.BBOX.value,
            bbox=self.kronshtadt_bbox,
            facility_source=FacilitySourceType.OSM.value,
            save_artifacts=False,
            refetch=False,
        )

        with patch.object(config, "osm_offline_mode", True):
            # Мокаем execute_with_overpass_fallback, чтобы гарантировать:
            # в оффлайн-режиме функция Overpass НИ РАЗУ не вызывается!
            with patch("graph_service.algorithms.road_network_service.execute_with_overpass_fallback") as mock_road_net, \
                 patch("graph_service.algorithms.facility_service.execute_with_overpass_fallback") as mock_fac_net:

                response = self.service.run_analysis(req)

                # Сеть не должна была вызываться вообще
                mock_road_net.assert_not_called()
                mock_fac_net.assert_not_called()

                self.assertEqual(response.status, AnalysisStatus.SUCCESS.value)
                self.assertIsNotNone(response.graph_object)
                self.assertGreater(len(response.graph_object.nodes), 0)
                self.assertGreater(len(response.graph_object.edges), 0)

    def test_offline_mode_fails_fast_when_fixture_missing(self):
        """
        Проверяет, что при отсутствии фикстуры в режиме OSM_OFFLINE_MODE
        сервис немедленно возвращает понятную ошибку без попыток уйти в сеть.
        """
        unknown_bbox = TerritoryBounds(
            min_lat=10.0,
            min_lon=10.0,
            max_lat=10.1,
            max_lon=10.1,
        )
        req = AnalysisRequest(
            territory_type=TerritorySourceType.BBOX.value,
            bbox=unknown_bbox,
            facility_source=FacilitySourceType.OSM.value,
            save_artifacts=False,
            refetch=False,
        )

        # Мокаем find_fixture_files так, будто для этого BBox ничего нет
        with patch.object(config, "osm_offline_mode", True), \
             patch("graph_service.fixtures.find_fixture_files", return_value=(None, None)), \
             patch("graph_service.algorithms.facility_service.find_fixture_files", return_value=(None, None)):

            with patch("graph_service.algorithms.road_network_service.execute_with_overpass_fallback") as mock_road_net, \
                 patch("graph_service.algorithms.facility_service.execute_with_overpass_fallback") as mock_fac_net:

                response = self.service.run_analysis(req)

                mock_road_net.assert_not_called()
                mock_fac_net.assert_not_called()

                self.assertEqual(response.status, AnalysisStatus.ERROR.value)
                self.assertIn("оффлайн-режим", response.error_message)


if __name__ == "__main__":
    unittest.main()
