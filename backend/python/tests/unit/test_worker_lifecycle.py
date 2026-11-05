import asyncio
import unittest
import networkx as nx
from shapely.geometry import LineString

from graph_service.kafka import (
    AnalysisWorker,
    MockKafkaTransport,
    KafkaEnvelope,
    CommandType,
    EventType,
    TaskStatus,
    ErrorCode,
)
from graph_service.domain.models import AnalysisResponse, AnalysisStatus
from graph_service.application.cancellation import TaskCancelledException


class DummyAnalysisService:
    """Эмулятор сервиса анализа для быстрого изолированного тестирования воркера."""

    def __init__(self, delay_sec: float = 0.0):
        self.delay_sec = delay_sec
        # Готовим валидный тестовый мультиграф
        self.graph = nx.MultiGraph()
        self.graph.add_node("n1", x=30.25, y=59.90, name="Хаб 1", object_type="warehouse")
        self.graph.add_node("n2", x=30.35, y=59.95, name="Хаб 2", object_type="terminal")
        geom = LineString([(30.25, 59.90), (30.35, 59.95)])
        self.graph.add_edge(
            "n1",
            "n2",
            key="road",
            transport_mode="road",
            route_status_ab="found",
            route_status_ba="found",
            total_distance_ab_m=3500.0,
            road_geometry_ab_wkt=geom.wkt,
        )

    def run_analysis(self, request, cancellation_token=None):
        if self.delay_sec > 0:
            import time
            steps = int(self.delay_sec / 0.05)
            for _ in range(steps):
                time.sleep(0.05)
                if cancellation_token:
                    cancellation_token.check_cancelled()

        if cancellation_token:
            cancellation_token.check_cancelled()

        return AnalysisResponse(
            status=AnalysisStatus.SUCCESS.value,
            graph_object=self.graph,
        )


class TestWorkerLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transport = MockKafkaTransport()
        self.service = DummyAnalysisService()
        self.worker = AnalysisWorker(
            transport=self.transport,
            analysis_service=self.service,
        )

    async def test_worker_full_pipeline_start_to_result(self):
        # Запускаем воркер в фоне
        worker_task = asyncio.create_task(self.worker.start())

        start_cmd = {
            "message_id": "msg-start-001",
            "job_id": "job-101",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 59.90, "longitude": 30.25},
                    "second_point": {"latitude": 59.95, "longitude": 30.35},
                },
                "transports": ["road"],
            },
        }

        # Отправляем команду
        await self.transport.put_test_command("analysis.commands", "job-101", start_cmd)

        # Ждем выполнения вычислений
        await asyncio.sleep(0.3)

        sent = self.transport.get_sent_messages("analysis.results")
        self.assertGreaterEqual(len(sent), 2)

        # 1. Первое сообщение — STATUS: running
        key1, val1 = sent[0]
        self.assertEqual(key1, "job-101")
        self.assertEqual(val1["type"], EventType.STATUS.value)
        self.assertEqual(val1["payload"]["status"], TaskStatus.RUNNING.value)

        # 2. Второе сообщение — RESULT: completed
        key2, val2 = sent[1]
        self.assertEqual(key2, "job-101")
        self.assertEqual(val2["type"], EventType.RESULT.value)
        self.assertEqual(val2["payload"]["status"], TaskStatus.COMPLETED.value)
        self.assertIsNotNone(val2["payload"]["graph"])
        self.assertEqual(len(val2["payload"]["graph"]["nodes"]), 2)
        # Проверка порядка координат [lon, lat]
        self.assertEqual(val2["payload"]["graph"]["nodes"][0]["position"], [30.25, 59.90])
        self.assertGreater(len(val2["payload"]["metrics"]), 0)

        await self.worker.stop()
        worker_task.cancel()

    async def test_worker_unsupported_transport_fails(self):
        worker_task = asyncio.create_task(self.worker.start())

        start_cmd = {
            "message_id": "msg-trans-001",
            "job_id": "job-unsupported",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 59.90, "longitude": 30.25},
                    "second_point": {"latitude": 59.95, "longitude": 30.35},
                },
                "transports": ["road", "sea"],
            },
        }

        await self.transport.put_test_command("analysis.commands", "job-unsupported", start_cmd)
        await asyncio.sleep(0.2)

        sent = self.transport.get_sent_messages("analysis.results")
        self.assertEqual(len(sent), 1)

        key, val = sent[0]
        self.assertEqual(key, "job-unsupported")
        self.assertEqual(val["type"], EventType.RESULT.value)
        self.assertEqual(val["payload"]["status"], TaskStatus.FAILED.value)
        self.assertEqual(val["payload"]["error"]["code"], ErrorCode.UNSUPPORTED_TRANSPORT.value)

        await self.worker.stop()
        worker_task.cancel()

    async def test_worker_cancellation(self):
        slow_service = DummyAnalysisService(delay_sec=0.5)
        worker = AnalysisWorker(
            transport=self.transport,
            analysis_service=slow_service,
        )
        worker_task = asyncio.create_task(worker.start())

        start_cmd = {
            "message_id": "msg-cancel-start",
            "job_id": "job-to-cancel",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 59.90, "longitude": 30.25},
                    "second_point": {"latitude": 59.95, "longitude": 30.35},
                },
                "transports": ["road"],
            },
        }
        await self.transport.put_test_command("analysis.commands", "job-to-cancel", start_cmd)

        # Ждем старта
        await asyncio.sleep(0.1)

        # Отправляем CANCEL
        cancel_cmd = {
            "message_id": "msg-cancel-req",
            "job_id": "job-to-cancel",
            "type": "CANCEL",
            "payload": {},
        }
        await self.transport.put_test_command("analysis.commands", "job-to-cancel", cancel_cmd)

        await asyncio.sleep(0.3)

        sent = self.transport.get_sent_messages("analysis.results")
        statuses = [v["payload"].get("status") for k, v in sent]
        self.assertIn(TaskStatus.RUNNING.value, statuses)
        self.assertIn(TaskStatus.CANCELED.value, statuses)

        await worker.stop()
        worker_task.cancel()

    async def test_worker_idempotency_duplicate_start(self):
        worker_task = asyncio.create_task(self.worker.start())

        start_cmd = {
            "message_id": "msg-idemp-001",
            "job_id": "job-idemp",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 59.90, "longitude": 30.25},
                    "second_point": {"latitude": 59.95, "longitude": 30.35},
                },
                "transports": ["road"],
            },
        }

        # 1-й запуск
        await self.transport.put_test_command("analysis.commands", "job-idemp", start_cmd)
        await asyncio.sleep(0.2)
        count_first = len(self.transport.get_sent_messages("analysis.results"))
        self.assertEqual(count_first, 2)  # running + completed

        # 2-й запуск с тем же message_id
        await self.transport.put_test_command("analysis.commands", "job-idemp", start_cmd)
        await asyncio.sleep(0.1)

        sent = self.transport.get_sent_messages("analysis.results")
        # Должен повторно доставить сохраненный RESULT
        self.assertEqual(len(sent), 3)
        self.assertEqual(sent[-1][1]["type"], EventType.RESULT.value)

        await self.worker.stop()
        worker_task.cancel()

    async def test_manual_commit_strictly_after_result(self):
        """Проверка Issue 1: оффсет коммитится строго после отправки RESULT."""
        slow_service = DummyAnalysisService(delay_sec=0.3)
        worker = AnalysisWorker(
            transport=self.transport,
            analysis_service=slow_service,
        )
        worker_task = asyncio.create_task(worker.start())

        start_cmd = {
            "message_id": "msg-commit-001",
            "job_id": "job-commit",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 59.90, "longitude": 30.25},
                    "second_point": {"latitude": 59.95, "longitude": 30.35},
                },
                "transports": ["road"],
            },
        }

        await self.transport.put_test_command("analysis.commands", "job-commit", start_cmd)

        # Сразу после запуска вычислений оффсет НЕ должен быть закоммичен
        await asyncio.sleep(0.1)
        committed = self.transport.get_committed_messages()
        self.assertEqual(len(committed), 0, "Оффсет не должен коммититься во время выполнения задачи!")

        # Ждем завершения расчета
        await asyncio.sleep(0.4)
        committed = self.transport.get_committed_messages()
        self.assertEqual(len(committed), 1, "Оффсет должен быть закоммичен после завершения задачи")

        results = self.transport.get_sent_messages("analysis.results")
        self.assertTrue(any(v["type"] == EventType.RESULT.value for k, v in results))

        await worker.stop()
        worker_task.cancel()

    async def test_resilience_to_running_status_emit_failure(self):
        """Проверка Issue 2: сбой отправки running не оставляет задачу без вычисления."""
        original_emit = self.worker._emit_status

        async def faulty_emit_status(job_id: str, status: str):
            if status == TaskStatus.RUNNING.value:
                raise ConnectionError("Сбой сети при отправке промежуточного статуса running")
            return await original_emit(job_id, status)

        self.worker._emit_status = faulty_emit_status
        worker_task = asyncio.create_task(self.worker.start())

        start_cmd = {
            "message_id": "msg-resilience-001",
            "job_id": "job-resilience",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 59.90, "longitude": 30.25},
                    "second_point": {"latitude": 59.95, "longitude": 30.35},
                },
                "transports": ["road"],
            },
        }

        await self.transport.put_test_command("analysis.commands", "job-resilience", start_cmd)
        await asyncio.sleep(0.3)

        sent = self.transport.get_sent_messages("analysis.results")
        # Статус RUNNING упал, но RESULT completed должен быть успешно отправлен
        result_events = [v for k, v in sent if v["type"] == EventType.RESULT.value]
        self.assertEqual(len(result_events), 1)
        self.assertEqual(result_events[0]["payload"]["status"], TaskStatus.COMPLETED.value)

        # Оффсет команды также подтвержден
        self.assertGreaterEqual(len(self.transport.get_committed_messages()), 1)

        await self.worker.stop()
        worker_task.cancel()

    async def test_retry_processed_message_without_saved_result(self):
        """Проверка Issue 2: если message_id был зафиксирован, но результат не был сохранен (падение), повтор не теряется."""
        # Имитируем падение: message_id есть в репозитории, но результат пуст
        self.worker.repository.mark_message_processed("msg-lost-001", "job-lost-101")
        self.assertIsNone(self.worker.repository.get_saved_result("job-lost-101"))

        worker_task = asyncio.create_task(self.worker.start())

        start_cmd = {
            "message_id": "msg-lost-001",
            "job_id": "job-lost-101",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 59.90, "longitude": 30.25},
                    "second_point": {"latitude": 59.95, "longitude": 30.35},
                },
                "transports": ["road"],
            },
        }

        # Отправляем повтор команды
        await self.transport.put_test_command("analysis.commands", "job-lost-101", start_cmd)
        await asyncio.sleep(0.3)

        sent = self.transport.get_sent_messages("analysis.results")
        result_events = [v for k, v in sent if v["type"] == EventType.RESULT.value]
        self.assertEqual(len(result_events), 1, "Задача должна быть рассчитана, а не проигнорирована!")
        self.assertEqual(result_events[0]["payload"]["status"], TaskStatus.COMPLETED.value)

        await self.worker.stop()
        worker_task.cancel()

    async def test_poison_pill_does_not_crash_consumer(self):
        """Проверка Issue 3: битый JSON подтверждается (commit) и консьюмер не падает, читая следующие команды."""
        worker_task = asyncio.create_task(self.worker.start())

        # 1. Отправляем "битый" JSON (Poison Pill) в виде байт
        bad_json_bytes = b"BROKEN_JSON_NOT_A_VALID_STRUCTURE{{{"
        await self.transport.put_test_command("analysis.commands", "corrupted-key", bad_json_bytes)

        # 2. Сразу следом отправляем валидную команду START
        valid_cmd = {
            "message_id": "msg-after-poison-001",
            "job_id": "job-after-poison",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 59.90, "longitude": 30.25},
                    "second_point": {"latitude": 59.95, "longitude": 30.35},
                },
                "transports": ["road"],
            },
        }
        await self.transport.put_test_command("analysis.commands", "job-after-poison", valid_cmd)

        # Ждем обработки обоих сообщений
        await asyncio.sleep(0.3)

        # Проверяем, что оффсет битого сообщения был закоммичен, а также оффсет валидного
        committed = self.transport.get_committed_messages()
        self.assertGreaterEqual(len(committed), 2, "Должны быть закоммичены и битое сообщение, и выполненная команда")

        # Проверяем, что валидная команда успешно выполнена (консьюмер не умер на битом JSON)
        sent = self.transport.get_sent_messages("analysis.results")
        result_events = [v for k, v in sent if v["job_id"] == "job-after-poison" and v["type"] == EventType.RESULT.value]
        self.assertEqual(len(result_events), 1)
        self.assertEqual(result_events[0]["payload"]["status"], TaskStatus.COMPLETED.value)

        await self.worker.stop()
        worker_task.cancel()


if __name__ == "__main__":
    unittest.main()

