import json
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, AsyncGenerator, Tuple


class KafkaTransportInterface(ABC):
    """
    Интерфейс низкоуровневого взаимодействия с брокером сообщений.
    """

    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass

    @abstractmethod
    async def send(self, topic: str, key: str, value: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def consume(self, topic: str) -> AsyncGenerator[Tuple[str, Dict[str, Any]], None]:
        pass


class MockKafkaTransport(KafkaTransportInterface):
    """
    Потокобезопасный in-memory транспорт для модульного и интеграционного тестирования
    без реального брокера Kafka.
    """

    def __init__(self):
        self._queues: Dict[str, asyncio.Queue] = {}
        self._sent_messages: Dict[str, list] = {}  # topic -> [(key, value)]
        self._running = False

    def _get_queue(self, topic: str) -> asyncio.Queue:
        if topic not in self._queues:
            self._queues[topic] = asyncio.Queue()
        return self._queues[topic]

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, topic: str, key: str, value: Dict[str, Any]) -> None:
        if topic not in self._sent_messages:
            self._sent_messages[topic] = []
        self._sent_messages[topic].append((key, value))
        await self._get_queue(topic).put((key, value))

    async def put_test_command(self, topic: str, key: str, value: Dict[str, Any]) -> None:
        """Метод для симуляции отправки команды из Go-оркестратора в тестах."""
        await self._get_queue(topic).put((key, value))

    async def consume(self, topic: str) -> AsyncGenerator[Tuple[str, Dict[str, Any]], None]:
        queue = self._get_queue(topic)
        while self._running:
            try:
                # Ожидаем с таймаутом, чтобы можно было корректно завершить генератор по флагу running
                key, val = await asyncio.wait_for(queue.get(), timeout=0.2)
                yield key, val
                queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def get_sent_messages(self, topic: str) -> list:
        return list(self._sent_messages.get(topic, []))

    def clear(self) -> None:
        self._queues.clear()
        self._sent_messages.clear()


class AioKafkaTransport(KafkaTransportInterface):
    """
    Реализация транспорта на базе aiokafka для боевого использования.
    """

    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        commands_topic: str,
    ):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.commands_topic = commands_topic
        self._producer = None
        self._consumer = None
        self._running = False

    async def start(self) -> None:
        from aiokafka import AIOKafkaProducer, AIOKafkaConsumer

        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if isinstance(k, str) else k,
        )
        await self._producer.start()

        self._consumer = AIOKafkaConsumer(
            self.commands_topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            key_deserializer=lambda k: k.decode("utf-8") if k else "",
        )
        await self._consumer.start()
        self._running = True

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()

    async def send(self, topic: str, key: str, value: Dict[str, Any]) -> None:
        if not self._producer:
            raise RuntimeError("AioKafkaProducer не запущен")
        await self._producer.send_and_wait(topic, value=value, key=key)

    async def consume(self, topic: str) -> AsyncGenerator[Tuple[str, Dict[str, Any]], None]:
        if not self._consumer:
            raise RuntimeError("AioKafkaConsumer не запущен")
        while self._running:
            try:
                msg = await self._consumer.getone()
                yield msg.key, msg.value
            except asyncio.CancelledError:
                break
