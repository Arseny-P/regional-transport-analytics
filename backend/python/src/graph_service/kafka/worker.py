import sys
import asyncio
from typing import Dict, Any, Optional

from graph_service.domain.models import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    TerritoryBounds,
    TerritorySourceType,
    FacilitySourceType,
)
from graph_service.domain.errors import (
    GraphServiceError,
    TerritoryValidationError,
    UnsupportedTransportError,
    OSMUnavailableError,
    GraphBuildError,
    MetricsCalculationError,
)
from graph_service.application.build_graph import TerritoryAnalysisService
from graph_service.application.cancellation import CancellationToken, TaskCancelledException
from graph_service.db.repository import JobRepository
from graph_service.db.memory_repository import MemoryJobRepository
from graph_service.kafka.schemas import (
    KafkaEnvelope,
    CommandType,
    EventType,
    TaskStatus,
    ErrorCode,
    StartCommandPayload,
    StatusEventPayload,
    ResultEventPayload,
    ErrorPayload,
)
from graph_service.kafka.consumer import CommandConsumer
from graph_service.kafka.producer import EventProducer
from graph_service.kafka.transport import KafkaTransportInterface


class AnalysisWorker:
    """
    Основной оркестратор фонового воркера Kafka.
    Слушает входящие команды (START, CANCEL) и публикует события (STATUS, RESULT).
    """

    def __init__(
        self,
        transport: KafkaTransportInterface,
        repository: Optional[JobRepository] = None,
        analysis_service: Optional[TerritoryAnalysisService] = None,
    ):
        self.transport = transport
        self.repository = repository or MemoryJobRepository()
        self.analysis_service = analysis_service or TerritoryAnalysisService()
        self.consumer = CommandConsumer(transport=self.transport)
        self.producer = EventProducer(transport=self.transport)

        # Активные задачи в процессе вычисления (job_id -> CancellationToken)
        self._active_tokens: Dict[str, CancellationToken] = {}
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._running = False

    async def start(self) -> None:
        """
        Запускает транспорт и цикл обработки команд Kafka.
        """
        self._running = True
        await self.transport.start()
        print("[*] Kafka AnalysisWorker запущен и ожидает входящие команды...")
        await self.consumer.start(self.handle_command)

    async def stop(self) -> None:
        """
        Останавливает воркер и все выполняющиеся фоновые вычисления.
        """
        self._running = False
        # Отменяем все активные вычисления
        for job_id, token in list(self._active_tokens.items()):
            token.cancel()

        await self.consumer.stop()
        await self.transport.stop()
        print("[*] Kafka AnalysisWorker остановлен.")

    async def handle_command(self, envelope: KafkaEnvelope) -> None:
        """
        Маршрутизирует входящую команду (START или CANCEL).
        """
        cmd_type = envelope.type.upper()

        if cmd_type == CommandType.START.value:
            await self._handle_start(envelope)
        elif cmd_type == CommandType.CANCEL.value:
            await self._handle_cancel(envelope)
        else:
            print(f"[!] Получена неизвестная команда: '{cmd_type}' для задачи {envelope.job_id}")

    async def _handle_start(self, envelope: KafkaEnvelope) -> None:
        """
        Обрабатывает команду запуска анализа START.
        """
        job_id = envelope.job_id
        message_id = envelope.message_id

        # 1. Проверка идемпотентности сообщения
        if self.repository.is_message_processed(message_id):
            print(f"[*] Сообщение {message_id} уже обработано ранее. Проверка наличия сохраненного результата.")
            saved_result = self.repository.get_saved_result(job_id)
            if saved_result:
                # Повторно доставляем сохраненный RESULT
                res_envelope = KafkaEnvelope.from_dict(saved_result)
                await self.producer.send_event(res_envelope)
            return

        # 2. Проверка, не выполняется ли уже эта задача
        if job_id in self._active_tokens:
            print(f"[!] Задача {job_id} уже выполняется. Повторный запуск проигнорирован.")
            return

        # Фиксируем получение message_id
        self.repository.mark_message_processed(message_id, job_id)

        # 3. Валидация входных данных команды START
        try:
            start_payload = StartCommandPayload.from_dict(envelope.payload)
        except ValueError as val_err:
            await self._emit_failed_result(
                job_id=job_id,
                code=ErrorCode.INVALID_PARAMETERS.value,
                message=str(val_err),
            )
            return

        try:
            start_payload.validate_transports()
        except ValueError as trans_err:
            await self._emit_failed_result(
                job_id=job_id,
                code=ErrorCode.UNSUPPORTED_TRANSPORT.value,
                message=str(trans_err),
            )
            return

        # 4. Регистрация токена отмены и отправка статуса running
        token = CancellationToken()
        self._active_tokens[job_id] = token

        await self._emit_status(job_id=job_id, status=TaskStatus.RUNNING.value)
        self.repository.save_job_state(job_id, status=TaskStatus.RUNNING.value)

        # 5. Запуск вычислений в фоновом режиме (не блокируя Kafka loop)
        task = asyncio.create_task(
            self._run_analysis_pipeline(
                job_id=job_id,
                payload=start_payload,
                token=token,
            )
        )
        self._active_tasks[job_id] = task

    async def _handle_cancel(self, envelope: KafkaEnvelope) -> None:
        """
        Обрабатывает команду отмены вычислений CANCEL.
        """
        job_id = envelope.job_id
        print(f"[*] Получен запрос на отмену (CANCEL) для задачи {job_id}")

        if job_id in self._active_tokens:
            # Задача выполняется — посылаем сигнал отмены
            token = self._active_tokens[job_id]
            token.cancel()
            print(f"[+] Сигнал отмены передан в вычислительный процесс задачи {job_id}")
        else:
            # Задача уже не выполняется или была завершена ранее
            state = self.repository.get_job_state(job_id)
            if state and state.get("status") in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value):
                print(f"[*] Задача {job_id} уже завершена со статусом {state.get('status')}. Отмена не требуется.")
            else:
                # Если задача еще не стартовала, подтверждаем отмену
                await self._emit_status(job_id=job_id, status=TaskStatus.CANCELED.value)
                self.repository.save_job_state(job_id, status=TaskStatus.CANCELED.value)

    async def _run_analysis_pipeline(
        self,
        job_id: str,
        payload: StartCommandPayload,
        token: CancellationToken,
    ) -> None:
        """
        Фоновый цикл выполнения построения графа, расчета метрик и публикации RESULT.
        """
        try:
            west, south, east, north = payload.area.to_bounds()
            bbox = TerritoryBounds(
                min_lat=south,
                min_lon=west,
                max_lat=north,
                max_lon=east,
            )

            request = AnalysisRequest(
                territory_type=TerritorySourceType.BBOX.value,
                bbox=bbox,
                facility_source=FacilitySourceType.OSM.value,
                osm_facilities_limit=100,
                knn=None,
                save_artifacts=True,
                include_geojson_payload=False,
                refetch=False,
            )

            # Выполняем синхронное построение графа в отдельном пуле потоков
            response: AnalysisResponse = await asyncio.to_thread(
                self.analysis_service.run_analysis,
                request,
                token,
            )

            if token.is_cancelled:
                raise TaskCancelledException("Задача была отменена во время выполнения")

            # Проверка статуса ответа сервиса
            if response.status == AnalysisStatus.ERROR.value:
                err_msg = response.error_message or "Неизвестная ошибка построения графа"
                code = ErrorCode.GRAPH_BUILD_FAILED.value
                if "Overpass" in err_msg or "зеркал" in err_msg or "OSM" in err_msg:
                    code = ErrorCode.OSM_UNAVAILABLE.value
                elif "валидации" in err_msg:
                    code = ErrorCode.INVALID_PARAMETERS.value

                await self._emit_failed_result(job_id=job_id, code=code, message=err_msg)
                return

            # Успешное построение графа — сериализуем в контракт Go и рассчитываем метрики
            from graph_service.application.graph_serializer import GraphSerializer
            from graph_service.application.metrics_service import GraphMetricsService

            log_graph = response.graph_object
            if log_graph is None:
                # Fallback, если объект графа не был передан в памяти
                alias = bbox.cache_key()
                log_graph = self.analysis_service.logistics_service.load_graphml(filename=f"{alias}_logistics")

            graph_payload = GraphSerializer.serialize(log_graph)

            # Расчёт метрик Data Science (#28)
            try:
                metrics = GraphMetricsService.calculate_metrics(log_graph)
                result_payload = ResultEventPayload(
                    status=TaskStatus.COMPLETED.value,
                    graph=graph_payload,
                    metrics=metrics,
                )
            except Exception as metrics_err:
                # Если упали метрики, готовый граф НЕ уничтожается по контракту (п. 7)
                print(f"[-] Сбой расчёта метрик для задачи {job_id}: {metrics_err}")
                result_payload = ResultEventPayload(
                    status=TaskStatus.FAILED.value,
                    graph=graph_payload,
                    metrics=[],
                    error=ErrorPayload(
                        code=ErrorCode.METRICS_CALCULATION_FAILED.value,
                        message=f"Не удалось рассчитать метрики: {metrics_err}",
                    ),
                )

            result_envelope = KafkaEnvelope.create(
                job_id=job_id,
                msg_type=EventType.RESULT.value,
                payload=result_payload.to_dict(),
            )
            await self.producer.send_event(result_envelope)
            self.repository.save_job_state(
                job_id=job_id,
                status=result_payload.status,
                result_envelope=result_envelope.to_dict(),
            )
            print(f"[+] Задача {job_id} успешно завершена со статусом {result_payload.status}.")

        except TaskCancelledException:
            print(f"[*] Выполнение задачи {job_id} остановлено по сигналу отмены.")
            await self._emit_status(job_id=job_id, status=TaskStatus.CANCELED.value)
            self.repository.save_job_state(job_id=job_id, status=TaskStatus.CANCELED.value)

        except Exception as unhandled_err:
            print(f"[-] Непредвиденная ошибка в задаче {job_id}: {unhandled_err}", file=sys.stderr)
            await self._emit_failed_result(
                job_id=job_id,
                code=ErrorCode.INTERNAL_ERROR.value,
                message=f"Внутренняя ошибка сервиса: {unhandled_err}",
            )

        finally:
            self._active_tokens.pop(job_id, None)
            self._active_tasks.pop(job_id, None)

    async def _emit_status(self, job_id: str, status: str) -> None:
        """
        Отправляет событие STATUS в топик analysis.results.
        """
        payload = StatusEventPayload(status=status).to_dict()
        envelope = KafkaEnvelope.create(
            job_id=job_id,
            msg_type=EventType.STATUS.value,
            payload=payload,
        )
        await self.producer.send_event(envelope)

    async def _emit_failed_result(self, job_id: str, code: str, message: str) -> None:
        """
        Отправляет событие RESULT failed в топик analysis.results.
        """
        payload = ResultEventPayload(
            status=TaskStatus.FAILED.value,
            graph=None,
            metrics=[],
            error=ErrorPayload(code=code, message=message),
        ).to_dict()
        envelope = KafkaEnvelope.create(
            job_id=job_id,
            msg_type=EventType.RESULT.value,
            payload=payload,
        )
        await self.producer.send_event(envelope)
        self.repository.save_job_state(
            job_id=job_id,
            status=TaskStatus.FAILED.value,
            result_envelope=envelope.to_dict(),
            error=message,
        )
