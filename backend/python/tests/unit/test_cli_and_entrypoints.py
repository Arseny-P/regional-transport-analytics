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


if __name__ == "__main__":
    unittest.main()

