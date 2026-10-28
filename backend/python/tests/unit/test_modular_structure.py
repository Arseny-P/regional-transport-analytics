import unittest
from graph_service.domain import (
    TerritoryBounds,
    LogisticsNode,
    LogisticsEdge,
    AnalysisRequest,
    AnalysisResponse,
)
from graph_service.application import BuildGraphUseCase, TerritoryAnalysisService
from graph_service.algorithms import RoadNetworkService, FacilityService, LogisticsGraphService
from graph_service.adapters import execute_with_overpass_fallback, OVERPASS_MIRRORS
from graph_service.messaging import (
    KafkaEnvelope,
    CommandType,
    EventType,
    TaskStatus,
    MapPoint,
    AreaPayload,
    StartCommandPayload,
    CancelCommandPayload,
    ResultEventPayload,
    MetricItem,
)


class TestModularStructure(unittest.TestCase):
    def test_domain_models_import_and_init(self):
        bounds = TerritoryBounds(min_lat=59.0, min_lon=30.0, max_lat=60.0, max_lon=31.0)
        self.assertEqual(bounds.to_osmnx_bbox(), (30.0, 59.0, 31.0, 60.0))

        node = LogisticsNode(
            id="n1",
            name="Test Node",
            object_type="warehouse",
            latitude=59.5,
            longitude=30.5,
        )
        self.assertEqual(node.name, "Test Node")
        self.assertEqual(node["lat"], 59.5)

    def test_application_use_case_aliases(self):
        self.assertIs(BuildGraphUseCase, TerritoryAnalysisService)

    def test_messaging_schemas_envelope(self):
        envelope = KafkaEnvelope.create(
            job_id="job-123",
            msg_type=EventType.STATUS.value,
            payload={"status": TaskStatus.RUNNING.value},
        )
        self.assertEqual(envelope.job_id, "job-123")
        self.assertEqual(envelope.type, "STATUS")
        self.assertEqual(envelope.payload["status"], "running")
        self.assertIsNotNone(envelope.message_id)

    def test_area_payload_to_bounds_calculation(self):
        p1 = MapPoint(latitude=59.95, longitude=30.25)
        p2 = MapPoint(latitude=59.90, longitude=30.35)
        area = AreaPayload(first_point=p1, second_point=p2)

        west, south, east, north = area.to_bounds()
        self.assertEqual(west, 30.25)
        self.assertEqual(east, 30.35)
        self.assertEqual(south, 59.90)
        self.assertEqual(north, 59.95)


if __name__ == "__main__":
    unittest.main()
