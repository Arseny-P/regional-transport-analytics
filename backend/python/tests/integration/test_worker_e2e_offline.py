import asyncio
import os
import unittest
from unittest.mock import patch

from graph_service.config import config
from graph_service.kafka import (
    AnalysisWorker,
    MockKafkaTransport,
    EventType,
    TaskStatus,
    ErrorCode,
)


class TestWorkerE2EOffline(unittest.IsolatedAsyncioTestCase):
    """
    Интеграционный E2E-тест Kafka-воркера в оффлайн-режиме (OSM_OFFLINE_MODE=True).
    Проверяет:
    1. Запуск реального воркера с MockKafkaTransport.
    2. Прием команды START с координатами тестовой территории (Кронштадт).
    3. Построение реального графа, снаппинг, расчет маршрутов и графовых метрик (Sprint 5)
       без единого сетевого запроса к Overpass OSM (только предзагруженные фикстуры).
    4. Отправку промежуточного статуса STATUS (running).
    5. Отправку финального RESULT (completed) с графом и метриками.
    6. Корректную валидацию физических segment_id и структуры метрик.
    7. Быстрый и контролируемый фейл при отсутствии фикстуры для неизвестной территории.
    """

    async def asyncSetUp(self):
        self.transport = MockKafkaTransport()
        self.worker = AnalysisWorker(transport=self.transport)

    async def asyncTearDown(self):
        await self.worker.stop()

    async def test_worker_full_pipeline_offline_with_kronstadt_fixtures(self):
        """
        Тестирует полный рабочий цикл: команда START -> статус running -> результат completed с графом и метриками.
        Вся работа идет 100% оффлайн на фикстурах Кронштадта.
        """
        worker_task = asyncio.create_task(self.worker.start())

        # Координаты тестовой территории (Кронштадт)
        # BBox: [59.9700, 29.7000, 60.0300, 29.8500]
        start_cmd = {
            "message_id": "msg-e2e-kronshtadt-001",
            "job_id": "job-kronshtadt-e2e",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 59.9700, "longitude": 29.7000},
                    "second_point": {"latitude": 60.0300, "longitude": 29.8500},
                },
                "transports": ["road"],
            },
        }

        with patch.object(config, "osm_offline_mode", True):
            # Мокаем вызовы к Overpass, чтобы гарантировать: 0 сетевых запросов
            with patch("graph_service.algorithms.road_network_service.execute_with_overpass_fallback") as mock_road_net, \
                 patch("graph_service.algorithms.facility_service.execute_with_overpass_fallback") as mock_fac_net:

                await self.transport.put_test_command("analysis.commands", "job-kronshtadt-e2e", start_cmd)

                # Ждем пока воркер обработает задачу
                for _ in range(50):
                    await asyncio.sleep(0.1)
                    sent = self.transport.get_sent_messages("analysis.results")
                    if len(sent) >= 2 and sent[-1][1]["type"] == EventType.RESULT.value:
                        break

                mock_road_net.assert_not_called()
                mock_fac_net.assert_not_called()

        sent = self.transport.get_sent_messages("analysis.results")
        self.assertGreaterEqual(len(sent), 2, "Ожидалось как минимум 2 сообщения (STATUS + RESULT)")

        # 1. Проверяем промежуточный статус RUNNING
        key1, status_msg = sent[0]
        self.assertEqual(key1, "job-kronshtadt-e2e")
        self.assertEqual(status_msg["type"], EventType.STATUS.value)
        self.assertEqual(status_msg["payload"]["status"], TaskStatus.RUNNING.value)

        # 2. Проверяем финальный RESULT
        key2, result_msg = sent[1]
        self.assertEqual(key2, "job-kronshtadt-e2e")
        self.assertEqual(result_msg["type"], EventType.RESULT.value)
        result_payload = result_msg["payload"]
        self.assertEqual(result_payload["status"], TaskStatus.COMPLETED.value)
        self.assertNotIn("error", result_payload)

        # 3. Проверяем граф
        graph = result_payload.get("graph")
        self.assertIsNotNone(graph, "Граф должен присутствовать в payload результата")
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        self.assertGreater(len(nodes), 0, "Граф должен содержать узлы")
        self.assertGreater(len(edges), 0, "Граф должен содержать рёбра")

        # Проверяем наличие складов и дорожных перекрестков среди узлов
        node_types = {
            n.get("attributes", {}).get("object_type")
            for n in nodes
        }
        self.assertIn("warehouse", node_types)
        self.assertTrue(node_types.intersection({"intersection", "road_node"}))

        # Проверяем наличие segment_id у дорожных рёбер
        road_edges = [
            e for e in edges
            if e.get("attributes", {}).get("edge_type") == "road"
        ]
        self.assertGreater(len(road_edges), 0, "Должны присутствовать дорожные рёбра")
        for edge in road_edges:
            self.assertIn("segment_id", edge, "Каждое дорожное ребро должно иметь segment_id")
            self.assertTrue(edge["segment_id"], "segment_id не должен быть пустым")
            self.assertEqual(edge.get("attributes", {}).get("transport_mode"), "road")
            self.assertIn("geometry", edge)

        # Проверяем наличие подъездных коннекторов
        connector_edges = [
            e for e in edges
            if e.get("attributes", {}).get("edge_type") == "access_connector"
        ]
        self.assertGreater(len(connector_edges), 0, "Должны присутствовать подъездные коннекторы к складам")

        # 4. Проверяем метрики (Sprint 5 #71)
        metrics = result_payload.get("metrics", [])
        self.assertGreater(len(metrics), 0, "Метрики должны быть рассчитаны")

        regional_metrics = {m["name"]: m["value"] for m in metrics if m.get("node_id") is None}
        self.assertIn("warehouse_count", regional_metrics)
        self.assertGreater(regional_metrics["warehouse_count"], 0)
        self.assertIn("intersection_count", regional_metrics)
        self.assertGreater(regional_metrics["intersection_count"], 0)
        self.assertIn("road_segment_count", regional_metrics)
        self.assertGreater(regional_metrics["road_segment_count"], 0)
        self.assertIn("component_count", regional_metrics)
        self.assertGreaterEqual(regional_metrics["component_count"], 1.0)
        self.assertIn("total_routes_count", regional_metrics)
        self.assertGreater(regional_metrics["total_routes_count"], 0)

        warehouse_metrics = [
            m for m in metrics
            if m.get("node_id") and any(
                n["id"] == str(m["node_id"]) and n.get("attributes", {}).get("object_type") == "warehouse"
                for n in nodes
            )
        ]
        self.assertGreater(len(warehouse_metrics), 0, "Метрики складов должны присутствовать")

        intersection_metrics = [
            m for m in metrics
            if m.get("node_id") and any(
                n["id"] == str(m["node_id"]) and n.get("attributes", {}).get("object_type") == "intersection"
                for n in nodes
            )
        ]
        self.assertGreater(len(intersection_metrics), 0, "Метрики перекрёстков должны присутствовать")

        # Останавливаем воркер
        await self.worker.stop()
        worker_task.cancel()

    async def test_worker_offline_mode_fails_fast_on_missing_fixtures(self):
        """
        Проверяет, что при запросе неизвестной территории в оффлайн-режиме
        воркер корректно и быстро возвращает FAILED RESULT с понятным кодом ошибки,
        не пытаясь подключаться к Overpass API.
        """
        worker_task = asyncio.create_task(self.worker.start())

        unknown_cmd = {
            "message_id": "msg-e2e-unknown-001",
            "job_id": "job-unknown-e2e",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 10.0, "longitude": 10.0},
                    "second_point": {"latitude": 10.1, "longitude": 10.1},
                },
                "transports": ["road"],
            },
        }

        with patch.object(config, "osm_offline_mode", True):
            with patch("graph_service.algorithms.road_network_service.execute_with_overpass_fallback") as mock_road_net, \
                 patch("graph_service.algorithms.facility_service.execute_with_overpass_fallback") as mock_fac_net:

                await self.transport.put_test_command("analysis.commands", "job-unknown-e2e", unknown_cmd)

                for _ in range(30):
                    await asyncio.sleep(0.1)
                    sent = self.transport.get_sent_messages("analysis.results")
                    if len(sent) >= 2 and sent[-1][1]["type"] == EventType.RESULT.value:
                        break

                mock_road_net.assert_not_called()
                mock_fac_net.assert_not_called()

        sent = self.transport.get_sent_messages("analysis.results")
        self.assertGreaterEqual(len(sent), 2)

        key2, result_msg = sent[1]
        self.assertEqual(key2, "job-unknown-e2e")
        self.assertEqual(result_msg["type"], EventType.RESULT.value)
        result_payload = result_msg["payload"]
        self.assertEqual(result_payload["status"], TaskStatus.FAILED.value)
        self.assertIn("error", result_payload)
        self.assertIn("OSM_OFFLINE_MODE", result_payload["error"]["message"])

        await self.worker.stop()
        worker_task.cancel()
