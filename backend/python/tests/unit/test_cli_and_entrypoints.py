import os
import json
import asyncio
import unittest

from graph_service.kafka import (
    KafkaEnvelope,
    StartCommandPayload,
    CancelCommandPayload,
    ResultEventPayload,
    StatusEventPayload,
)
from main import parse_args


class TestCliAndEntrypoints(unittest.TestCase):
    def test_cli_worker_flags_parsing(self):
        # Проверяем распознавание флагов --worker и --mock-kafka
        import sys
        old_argv = sys.argv
        try:
            sys.argv = ["main.py", "--worker", "--mock-kafka"]
            args = parse_args()
            self.assertTrue(args.worker)
            self.assertTrue(args.mock_kafka)
        finally:
            sys.argv = old_argv

    def test_example_kafka_contract_json_files_valid(self):
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")

        # 1. START
        start_file = os.path.join(data_dir, "example_kafka_start.json")
        self.assertTrue(os.path.exists(start_file))
        with open(start_file, "r", encoding="utf-8") as f:
            start_data = json.load(f)
        start_env = KafkaEnvelope.from_dict(start_data)
        self.assertEqual(start_env.type, "START")
        start_payload = StartCommandPayload.from_dict(start_env.payload)
        self.assertEqual(start_payload.transports, ["road"])

        # 2. CANCEL
        cancel_file = os.path.join(data_dir, "example_kafka_cancel.json")
        self.assertTrue(os.path.exists(cancel_file))
        with open(cancel_file, "r", encoding="utf-8") as f:
            cancel_data = json.load(f)
        cancel_env = KafkaEnvelope.from_dict(cancel_data)
        self.assertEqual(cancel_env.type, "CANCEL")

        # 3. RESULT completed
        res_comp_file = os.path.join(data_dir, "example_kafka_result_completed.json")
        self.assertTrue(os.path.exists(res_comp_file))
        with open(res_comp_file, "r", encoding="utf-8") as f:
            res_comp_data = json.load(f)
        res_comp_env = KafkaEnvelope.from_dict(res_comp_data)
        self.assertEqual(res_comp_env.type, "RESULT")
        self.assertEqual(res_comp_env.payload["status"], "completed")
        self.assertGreater(len(res_comp_env.payload["graph"]["nodes"]), 0)

        # 4. RESULT failed
        res_fail_file = os.path.join(data_dir, "example_kafka_result_failed.json")
        self.assertTrue(os.path.exists(res_fail_file))
        with open(res_fail_file, "r", encoding="utf-8") as f:
            res_fail_data = json.load(f)
        res_fail_env = KafkaEnvelope.from_dict(res_fail_data)
        self.assertEqual(res_fail_env.type, "RESULT")
        self.assertEqual(res_fail_env.payload["status"], "failed")
        self.assertIsNotNone(res_fail_env.payload["error"]["code"])

    def test_dunder_main_module_importable(self):
        import graph_service.__main__
        self.assertIsNotNone(graph_service.__main__.run_worker_cli)

    def test_dockerfile_and_compose_configuration(self):
        backend_python_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        root_dir = os.path.dirname(os.path.dirname(backend_python_dir))

        dockerfile_path = os.path.join(backend_python_dir, "Dockerfile")
        self.assertTrue(os.path.exists(dockerfile_path), "Dockerfile должен существовать в backend/python/")
        with open(dockerfile_path, "r", encoding="utf-8") as f:
            df_content = f.read()

        self.assertIn("FROM python:3.11-slim", df_content)
        self.assertIn("USER appuser", df_content)
        self.assertIn("CMD [\"python\", \"-m\", \"graph_service\"]", df_content)
        self.assertIn("KAFKA_BOOTSTRAP_SERVERS=\"kafka:19092\"", df_content)

        dockerignore_path = os.path.join(backend_python_dir, ".dockerignore")
        self.assertTrue(os.path.exists(dockerignore_path), ".dockerignore должен существовать в backend/python/")

        compose_path = os.path.join(root_dir, "compose.yaml")
        self.assertTrue(os.path.exists(compose_path), "compose.yaml должен существовать в корне проекта")
        with open(compose_path, "r", encoding="utf-8") as f:
            compose_content = f.read()

        self.assertIn("graph-service:", compose_content)
        self.assertIn("KAFKA_BOOTSTRAP_SERVERS: kafka:19092", compose_content)
        self.assertIn("analysis.commands", compose_content)
        self.assertIn("analysis.results", compose_content)
        self.assertIn("graph_data:", compose_content)
        self.assertIn("graph_cache:", compose_content)


class TestWorkerProcessCrashHandling(unittest.IsolatedAsyncioTestCase):
    def test_run_worker_cli_exits_with_code_1_on_fatal_failure(self):
        """Проверяет, что при фатальной ошибке run_worker_cli завершает процесс с кодом 1."""
        from unittest.mock import patch
        from graph_service.kafka.worker import run_worker_cli

        with patch("sys.argv", ["main.py", "--mock-kafka"]):
            with patch("graph_service.kafka.worker.run_worker_async", side_effect=ConnectionError("Kafka broker unreachable")):
                with self.assertRaises(SystemExit) as cm:
                    run_worker_cli()
                self.assertEqual(cm.exception.code, 1)

    async def test_run_worker_async_raises_on_fatal_worker_failure(self):
        """Проверяет, что при сбое воркера run_worker_async не виснет в stop_event.wait(), а выбрасывает ошибку."""
        from unittest.mock import patch
        from graph_service.kafka.worker import run_worker_async
        from graph_service.kafka.transport import MockKafkaTransport

        with patch.object(MockKafkaTransport, "start", side_effect=ConnectionError("Kafka failed")):
            with self.assertRaises(ConnectionError):
                await run_worker_async(mock_kafka=True)


if __name__ == "__main__":
    unittest.main()

