from typing import Optional
from graph_service.config import config
from graph_service.kafka.schemas import KafkaEnvelope
from graph_service.kafka.transport import KafkaTransportInterface


class EventProducer:
    """
    Отправитель событий в топик analysis.results (STATUS, RESULT).
    Всегда использует строковый job_id в качестве Kafka key.
    """

    def __init__(
        self,
        transport: KafkaTransportInterface,
        topic: Optional[str] = None,
    ):
        self.transport = transport
        self.topic = topic or config.kafka.results_topic

    async def send_event(self, envelope: KafkaEnvelope) -> None:
        """
        Публикует событие с ключом job_id в топик результатов.
        """
        await self.transport.send(
            topic=self.topic,
            key=str(envelope.job_id),
            value=envelope.to_dict(),
        )
