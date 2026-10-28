"""
Kafka Consumer interface for analysis commands.
"""
from typing import Callable, Optional
from graph_service.config import config


class CommandConsumer:
    """
    Получатель команд из топика analysis.commands (START, CANCEL).
    """

    def __init__(self, bootstrap_servers: Optional[str] = None, topic: Optional[str] = None):
        self.bootstrap_servers = bootstrap_servers or config.kafka.bootstrap_servers
        self.topic = topic or config.kafka.commands_topic
        self.running = False

    async def start(self, handler: Callable[[dict], None]) -> None:
        """
        Запускает цикл прослушивания входящих сообщений.
        """
        self.running = True

    async def stop(self) -> None:
        """
        Останавливает чтение из Kafka.
        """
        self.running = False
