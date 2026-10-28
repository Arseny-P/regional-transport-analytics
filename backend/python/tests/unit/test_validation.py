import unittest
from graph_service.domain import (
    TerritoryBounds,
    TerritoryValidationError,
    FacilityValidationError,
)
from graph_service.algorithms import FacilityService


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.facility_service = FacilityService()

    def test_valid_bbox(self):
        bbox = TerritoryBounds(min_lat=59.90, min_lon=29.60, max_lat=60.10, max_lon=29.90)
        bbox.validate()
        # Проверяем правильный формат OSMnx 2.x: (min_lon, min_lat, max_lon, max_lat)
        self.assertEqual(bbox.to_osmnx_bbox(), (29.60, 59.90, 29.90, 60.10))
        self.assertTrue(bbox.contains(60.00, 29.75))
        self.assertFalse(bbox.contains(61.00, 29.75))
        self.assertTrue(bbox.cache_key().startswith("bbox_59.9000_29.6000"))

    def test_invalid_lat_range(self):
        with self.assertRaises(TerritoryValidationError):
            TerritoryBounds(min_lat=-95.0, min_lon=30.0, max_lat=60.0, max_lon=31.0).validate()

    def test_invalid_lon_range(self):
        with self.assertRaises(TerritoryValidationError):
            TerritoryBounds(min_lat=50.0, min_lon=30.0, max_lat=60.0, max_lon=195.0).validate()

    def test_inverted_coordinates(self):
        with self.assertRaises(TerritoryValidationError):
            TerritoryBounds(min_lat=60.0, min_lon=30.0, max_lat=59.0, max_lon=31.0).validate()

        with self.assertRaises(TerritoryValidationError):
            TerritoryBounds(min_lat=59.0, min_lon=31.0, max_lat=60.0, max_lon=30.0).validate()

    def test_max_span_exceeded(self):
        # Превышение лимита в 2 градуса
        with self.assertRaises(TerritoryValidationError):
            TerritoryBounds(min_lat=50.0, min_lon=30.0, max_lat=55.0, max_lon=31.0).validate(max_lat_span=2.0)

    def test_facility_missing_coordinates(self):
        raw_data = [{"name": "Склад без координат", "type": "warehouse"}]
        with self.assertRaises(FacilityValidationError):
            self.facility_service.parse_and_validate_facilities(raw_data)

    def test_facility_invalid_coordinates_type(self):
        raw_data = [{"name": "Склад", "lat": "not_a_number", "lon": 30.0}]
        with self.assertRaises(FacilityValidationError):
            self.facility_service.parse_and_validate_facilities(raw_data)

    def test_facility_id_deduplication(self):
        raw_data = [
            {"id": "hub_1", "name": "Склад 1", "lat": 59.9, "lon": 30.1},
            {"id": "hub_1", "name": "Склад 2 (дубликат ID)", "lat": 59.95, "lon": 30.2},
            {"name": "Склад 3 (без ID)", "lat": 59.98, "lon": 30.3},
        ]
        nodes = self.facility_service.parse_and_validate_facilities(raw_data)
        self.assertEqual(len(nodes), 3)
        ids = [n.id for n in nodes]
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(ids[0], "hub_1")
        self.assertEqual(ids[1], "hub_1_2")
        self.assertEqual(ids[2], "node_3")


if __name__ == "__main__":
    unittest.main()
