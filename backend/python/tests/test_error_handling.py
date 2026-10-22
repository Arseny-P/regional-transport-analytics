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
        self.service = TerritoryAnalysisService(default_storage_dir="data")

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


if __name__ == "__main__":
    unittest.main()
