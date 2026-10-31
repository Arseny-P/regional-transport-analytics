from abc import ABC, abstractmethod
from typing import Optional, Dict, Any


class JobRepository(ABC):
    """
    Абстрактный интерфейс репозитория состояний задач и дедупликации сообщений.
    """

    @abstractmethod
    def is_message_processed(self, message_id: str) -> bool:
        """
        Проверяет, было ли входящее сообщение с данным message_id уже обработано.
        """
        pass

    @abstractmethod
    def mark_message_processed(self, message_id: str, job_id: str) -> None:
        """
        Помечает message_id как принятое к обработке.
        """
        pass

    @abstractmethod
    def save_job_state(
        self,
        job_id: str,
        status: str,
        result_envelope: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Сохраняет текущий статус задачи и итоговый конверт результата.
        """
        pass

    @abstractmethod
    def get_job_state(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Возвращает информацию о текущем состоянии задачи (статус, время создания/обновления).
        """
        pass

    @abstractmethod
    def get_saved_result(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Возвращает сохраненный финальный результат задачи (RESULT конверт) для повторной отправки.
        """
        pass

