import time
import threading
from typing import Optional, Dict, Any
from graph_service.db.repository import JobRepository


class MemoryJobRepository(JobRepository):
    """
    Потокобезопасная in-memory реализация репозитория задач и дедупликации сообщений.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._processed_messages: Dict[str, str] = {}  # message_id -> job_id
        self._job_states: Dict[str, Dict[str, Any]] = {}  # job_id -> metadata
        self._saved_results: Dict[str, Dict[str, Any]] = {}  # job_id -> envelope dict

    def is_message_processed(self, message_id: str) -> bool:
        with self._lock:
            return message_id in self._processed_messages

    def mark_message_processed(self, message_id: str, job_id: str) -> None:
        with self._lock:
            self._processed_messages[message_id] = job_id
            if job_id not in self._job_states:
                self._job_states[job_id] = {
                    "job_id": job_id,
                    "status": "received",
                    "created_at": time.time(),
                    "updated_at": time.time(),
                }

    def save_job_state(
        self,
        job_id: str,
        status: str,
        result_envelope: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            now = time.time()
            if job_id not in self._job_states:
                self._job_states[job_id] = {
                    "job_id": job_id,
                    "status": status,
                    "created_at": now,
                    "updated_at": now,
                    "error": error,
                }
            else:
                self._job_states[job_id]["status"] = status
                self._job_states[job_id]["updated_at"] = now
                if error:
                    self._job_states[job_id]["error"] = error

            if result_envelope is not None:
                self._saved_results[job_id] = result_envelope

    def get_job_state(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            state = self._job_states.get(job_id)
            return dict(state) if state else None

    def get_saved_result(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            res = self._saved_results.get(job_id)
            return dict(res) if res else None

    def clear(self) -> None:
        with self._lock:
            self._processed_messages.clear()
            self._job_states.clear()
            self._saved_results.clear()

