import unittest
from graph_service.kafka import (
    KafkaEnvelope,
    CommandType,
    EventType,
    TaskStatus,
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
    CommandConsumer,
    EventProducer,
)
from graph_service.http import execute_with_overpass_fallback, OVERPASS_MIRRORS
from graph_service.db import JobRepository, MemoryJobRepository
import graph_service.adapters as legacy_adapters
import graph_service.messaging as legacy_messaging


class TestL3Structure(unittest.TestCase):
    def test_kafka_layer_exports(self):
        envelope = KafkaEnvelope.create(
            job_id="test-job-l3",
            msg_type=EventType.STATUS.value,
            payload={"status": TaskStatus.RUNNING.value},
        )
        self.assertEqual(envelope.job_id, "test-job-l3")
        self.assertEqual(envelope.type, "STATUS")
        self.assertEqual(envelope.payload["status"], "running")

    def test_http_layer_exports(self):
        self.assertIsNotNone(execute_with_overpass_fallback)
        self.assertGreater(len(OVERPASS_MIRRORS), 0)

    def test_db_layer_idempotency_and_state(self):
        repo = MemoryJobRepository()
        self.assertFalse(repo.is_message_processed("msg-001"))

        repo.mark_message_processed("msg-001", "job-100")
        self.assertTrue(repo.is_message_processed("msg-001"))

        state = repo.get_job_state("job-100")
        self.assertIsNotNone(state)
        self.assertEqual(state["status"], "received")

        repo.save_job_state("job-100", "running")
        state = repo.get_job_state("job-100")
        self.assertEqual(state["status"], "running")

        result_dict = {"status": "completed", "graph": {"nodes": [], "edges": []}}
        repo.save_job_state("job-100", "completed", result_envelope=result_dict)
        saved = repo.get_saved_result("job-100")
        self.assertEqual(saved, result_dict)

    def test_backward_compatibility_shims(self):
        self.assertIs(legacy_adapters.execute_with_overpass_fallback, execute_with_overpass_fallback)
        self.assertIs(legacy_messaging.KafkaEnvelope, KafkaEnvelope)
        self.assertIs(legacy_messaging.CommandConsumer, CommandConsumer)


if __name__ == "__main__":
    unittest.main()

