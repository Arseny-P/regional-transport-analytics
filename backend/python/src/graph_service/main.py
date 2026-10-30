import sys
import os
import signal
import asyncio
import argparse

# Ensure src is in python path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from graph_service.config import config
from graph_service.kafka import AnalysisWorker, AioKafkaTransport, MockKafkaTransport
from graph_service.db import MemoryJobRepository


async def run_worker_async(mock_kafka: bool = False):
    """
    Запускает фоновый воркер Kafka с корректной обработкой сигналов завершения ОС.
    """
    print("=" * 65)
    print("PYTHON GRAPH SERVICE — KAFKA ANALYSIS WORKER (Спринт 3)")
    print("=" * 65)

    if mock_kafka:
        print("[*] Режим: MockKafkaTransport (in-memory, без подключения к брокеру)")
        transport = MockKafkaTransport()
    else:
        print(f"[*] Режим: AioKafkaTransport (подключение к брокеру: {config.kafka.bootstrap_servers})")
        print(f"[*] Входящий топик: {config.kafka.commands_topic}")
        print(f"[*] Исходящий топик: {config.kafka.results_topic}")
        print(f"[*] Consumer Group: {config.kafka.group_id}")
        transport = AioKafkaTransport(
            bootstrap_servers=config.kafka.bootstrap_servers,
            group_id=config.kafka.group_id,
            commands_topic=config.kafka.commands_topic,
        )

    repository = MemoryJobRepository()
    worker = AnalysisWorker(transport=transport, repository=repository)

    # Graceful shutdown handler
    stop_event = asyncio.Event()

    def signal_handler():
        print("\n[!] Получен сигнал завершения (SIGINT/SIGTERM). Выполняем корректную остановку воркера...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # На Windows add_signal_handler может быть не реализован
            pass

    worker_task = asyncio.create_task(worker.start())

    try:
        await stop_event.wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        print("[*] Остановка AnalysisWorker и отмена активных задач...")
        await worker.stop()
        worker_task.cancel()
        print("[+] Воркер успешно остановлен.")


def main():
    parser = argparse.ArgumentParser(description="Python Graph Service - Kafka Analysis Worker")
    parser.add_argument(
        "--mock-kafka",
        action="store_true",
        help="Запустить воркер с in-memory MockKafkaTransport (для оффлайн тестирования)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run_worker_async(mock_kafka=args.mock_kafka))
    except KeyboardInterrupt:
        print("\n[+] Процесс завершен пользователем.")


if __name__ == "__main__":
    main()
