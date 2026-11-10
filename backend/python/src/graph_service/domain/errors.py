"""
Domain exceptions for the Graph Service.
"""


class GraphServiceError(Exception):
    """Базовое исключение доменной области построения графа."""
    code: str = "internal_error"

    def __init__(self, message: str, code: str = None):
        super().__init__(message)
        if code:
            self.code = code


class TerritoryValidationError(GraphServiceError, ValueError):
    """Ошибка валидации географических координат или границ исследуемой территории."""
    code = "invalid_parameters"


class FacilityValidationError(GraphServiceError, ValueError):
    """Ошибка валидации данных логистического объекта."""
    code = "invalid_parameters"


class UnsupportedTransportError(GraphServiceError):
    """Запрошен неподдерживаемый вид транспорта (например, sea/rail до их реализации)."""
    code = "unsupported_transport"


class OSMUnavailableError(GraphServiceError, RuntimeError):
    """OpenStreetMap / Overpass API недоступен или вернул ошибку на всех зеркалах."""
    code = "osm_unavailable"


class GraphBuildError(GraphServiceError):
    """Ошибка в процессе алгоритмического построения графа."""
    code = "graph_build_failed"


class MetricsCalculationError(GraphServiceError):
    """Ошибка расчёта метрик графа."""
    code = "metrics_calculation_failed"
