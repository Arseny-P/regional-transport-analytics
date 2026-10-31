from typing import Callable, Awaitable, Optional
from graph_service.config import config
from graph_service.kafka.schemas import KafkaEnvelope
from graph_service.kafka.transport import KafkaTransportInterface


class CommandConsumer:
    """
    Получатель команд из топика analysis.commands (START, CANCEL).
    Десериализует сообщения в KafkaEnvelope и передает их в зарегистрированный обработчик.
    """

    def __init__(
        self,
        transport: KafkaTransportInterface,
        topic: Optional[str] = None,
    ):
        self.transport = transport
        self.topic = topic or config.kafka.commands_topic
        self.running = False

    async def start(self, handler: Callable[[KafkaEnvelope], Awaitable[None]]) -> None:
        """
        Запускает цикл прослушивания входящих команд.
        """
        self.running = True
        try:
            async for key, value in self.transport.consume(self.topic):
                if not self.running:
                    break
                try:
                    envelope = KafkaEnvelope.from_dict(value)
                    await handler(envelope)
                except Exception as parse_err:
                    print(f"[-] Ошибка разбора входящего сообщения Kafka: {parse_err}")
        except Exception as conn_err:
            print(f"[-] Ошибка консьюмера Kafka: {conn_err}")

    async def stop(self) -> None:
        """
        Останавливает чтение из Kafka.
        """
        self.running = False
