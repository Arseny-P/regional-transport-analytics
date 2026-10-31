import threading


class TaskCancelledException(Exception):
    """Исключение, выбрасываемое при отмене выполнения задачи."""
    pass


class CancellationToken:
    """
    Потокобезопасный токен для кооперативной отмены длительных вычислений графа.
    """

    def __init__(self):
        self._cancelled = False
        self._lock = threading.Lock()

    def cancel(self) -> None:
        """Переводит токен в состояние отмены."""
        with self._lock:
            self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        """Возвращает True, если был вызван cancel()."""
        with self._lock:
            return self._cancelled

    def check_cancelled(self) -> None:
        """
        Проверяет состояние токена и выбрасывает TaskCancelledException,
        если операция была отменена.
        """
        if self.is_cancelled:
            raise TaskCancelledException("Операция была отменена по запросу CANCEL.")
