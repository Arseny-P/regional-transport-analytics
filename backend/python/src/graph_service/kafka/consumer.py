import json
import inspect
from typing import Callable, Awaitable, Optional, Any
from graph_service.config import config
from graph_service.kafka.schemas import KafkaEnvelope
from graph_service.kafka.transport import KafkaTransportInterface


class CommandConsumer:
    """
    Получатель команд из топика analysis.commands (START, CANCEL).
    Десериализует сообщения в KafkaEnvelope и передает их в зарегистрированный обработчик.
    Защищен от Poison Pill (битый JSON не крашит процесс и цикл чтения).
    """

    def __init__(
        self,
        transport: KafkaTransportInterface,
        topic: Optional[str] = None,
    ):
        self.transport = transport
        self.topic = topic or config.kafka.commands_topic
        self.running = False

    async def start(self, handler: Callable[..., Awaitable[None]]) -> None:
        """
        Запускает цикл прослушивания входящих команд.
        - Изолирует парсинг JSON внутри итерации сообщения (Issue 3).
        - При получении невалидного JSON коммитит оффсет битого сообщения и продолжает работу.
        - Передает message_context в обработчик для последующего Manual Commit (Issue 1).
        """
        self.running = True
        try:
            async for key, raw_val, ctx in self.transport.consume(self.topic):
                if not self.running:
                    break

                # 1. Безопасный парсинг входящих данных (защита от Poison Pill)
                try:
                    if isinstance(raw_val, (bytes, bytearray)):
                        payload_dict = json.loads(raw_val.decode("utf-8"))
                    elif isinstance(raw_val, str):
                        payload_dict = json.loads(raw_val)
                    elif isinstance(raw_val, dict):
                        payload_dict = raw_val
                    else:
                        raise ValueError(f"Неожиданный тип значения сообщения: {type(raw_val)}")

                    envelope = KafkaEnvelope.from_dict(payload_dict)
                except Exception as parse_err:
                    print(
                        f"[-] [Poison Pill] Ошибка разбора входящего сообщения Kafka: {parse_err}. "
                        f"Пропускаем битое сообщение и подтверждаем его оффсет."
                    )
                    await self.transport.commit(ctx)
                    continue

                # 2. Передача команды в обработчик
                try:
                    sig = inspect.signature(handler)
                    if len(sig.parameters) >= 2:
                        await handler(envelope, ctx)
                    else:
                        await handler(envelope)
                except Exception as handler_err:
                    print(f"[-] Непредвиденная ошибка в обработчике команды: {handler_err}")
        except Exception as conn_err:
            print(f"[-] Критическая ошибка соединения консьюмера Kafka: {conn_err}")

    async def stop(self) -> None:
        """
        Останавливает чтение из Kafka.
        """
        self.running = False
