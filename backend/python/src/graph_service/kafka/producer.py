"""
Kafka Producer interface for publishing analysis results and status events.
"""
from typing import Optional
from graph_service.config import config
from graph_service.kafka.schemas import KafkaEnvelope


class EventProducer:
    """
    Отправитель событий в топик analysis.results (STATUS, RESULT).
    """

    def __init__(self, bootstrap_servers: Optional[str] = None, topic: Optional[str] = None):
        self.bootstrap_servers = bootstrap_servers or config.kafka.bootstrap_servers
        self.topic = topic or config.kafka.results_topic

    async def send_event(self, envelope: KafkaEnvelope) -> None:
        """
        Публикует событие с ключом job_id в топик результатов.
        """
        pass
