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
        self.assertEqual(status_msg.get("transport_type"), "rail")
        self.assertEqual(status_msg["payload"]["status"], TaskStatus.RUNNING.value)

        # 2. Проверяем финальный RESULT
        key2, result_msg = sent[1]
        self.assertEqual(key2, "job-rail-shushary-e2e")
        self.assertEqual(result_msg["type"], EventType.RESULT.value)
        self.assertEqual(result_msg.get("transport_type"), "rail")
        result_payload = result_msg["payload"]
        self.assertEqual(result_payload["status"], TaskStatus.COMPLETED.value)
        self.assertNotIn("error", result_payload)

        # 3. Проверяем структуру и объем графа
        graph = result_payload.get("graph")
        self.assertIsNotNone(graph, "Граф должен присутствовать в payload результата")
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])

        # Ориентир Шушар после топологического сжатия: 86 путевых вершин + 2 станции-кандидата = 88 вершин
        # 180 направленных рёбер (90 physical * 2)
        self.assertEqual(len(nodes), 88, "Граф Шушар должен содержать 88 вершин (86 путевых + 2 станции)")
        track_nodes = [n for n in nodes if not n["id"].startswith("station:")]
        station_nodes = [n for n in nodes if n["id"].startswith("station:")]
        self.assertEqual(len(track_nodes), 86)
        self.assertEqual(len(station_nodes), 2)
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

    async def test_worker_rail_pipeline_with_connected_stations_calculates_distance(self):
        """
        Проверяет полный цикл анализа при передаче подтвержденных станций в команде START:
        - станции привязываются к путям (anchor_node_ids)
        - station_count > 0
        - метрика nearest_station_distance_m рассчитывается и сопоставляется с вершиной
        - станции присутствуют в graph.nodes с ID == facility_id (OpenAPI соответствие)
        - transport_type == 'rail' в заголовках сообщений
        """
        worker_task = asyncio.create_task(self.worker.start())

        start_cmd = {
            "message_id": "msg-rail-stations-001",
            "job_id": "job-rail-stations-connected",
            "type": "START",
            "payload": {
                "area": {
                    "first_point": {"latitude": 59.7950, "longitude": 30.3850},
                    "second_point": {"latitude": 59.8240, "longitude": 30.4410},
                },
                "transports": ["rail"],
                "facilities": [
                    {
                        "facility_id": "station:1377619868",
                        "name": "Шушары",
                        "latitude": 59.816,
                        "longitude": 30.395,
                        "anchor_node_ids": ["osm_node:1382891208"],
                    },
                    {
                        "facility_id": "station:922690113",
                        "name": "Юный",
                        "latitude": 59.805,
                        "longitude": 30.405,
                        "anchor_node_ids": ["osm_node:922499002"],
                    },
                ],
            },
        }

        with patch.object(config, "osm_offline_mode", True):
            await self.transport.put_test_command("analysis.commands", "job-rail-stations-connected", start_cmd)

            for _ in range(50):
                await asyncio.sleep(0.1)
                sent = self.transport.get_sent_messages("analysis.results")
                if len(sent) >= 2 and sent[-1][1]["type"] == EventType.RESULT.value:
                    break

        sent = self.transport.get_sent_messages("analysis.results")
        self.assertGreaterEqual(len(sent), 2)

        # 1. Заголовки сообщений должны содержать transport_type == 'rail'
        status_msg = sent[0][1]
        self.assertEqual(status_msg.get("transport_type"), "rail")

        result_msg = sent[1][1]
        self.assertEqual(result_msg.get("transport_type"), "rail")

        result_payload = result_msg["payload"]
        self.assertEqual(result_payload["status"], TaskStatus.COMPLETED.value)

        # 2. Проверяем вершины станций в graph.nodes (соответствие OpenAPI)
        nodes = result_payload["graph"]["nodes"]
        node_ids = {n["id"] for n in nodes}
        self.assertIn("station:1377619868", node_ids)
        self.assertIn("station:922690113", node_ids)

        shushary_node = next(n for n in nodes if n["id"] == "station:1377619868")
        self.assertEqual(shushary_node["attributes"]["object_type"], "rail_facility")
        self.assertEqual(shushary_node["attributes"]["node_kind"], "station")
        self.assertEqual(shushary_node["attributes"]["connection_status"], "connected")
        self.assertEqual(shushary_node["attributes"]["anchor_node_ids"], ["osm_node:1382891208"])

        # 3. Проверяем расчет метрик: station_count == 2.0 и nearest_station_distance_m
        metrics = result_payload["metrics"]
        by_name = {}
        for m in metrics:
            by_name.setdefault(m["name"], []).append(m)

        self.assertIn("station_count", by_name)
        self.assertEqual(by_name["station_count"][0]["value"], 2.0)

        self.assertIn("nearest_station_distance_m", by_name)
        dist_metrics = by_name["nearest_station_distance_m"]
        self.assertEqual(len(dist_metrics), 2)

        # node_id метрики должен совпадать с ID вершины станции из graph.nodes
        for dm in dist_metrics:
            self.assertIn(dm["node_id"], {"station:1377619868", "station:922690113"})
            self.assertAlmostEqual(dm["value"], 1006.388381, places=1)

        await self.worker.stop()
        worker_task.cancel()

    async def test_worker_rail_cancel_after_completed_emits_canceled_status(self):
        """
        Проверяет требование Go-оркестратора:
        Если задача уже успешно выполнилась (COMPLETED), но следом приходит CANCEL,
        воркер переводит задачу в canceled и отправляет STATUS: canceled,
        чтобы в Go не зависал статус cancel_requested.
        """
        worker_task = asyncio.create_task(self.worker.start())

        job_id = "job-rail-cancel-after-completed"
        start_cmd = {
            "message_id": "msg-start-001",
            "job_id": job_id,
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
            await self.transport.put_test_command("analysis.commands", job_id, start_cmd)

            # Ждём завершения вычислений (STATUS + RESULT)
            for _ in range(50):
                await asyncio.sleep(0.1)
                sent = self.transport.get_sent_messages("analysis.results")
                if len(sent) >= 2 and sent[-1][1]["type"] == EventType.RESULT.value:
                    break

        sent_before_cancel = self.transport.get_sent_messages("analysis.results")
        self.assertEqual(len(sent_before_cancel), 2)
        self.assertEqual(sent_before_cancel[1][1]["type"], EventType.RESULT.value)
        self.assertEqual(sent_before_cancel[1][1]["payload"]["status"], TaskStatus.COMPLETED.value)

        # Теперь посылаем CANCEL уже после завершения
        cancel_cmd = {
            "message_id": "msg-cancel-002",
            "job_id": job_id,
            "type": "CANCEL",
            "payload": {},
        }
        await self.transport.put_test_command("analysis.commands", job_id, cancel_cmd)

        for _ in range(30):
            await asyncio.sleep(0.1)
            sent = self.transport.get_sent_messages("analysis.results")
            if len(sent) >= 3:
                break

        sent_after_cancel = self.transport.get_sent_messages("analysis.results")
        self.assertEqual(len(sent_after_cancel), 3, "Ожидалось 3 сообщения: RUNNING -> RESULT -> CANCELED")

        key3, cancel_event = sent_after_cancel[2]
        self.assertEqual(key3, job_id)
        self.assertEqual(cancel_event["type"], EventType.STATUS.value)
        self.assertEqual(cancel_event.get("transport_type"), "rail")
        self.assertEqual(cancel_event["payload"]["status"], TaskStatus.CANCELED.value)

        # Проверяем, что в репозитории статус стал canceled
        job_state = self.worker.repository.get_job_state(job_id)
        self.assertEqual(job_state["status"], TaskStatus.CANCELED.value)

        await self.worker.stop()
        worker_task.cancel()
