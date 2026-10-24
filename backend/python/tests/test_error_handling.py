import os
import unittest
from models import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    TerritorySourceType,
    FacilitySourceType,
    TerritoryBounds,
)
from services import TerritoryAnalysisService


class TestErrorHandling(unittest.TestCase):
    def setUp(self):
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        self.service = TerritoryAnalysisService(default_storage_dir=data_dir)

    def test_missing_bbox_for_bbox_mode(self):
        req = AnalysisRequest(
            territory_type=TerritorySourceType.BBOX.value,
            bbox=None,
            facility_source=FacilitySourceType.USER_DEFINED.value,
            facilities=[{"name": "Hub 1", "lat": 59.9, "lon": 30.0}],
        )
        res: AnalysisResponse = self.service.run_analysis(req)
        self.assertEqual(res.status, AnalysisStatus.ERROR.value)
        self.assertIn("необходимо передать объект 'bbox'", res.error_message)

    def test_invalid_bbox_coordinates_caught(self):
        req = AnalysisRequest(
            territory_type=TerritorySourceType.BBOX.value,
            bbox=TerritoryBounds(min_lat=60.0, min_lon=30.0, max_lat=50.0, max_lon=31.0),
            facility_source=FacilitySourceType.USER_DEFINED.value,
            facilities=[{"name": "Hub 1", "lat": 59.9, "lon": 30.0}],
        )
        res: AnalysisResponse = self.service.run_analysis(req)
        self.assertEqual(res.status, AnalysisStatus.ERROR.value)
        self.assertIn("min_lat (60.0) должен быть строго меньше max_lat (50.0)", res.error_message)

    def test_empty_user_facilities_error(self):
        req = AnalysisRequest(
            territory_type=TerritorySourceType.PLACE_NAME.value,
            place_name="Кронштадт, Россия",
            facility_source=FacilitySourceType.USER_DEFINED.value,
            facilities=[],
        )
        res: AnalysisResponse = self.service.run_analysis(req)
        self.assertEqual(res.status, AnalysisStatus.ERROR.value)
        self.assertIn("Передан пустой список пользовательских объектов", res.error_message)

    def test_invalid_facilities_structure(self):
        req = AnalysisRequest(
            territory_type=TerritorySourceType.PLACE_NAME.value,
            place_name="Кронштадт, Россия",
            facility_source=FacilitySourceType.USER_DEFINED.value,
            facilities=[{"name": "Broken Hub without coordinates"}],
        )
        res: AnalysisResponse = self.service.run_analysis(req)
        self.assertEqual(res.status, AnalysisStatus.ERROR.value)
        self.assertIn("не содержит обязательных координат", res.error_message)

    def test_overpass_fallback_succeeds_on_second_mirror(self):
        from services.overpass_client import execute_with_overpass_fallback
        from unittest.mock import MagicMock, patch

        mock_func = MagicMock()
        mock_func.side_effect = [ConnectionError("502 Bad Gateway"), "mock_graph"]

        with patch("time.sleep"):
            res = execute_with_overpass_fallback(mock_func, "dummy_arg")
        self.assertEqual(res, "mock_graph")
        self.assertEqual(mock_func.call_count, 2)

    def test_overpass_fallback_fails_when_all_mirrors_fail(self):
        from services.overpass_client import execute_with_overpass_fallback, OVERPASS_MIRRORS
        from unittest.mock import MagicMock, patch

        mock_func = MagicMock(side_effect=TimeoutError("Request timed out"))

        with patch("time.sleep"):
            with self.assertRaises(RuntimeError) as ctx:
                execute_with_overpass_fallback(mock_func)

        self.assertEqual(mock_func.call_count, len(OVERPASS_MIRRORS))
        self.assertIn("Все доступные зеркала Overpass API завершились ошибкой", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

