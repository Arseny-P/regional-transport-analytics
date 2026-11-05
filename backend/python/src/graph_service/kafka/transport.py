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
    async def commit(self, message_context: Optional[Any] = None) -> None:
        """
        Ручное подтверждение оффсета обработанного сообщения (Manual Commit).
        """
        pass

    @abstractmethod
    async def send(self, topic: str, key: str, value: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def consume(self, topic: str) -> AsyncGenerator[Tuple[str, Any, Any], None]:
        """
        Асинхронный генератор сообщений: yield (key, raw_value, message_context)
        """
        pass


class MockMessageContext:
    """
    Эмулятор контекста оффсета Kafka-сообщения для тестирования ручного подтверждения (commit).
    """

    def __init__(self, topic: str, partition: int, offset: int, key: str = ""):
        self.topic = topic
        self.partition = partition
        self.offset = offset
        self.key = key

    def __repr__(self):
        return f"MockContext(topic={self.topic}, p={self.partition}, offset={self.offset})"


class MockKafkaTransport(KafkaTransportInterface):
    """
    Потокобезопасный in-memory транспорт для модульного и интеграционного тестирования
    без реального брокера Kafka.
    """

    def __init__(self):
        self._queues: Dict[str, asyncio.Queue] = {}
        self._sent_messages: Dict[str, list] = {}  # topic -> [(key, value)]
        self._committed_messages: list = []
        self._offset_counter = 0
        self._running = False

    def _get_queue(self, topic: str) -> asyncio.Queue:
        if topic not in self._queues:
            self._queues[topic] = asyncio.Queue()
        return self._queues[topic]

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def commit(self, message_context: Optional[Any] = None) -> None:
        """Подтверждение смещения сообщения (Manual Commit)."""
        if message_context is not None:
            self._committed_messages.append(message_context)
        else:
            self._committed_messages.append("latest")

    def get_committed_messages(self) -> list:
        return list(self._committed_messages)

    async def send(self, topic: str, key: str, value: Dict[str, Any]) -> None:
        if topic not in self._sent_messages:
            self._sent_messages[topic] = []
        self._sent_messages[topic].append((key, value))
        self._offset_counter += 1
        ctx = MockMessageContext(topic=topic, partition=0, offset=self._offset_counter, key=key)
        await self._get_queue(topic).put((key, value, ctx))

    async def put_test_command(self, topic: str, key: str, value: Any) -> None:
        """Метод для симуляции отправки команды из Go-оркестратора в тестах."""
        self._offset_counter += 1
        ctx = MockMessageContext(topic=topic, partition=0, offset=self._offset_counter, key=key)
        await self._get_queue(topic).put((key, value, ctx))

    async def consume(self, topic: str) -> AsyncGenerator[Tuple[str, Any, Any], None]:
        queue = self._get_queue(topic)
        while self._running:
            try:
                # Ожидаем с таймаутом, чтобы можно было корректно завершить генератор по флагу running
                item = await asyncio.wait_for(queue.get(), timeout=0.2)
                if len(item) == 2:
                    key, val = item
                    ctx = MockMessageContext(topic=topic, partition=0, offset=self._offset_counter, key=key)
                else:
                    key, val, ctx = item
                yield key, val, ctx
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
        self._committed_messages.clear()
        self._offset_counter = 0


class AioKafkaTransport(KafkaTransportInterface):
    """
    Реализация транспорта на базе aiokafka для боевого использования.
    - enable_auto_commit=False: ручное подтверждение оффсета строго после публикации RESULT.
    - Безопасное чтение raw-байтов без лямбда-десериализатора (защита от Poison Pill).
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

        # Важно: enable_auto_commit=False для гарантированной обработки (Issue 1)
        # Не передаем value_deserializer с json.loads, чтобы битый JSON не завершал consumer (Issue 3)
        self._consumer = AIOKafkaConsumer(
            self.commands_topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
        )
        await self._consumer.start()
        self._running = True

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()

    async def commit(self, message_context: Optional[Any] = None) -> None:
        """
        Ручное подтверждение оффсета конкретного сообщения в Kafka.
        """
        if not self._consumer:
            return
        if (
            message_context is not None
            and hasattr(message_context, "topic")
            and hasattr(message_context, "partition")
            and hasattr(message_context, "offset")
        ):
            from aiokafka.structs import TopicPartition, OffsetAndMetadata

            tp = TopicPartition(message_context.topic, message_context.partition)
            await self._consumer.commit({tp: OffsetAndMetadata(message_context.offset + 1, "")})
        else:
            await self._consumer.commit()

    async def send(self, topic: str, key: str, value: Dict[str, Any]) -> None:
        if not self._producer:
            raise RuntimeError("AioKafkaProducer не запущен")
        await self._producer.send_and_wait(topic, value=value, key=key)

    async def consume(self, topic: str) -> AsyncGenerator[Tuple[str, Any, Any], None]:
        if not self._consumer:
            raise RuntimeError("AioKafkaConsumer не запущен")
        while self._running:
            try:
                msg = await self._consumer.getone()
                key_str = msg.key.decode("utf-8") if msg.key else ""
                # Возвращаем ключ, сырые байты сообщения и сам ConsumerRecord (контекст смещения)
                yield key_str, msg.value, msg
            except asyncio.CancelledError:
                break
