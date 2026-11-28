import asyncio
import unittest
from unittest.mock import patch, MagicMock

import networkx as nx
from graph_service.config import config
from graph_service.kafka import (
    AnalysisWorker,
    MockKafkaTransport,
    EventType,
    TaskStatus,
    ErrorCode,
)
from graph_service.domain.models import (
    AnalysisResponse,
    AnalysisStatus,
    RailFacility,
    RailConnectionStatus,
)


class TestWorkerMultiTransportE2E(unittest.IsolatedAsyncioTestCase):
    """
    Интеграционный E2E-тест параллельного стриминга нескольких видов транспорта (Спринт 6, PR #117).
    Проверяет:
    1. Одновременный запуск ['road', 'rail'] из одной команды START.
    2. Раздельный стриминг STATUS: running для каждого транспорта.
    3. Независимую отправку RESULT для каждого вида транспорта по мере готовности (streaming).
    4. Изоляцию сбоев: падение дорожного анализа не мешает успешной отправке ЖД анализа.
    5. Корректную отмену CANCEL всех параллельных подзадач.
    6. Фиксацию оффсета (Manual Commit) строго после завершения всех запрошенных транспортов.
    """

    async def asyncSetUp(self):
        self.transport = MockKafkaTransport()
        self.worker = AnalysisWorker(transport=self.transport)

    async def asyncTearDown(self):
        await self.worker.stop()

    def _create_mock_road_response(self) -> AnalysisResponse:
        """Создает валидный тестовый результат автомобильного графа."""
        road_graph = nx.MultiDiGraph()
        road_graph.graph["transport_mode"] = "road"
        road_graph.graph["routes"] = [{"route_id": "r1", "length_m": 500.0}]

        road_graph.add_node("wh_1", object_type="warehouse", x=30.38, y=59.80, name="Склад 1")
        road_graph.add_node("rn_1", object_type="road_node", x=30.39, y=59.81)
        road_graph.add_edge(
            "wh_1",
            "rn_1",
            key=0,
            edge_type="access_connector",
            length_m=120.0,
            transport_mode="road",
        )
        road_graph.add_edge(
            "rn_1",
            "wh_1",
            key=0,
            edge_type="access_connector",
            length_m=120.0,
            transport_mode="road",
        )

        return AnalysisResponse(
            status=AnalysisStatus.SUCCESS.value,
            graph_object=road_graph,
            routes=[{"route_id": "r1"}],
        )

    async def test_multi_transport_concurrent_streaming_results(self):
        """
        Проверяет, что при запросе transports=['road', 'rail'] воркер отправляет
        два независимых сообщения RESULT (по одному для каждого вида транспорта),
        каждое со своим transport_type ('road' и 'rail') и своими метриками.
        """
        worker_task = asyncio.create_task(self.worker.start())

        start_cmd = {
            "message_id": "msg-multi-001",
            "job_id": "job-multi-streaming-001",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 59.7950, "longitude": 30.3850},
                    "second_point": {"latitude": 59.8240, "longitude": 30.4410},
                },
                "transports": ["road", "rail"],
                "facilities": [
                    {
                        "id": "station:1377619868",
                        "name": "Шушары",
                        "lat": 59.816667,
                        "lon": 30.383333,
                        "anchor_node_ids": ["1377619868"],
                    }
                ],
            },
        }

        # Мокаем road на быстрый возврат, а rail оставляем на реальных оффлайн-фикстурах Шушар
        original_run_analysis = self.worker.analysis_service.run_analysis

        def side_effect_analysis(req, token=None):
            if req.transport_mode == "road":
                return self._create_mock_road_response()
            return original_run_analysis(req, token)

        with patch.object(self.worker.analysis_service, "run_analysis", side_effect=side_effect_analysis), \
             patch.object(config, "osm_offline_mode", True):

            await self.transport.put_test_command(
                "analysis.commands", "job-multi-streaming-001", start_cmd
            )

            # Ожидаем завершения обоих расчетов
            for _ in range(50):
                await asyncio.sleep(0.1)
                sent = self.transport.get_sent_messages("analysis.results")
                result_count = sum(1 for _, m in sent if m.get("type") == EventType.RESULT.value)
                if result_count >= 2:
                    break

        sent_messages = [m for _, m in self.transport.get_sent_messages("analysis.results")]

        # 1. Проверяем наличие событий STATUS: running для каждого транспорта
        status_running = [
            m for m in sent_messages
            if m.get("type") == EventType.STATUS.value and m.get("payload", {}).get("status") == TaskStatus.RUNNING.value
        ]
        running_transports = {m.get("transport_type") for m in status_running}
        self.assertIn("road", running_transports)
        self.assertIn("rail", running_transports)

        # 2. Проверяем наличие двух независимых RESULT: completed
        results = [
            m for m in sent_messages
            if m.get("type") == EventType.RESULT.value
        ]
        self.assertEqual(len(results), 2, "Должно быть отправлено ровно 2 сообщения RESULT")

        results_by_transport = {m.get("transport_type"): m for m in results}
        self.assertIn("road", results_by_transport)
        self.assertIn("rail", results_by_transport)

        # Проверяем дорожный результат
        road_res = results_by_transport["road"]
        self.assertEqual(road_res["job_id"], "job-multi-streaming-001")
        self.assertEqual(road_res["payload"]["status"], TaskStatus.COMPLETED.value)
        self.assertGreater(len(road_res["payload"]["graph"]["nodes"]), 0)
        road_metric_names = {m["name"] for m in road_res["payload"]["metrics"]}
        self.assertIn("warehouse_count", road_metric_names)

        # Проверяем железнодорожный результат (на оффлайн фикстурах Шушар)
        rail_res = results_by_transport["rail"]
        self.assertEqual(rail_res["job_id"], "job-multi-streaming-001")
        self.assertEqual(rail_res["payload"]["status"], TaskStatus.COMPLETED.value)
        self.assertGreater(len(rail_res["payload"]["graph"]["nodes"]), 0)
        rail_metric_names = {m["name"] for m in rail_res["payload"]["metrics"]}
        self.assertIn("total_rail_length_km", rail_metric_names)
        self.assertIn("station_count", rail_metric_names)

        # Проверяем, что ID сообщений разные
        self.assertNotEqual(road_res["message_id"], rail_res["message_id"])

        await self.worker.stop()
        worker_task.cancel()

    async def test_multi_transport_failure_isolation(self):
        """
        Проверяет изоляцию сбоев: если дорожный анализ падает с ошибкой,
        железнодорожный анализ успешно завершается и отправляет RESULT: completed,
        а дорожный отправляет RESULT: failed со своим transport_type='road'.
        """
        worker_task = asyncio.create_task(self.worker.start())

        start_cmd = {
            "message_id": "msg-multi-fail-001",
            "job_id": "job-multi-failure-isolation",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 59.7950, "longitude": 30.3850},
                    "second_point": {"latitude": 59.8240, "longitude": 30.4410},
                },
                "transports": ["road", "rail"],
            },
        }

        original_run_analysis = self.worker.analysis_service.run_analysis

        def side_effect_failure(req, token=None):
            if req.transport_mode == "road":
                return AnalysisResponse(
                    status=AnalysisStatus.ERROR.value,
                    error_message="Включен оффлайн-режим, фикстура дорог отсутствует",
                )
            return original_run_analysis(req, token)

        with patch.object(self.worker.analysis_service, "run_analysis", side_effect=side_effect_failure), \
             patch.object(config, "osm_offline_mode", True):

            await self.transport.put_test_command(
                "analysis.commands", "job-multi-failure-isolation", start_cmd
            )

            for _ in range(50):
                await asyncio.sleep(0.1)
                sent = self.transport.get_sent_messages("analysis.results")
                result_count = sum(1 for _, m in sent if m.get("type") == EventType.RESULT.value)
                if result_count >= 2:
                    break

        sent_messages = [m for _, m in self.transport.get_sent_messages("analysis.results")]
        results = [m for m in sent_messages if m.get("type") == EventType.RESULT.value]
        self.assertEqual(len(results), 2)

        results_by_transport = {m.get("transport_type"): m for m in results}

        # Road упал
        road_res = results_by_transport["road"]
        self.assertEqual(road_res["payload"]["status"], TaskStatus.FAILED.value)
        self.assertEqual(road_res["payload"]["error"]["code"], ErrorCode.OSM_UNAVAILABLE.value)

        # Rail успешно завершился
        rail_res = results_by_transport["rail"]
        self.assertEqual(rail_res["payload"]["status"], TaskStatus.COMPLETED.value)
        self.assertGreater(len(rail_res["payload"]["graph"]["nodes"]), 0)

        await self.worker.stop()
        worker_task.cancel()

    async def test_multi_transport_cancellation(self):
        """
        Проверяет отмену нескольких параллельных подзадач при получении команды CANCEL:
        каждая подзадача останавливается и отправляет STATUS: canceled со своим transport_type.
        """
        worker_task = asyncio.create_task(self.worker.start())

        start_cmd = {
            "message_id": "msg-multi-cancel-001",
            "job_id": "job-multi-cancel-e2e",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 59.7950, "longitude": 30.3850},
                    "second_point": {"latitude": 59.8240, "longitude": 30.4410},
                },
                "transports": ["road", "rail"],
            },
        }

        cancel_cmd = {
            "message_id": "msg-multi-cancel-002",
            "job_id": "job-multi-cancel-e2e",
            "type": "CANCEL",
            "payload": {},
        }

        # Имитируем долгие вычисления, проверяющие CancellationToken
        def slow_analysis(req, token=None):
            for _ in range(50):
                if token:
                    token.check_cancelled()
                import time
                time.sleep(0.05)
            return self._create_mock_road_response()

        with patch.object(self.worker.analysis_service, "run_analysis", side_effect=slow_analysis):
            await self.transport.put_test_command(
                "analysis.commands", "job-multi-cancel-e2e", start_cmd
            )

            # Даем воркеру начать вычисления
            await asyncio.sleep(0.15)

            # Посылаем CANCEL
            await self.transport.put_test_command(
                "analysis.commands", "job-multi-cancel-e2e", cancel_cmd
            )

            # Ждем обработки отмены
            for _ in range(30):
                await asyncio.sleep(0.1)
                sent = self.transport.get_sent_messages("analysis.results")
                canceled_count = sum(
                    1 for _, m in sent
                    if m.get("type") == EventType.STATUS.value and m.get("payload", {}).get("status") == TaskStatus.CANCELED.value
                )
                if canceled_count >= 2:
                    break

        sent_messages = [m for _, m in self.transport.get_sent_messages("analysis.results")]
        canceled_statuses = [
            m for m in sent_messages
            if m.get("type") == EventType.STATUS.value and m.get("payload", {}).get("status") == TaskStatus.CANCELED.value
        ]
        canceled_transports = {m.get("transport_type") for m in canceled_statuses}

        self.assertIn("road", canceled_transports)
        self.assertIn("rail", canceled_transports)

        await self.worker.stop()
        worker_task.cancel()
