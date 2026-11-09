import math
import unittest
from graph_service.kafka import (
    KafkaEnvelope,
    CommandType,
    EventType,
    TaskStatus,
    ErrorCode,
    MapPoint,
    AreaPayload,
    StartCommandPayload,
    CancelCommandPayload,
    StatusEventPayload,
    NodePayload,
    EdgePayload,
    GraphPayload,
    MetricItem,
    ErrorPayload,
    ResultEventPayload,
)


class TestKafkaContract(unittest.TestCase):
    def test_start_command_envelope_and_bounds_parsing(self):
        envelope_data = {
            "message_id": "11111111-1111-4111-8111-111111111111",
            "job_id": "550e8400-e29b-41d4-a716-446655440000",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 59.90, "longitude": 30.25},
                    "second_point": {"latitude": 59.95, "longitude": 30.35},
                },
                "transports": ["road"],
            },
        }

        envelope = KafkaEnvelope.from_dict(envelope_data)
        self.assertEqual(envelope.message_id, "11111111-1111-4111-8111-111111111111")
        self.assertEqual(envelope.job_id, "550e8400-e29b-41d4-a716-446655440000")
        self.assertEqual(envelope.type, CommandType.START.value)

        start_payload = StartCommandPayload.from_dict(envelope.payload)
        west, south, east, north = start_payload.area.to_bounds()
        self.assertEqual(west, 30.25)
        self.assertEqual(south, 59.90)
        self.assertEqual(east, 30.35)
        self.assertEqual(north, 59.95)

        # Проверка допустимости вида транспорта
        start_payload.validate_transports()

    def test_start_command_unsupported_transport(self):
        payload_data = {
            "area": {
                "first_point": {"latitude": 59.90, "longitude": 30.25},
                "second_point": {"latitude": 59.95, "longitude": 30.35},
            },
            "transports": ["road", "rail"],
        }
        start_payload = StartCommandPayload.from_dict(payload_data)
        with self.assertRaises(ValueError) as ctx:
            start_payload.validate_transports()
        self.assertIn("rail", str(ctx.exception))

    def test_invalid_area_coordinates(self):
        # Широта вне диапазона [-90, 90]
        with self.assertRaises(ValueError):
            MapPoint.from_dict({"latitude": 95.0, "longitude": 30.0})

        # Долгота вне диапазона [-180, 180]
        with self.assertRaises(ValueError):
            MapPoint.from_dict({"latitude": 59.0, "longitude": 185.0})

        # Нулевая площадь (одинаковая широта двух противоположных углов)
        with self.assertRaises(ValueError):
            AreaPayload.from_dict({
                "first_point": {"latitude": 59.90, "longitude": 30.25},
                "second_point": {"latitude": 59.90, "longitude": 30.35},
            })

        # Нулевая площадь (одинаковая долгота)
        with self.assertRaises(ValueError):
            AreaPayload.from_dict({
                "first_point": {"latitude": 59.90, "longitude": 30.25},
                "second_point": {"latitude": 59.95, "longitude": 30.25},
            })

    def test_cancel_command_envelope(self):
        envelope_data = {
            "message_id": "33333333-3333-4333-8333-333333333333",
            "job_id": "550e8400-e29b-41d4-a716-446655440000",
            "type": "CANCEL",
            "payload": {},
        }
        envelope = KafkaEnvelope.from_dict(envelope_data)
        self.assertEqual(envelope.type, CommandType.CANCEL.value)
        cancel_payload = CancelCommandPayload.from_dict(envelope.payload)
        self.assertEqual(cancel_payload.to_dict(), {})

    def test_status_event_payload(self):
        running_status = StatusEventPayload(status=TaskStatus.RUNNING.value)
        self.assertEqual(running_status.to_dict(), {"status": "running"})

        canceled_status = StatusEventPayload(status=TaskStatus.CANCELED.value)
        self.assertEqual(canceled_status.to_dict(), {"status": "canceled"})

    def test_result_event_success_format_and_coordinates_order(self):
        # По контракту: position строго [долгота, широта]
        nodes = [
            NodePayload(id="n1", position=[30.28, 59.91], attributes={"name": "Хаб 1"}),
            NodePayload(id="n2", position=[30.31, 59.93], attributes={"name": "Хаб 2"}),
        ]
        # Geometry: список точек [lon, lat]
        edges = [
            EdgePayload(
                id="e1",
                source="n1",
                target="n2",
                geometry=[[30.28, 59.91], [30.29, 59.92], [30.31, 59.93]],
                attributes={"distance_km": 2.5},
            )
        ]
        graph = GraphPayload(nodes=nodes, edges=edges)
        metrics = [
            MetricItem(name="vertex_count", value=2.0),
            MetricItem(name="edge_count", value=1.0),
        ]

        result = ResultEventPayload(
            status=TaskStatus.COMPLETED.value,
            graph=graph,
            metrics=metrics,
        )
        res_dict = result.to_dict()

        self.assertEqual(res_dict["status"], "completed")
        self.assertIsNotNone(res_dict["graph"])
        self.assertEqual(len(res_dict["graph"]["nodes"]), 2)
        # Проверяем [долгота, широта]
        self.assertEqual(res_dict["graph"]["nodes"][0]["position"], [30.28, 59.91])
        self.assertEqual(len(res_dict["metrics"]), 2)

    def test_result_event_metrics_reject_nan_and_inf(self):
        # Защита от NaN
        nan_metric = MetricItem(name="bad_val", value=float("nan"))
        with self.assertRaises(ValueError):
            nan_metric.to_dict()

        # Защита от Infinity
        inf_metric = MetricItem(name="bad_inf", value=float("inf"))
        with self.assertRaises(ValueError):
            inf_metric.to_dict()

    def test_result_event_failed_format(self):
        error = ErrorPayload(
            code=ErrorCode.OSM_UNAVAILABLE.value,
            message="Зеркала Overpass API недоступны",
        )
        result = ResultEventPayload(
            status=TaskStatus.FAILED.value,
            graph=None,
            metrics=[],
            error=error,
        )
        res_dict = result.to_dict()
        self.assertEqual(res_dict["status"], "failed")
        self.assertIsNone(res_dict["graph"])
        self.assertEqual(res_dict["metrics"], [])
        self.assertEqual(res_dict["error"]["code"], "osm_unavailable")


if __name__ == "__main__":
    unittest.main()

