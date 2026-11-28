import asyncio
import unittest
from unittest.mock import patch
import pytest

from graph_service.config import config
from graph_service.kafka import (
    AnalysisWorker,
    MockKafkaTransport,
    EventType,
    TaskStatus,
    ErrorCode,
)


class TestWorkerRailE2EOffline(unittest.IsolatedAsyncioTestCase):
    """
    Интеграционный сквозной (E2E) тест Kafka-воркера для анализа железнодорожной сети
    в оффлайн-режиме (OSM_OFFLINE_MODE=True).

    Проверяет:
    1. Запуск реального воркера с MockKafkaTransport.
    2. Прием команды START с transports=['rail'] и координатами BBOX Шушар.
    3. Построение ЖД-графа, топологическое сжатие, расчет 5 согласованных метрик MVP (Sprint 6)
       без единого сетевого запроса к Overpass OSM (100% на предзагруженных фикстурах).
    4. Отправку промежуточного статуса STATUS (running).
    5. Отправку финального RESULT (completed) с графом (86 узлов, 180 рёбер) и метриками.
    6. Строгое соответствие DTO: отсутствие 'edge_type', наличие segment_id, transport_mode='rail'.
    7. Контролируемый отказ (ErrorCode.OSM_UNAVAILABLE) при отсутствии фикстуры для неизвестной территории.
    8. Отказ при попытке запуска смешанного режима (transports=['road', 'rail']).
    """

    async def asyncSetUp(self):
        self.transport = MockKafkaTransport()
        self.worker = AnalysisWorker(transport=self.transport)

    async def asyncTearDown(self):
        await self.worker.stop()

    async def test_worker_rail_full_pipeline_offline_shushary(self):
        """
        Тестирует полный цикл железнодорожного анализа:
        START -> STATUS (running) -> RESULT (completed с ЖД-графом и 5 метриками).
        """
        worker_task = asyncio.create_task(self.worker.start())

        # BBOX Шушар: [30.385, 59.795, 30.441, 59.824]
        start_cmd = {
            "message_id": "msg-rail-e2e-shushary-001",
            "job_id": "job-rail-shushary-e2e",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 59.7950, "longitude": 30.3850},
                    "second_point": {"latitude": 59.8240, "longitude": 30.4410},
                },
                "transports": ["rail"],
            },
        }

        with patch.object(config, "osm_offline_mode", True):
            # Мокаем сетевой запрос к Overpass для гарантии 0 сетевых вызовов
            with patch("graph_service.algorithms.rail_network_service.query_overpass_json") as mock_overpass:
                await self.transport.put_test_command("analysis.commands", "job-rail-shushary-e2e", start_cmd)

                # Ожидаем обработку задачи воркером
                for _ in range(50):
                    await asyncio.sleep(0.1)
                    sent = self.transport.get_sent_messages("analysis.results")
                    if len(sent) >= 2 and sent[-1][1]["type"] == EventType.RESULT.value:
                        break

                mock_overpass.assert_not_called()

        sent = self.transport.get_sent_messages("analysis.results")
        self.assertGreaterEqual(len(sent), 2, "Ожидалось минимум 2 сообщения (STATUS + RESULT)")

        # 1. Проверяем промежуточный статус RUNNING
        key1, status_msg = sent[0]
        self.assertEqual(key1, "job-rail-shushary-e2e")
        self.assertEqual(status_msg["type"], EventType.STATUS.value)
        self.assertEqual(status_msg["payload"]["status"], TaskStatus.RUNNING.value)

        # 2. Проверяем финальный RESULT
        key2, result_msg = sent[1]
        self.assertEqual(key2, "job-rail-shushary-e2e")
        self.assertEqual(result_msg["type"], EventType.RESULT.value)
        result_payload = result_msg["payload"]
        self.assertEqual(result_payload["status"], TaskStatus.COMPLETED.value)
        self.assertNotIn("error", result_payload)

        # 3. Проверяем структуру и объем графа
        graph = result_payload.get("graph")
        self.assertIsNotNone(graph, "Граф должен присутствовать в payload результата")
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])

        # Ориентир Шушар после топологического сжатия: 86 вершин, 180 направленных рёбер (90 physical * 2)
        self.assertEqual(len(nodes), 86, "Граф Шушар должен содержать ровно 86 вершин")
        self.assertEqual(len(edges), 180, "Граф Шушар должен содержать ровно 180 направленных рёбер")

        # Проверка атрибутов вершин
        node_kinds = {n.get("attributes", {}).get("node_kind") for n in nodes}
        self.assertIn("switch", node_kinds)
        self.assertIn("boundary", node_kinds)

        for node in nodes:
            attrs = node.get("attributes", {})
            self.assertEqual(attrs.get("transport_mode"), "rail")
            self.assertIn(attrs.get("object_type"), {"rail_node", "rail_facility"})
            pos = node.get("position", [])
            self.assertEqual(len(pos), 2)
            self.assertTrue(30.38 <= pos[0] <= 30.45)
            self.assertTrue(59.79 <= pos[1] <= 59.83)

        # Проверка атрибутов рёбер
        for edge in edges:
            attrs = edge.get("attributes", {})
            self.assertEqual(attrs.get("transport_mode"), "rail")
            self.assertIn("length_m", attrs)
            self.assertGreater(attrs["length_m"], 0.0)
            self.assertIn("segment_id", edge)
            self.assertTrue(edge["segment_id"].startswith("segment:"))
            # СТРОГО: у ЖД-рёбер отсутствует edge_type
            self.assertNotIn("edge_type", attrs)
            # Геометрия направлена от source к target
            geom = edge.get("geometry", [])
            self.assertGreaterEqual(len(geom), 2)

        # 4. Проверка метрик (5 согласованных показателей MVP Sprint 6)
        metrics = result_payload.get("metrics", [])
        self.assertGreater(len(metrics), 0, "Метрики должны быть рассчитаны")

        regional_metrics = {m["name"]: m["value"] for m in metrics if m.get("node_id") is None}
        self.assertIn("total_rail_length_km", regional_metrics)
        self.assertAlmostEqual(regional_metrics["total_rail_length_km"], 25.750071, places=3)

        self.assertIn("switch_count", regional_metrics)
        self.assertEqual(regional_metrics["switch_count"], 36.0)

        self.assertIn("station_count", regional_metrics)
        self.assertEqual(regional_metrics["station_count"], 0.0)

        # Метрики стрелок: betweenness_centrality для каждого switch_id
        switch_metrics = [
            m for m in metrics
            if m["name"] == "betweenness_centrality" and m.get("node_id") is not None
        ]
        self.assertEqual(len(switch_metrics), 36, "Должно быть ровно 36 метрик betweenness_centrality для стрелок")
        for sm in switch_metrics:
            self.assertGreaterEqual(sm["value"], 0.0)
            self.assertLessEqual(sm["value"], 1.0)

        await self.worker.stop()
        worker_task.cancel()

    async def test_worker_rail_offline_fails_fast_on_missing_fixtures(self):
        """
        Проверяет быстрый и контролируемый фейл с OSM_UNAVAILABLE при отсутствии
        оффлайн-фикстур для неизвестной территории.
        """
        worker_task = asyncio.create_task(self.worker.start())

        unknown_cmd = {
            "message_id": "msg-rail-unknown-001",
            "job_id": "job-rail-unknown-e2e",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 10.0, "longitude": 10.0},
                    "second_point": {"latitude": 10.1, "longitude": 10.1},
                },
                "transports": ["rail"],
            },
        }

        with patch.object(config, "osm_offline_mode", True):
            await self.transport.put_test_command("analysis.commands", "job-rail-unknown-e2e", unknown_cmd)

            for _ in range(30):
                await asyncio.sleep(0.1)
                sent = self.transport.get_sent_messages("analysis.results")
                if len(sent) >= 2 and sent[-1][1]["type"] == EventType.RESULT.value:
                    break

        sent = self.transport.get_sent_messages("analysis.results")
        self.assertGreaterEqual(len(sent), 2)
        _, result_msg = sent[1]
        self.assertEqual(result_msg["type"], EventType.RESULT.value)
        self.assertEqual(result_msg["payload"]["status"], TaskStatus.FAILED.value)
        self.assertEqual(result_msg["payload"]["error"]["code"], ErrorCode.OSM_UNAVAILABLE.value)

        await self.worker.stop()
        worker_task.cancel()

    async def test_worker_rail_rejects_mixed_transports(self):
        """
        Проверяет, что смешанный запрос (['road', 'rail']) отклоняется
        с ошибкой UNSUPPORTED_TRANSPORT по контракту.
        """
        worker_task = asyncio.create_task(self.worker.start())

        mixed_cmd = {
            "message_id": "msg-rail-mixed-001",
            "job_id": "job-rail-mixed-e2e",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 59.7950, "longitude": 30.3850},
                    "second_point": {"latitude": 59.8240, "longitude": 30.4410},
                },
                "transports": ["road", "rail"],
            },
        }

        await self.transport.put_test_command("analysis.commands", "job-rail-mixed-e2e", mixed_cmd)

        for _ in range(30):
            await asyncio.sleep(0.1)
            sent = self.transport.get_sent_messages("analysis.results")
            if len(sent) >= 1 and sent[-1][1]["type"] == EventType.RESULT.value:
                break

        sent = self.transport.get_sent_messages("analysis.results")
        self.assertGreaterEqual(len(sent), 1)
        _, result_msg = sent[0]
        self.assertEqual(result_msg["type"], EventType.RESULT.value)
        self.assertEqual(result_msg["payload"]["status"], TaskStatus.FAILED.value)
        self.assertEqual(result_msg["payload"]["error"]["code"], ErrorCode.UNSUPPORTED_TRANSPORT.value)

        await self.worker.stop()
        worker_task.cancel()
