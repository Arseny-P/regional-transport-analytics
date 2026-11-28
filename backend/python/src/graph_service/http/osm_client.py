import time
import json
import urllib.request
import urllib.parse
from typing import Callable, Any, List, Dict
import osmnx as ox

from graph_service.config import config
from graph_service.domain.errors import OSMUnavailableError

# Список проверенных публичных глобальных зеркал Overpass API в порядке приоритета
OVERPASS_MIRRORS: List[str] = config.overpass.mirrors


def execute_with_overpass_fallback(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """
    Выполняет вызов функции загрузки данных OSMnx с автоматической ротацией зеркал Overpass API.
    Если текущее зеркало вернуло 502/504, 429 (rate limit), сбросило соединение или упало по таймауту,
    запрос автоматически повторяется на следующем доступном зеркале из списка.
    """
    last_error = None
    attempted_errors: List[str] = []
    mirrors = config.overpass.mirrors

    for idx, mirror in enumerate(mirrors, start=1):
        ox.settings.overpass_url = mirror
        ox.settings.requests_timeout = config.overpass.requests_timeout_sec
        try:
            print(f"[*] Попытка [{idx}/{len(mirrors)}] через Overpass зеркало: {mirror}...")
            result = func(*args, **kwargs)
            return result
        except Exception as err:
            last_error = err
            err_repr = f"{type(err).__name__}: {str(err)[:100]}"
            print(f"[-] Зеркало {mirror} недоступно или отклонило запрос ({err_repr}).")
            attempted_errors.append(f"{mirror} -> {err_repr}")
            if idx < len(mirrors):
                time.sleep(1.0)

    raise OSMUnavailableError(
        f"Все доступные зеркала Overpass API завершились ошибкой:\n"
        + "\n".join(f"  • {e}" for e in attempted_errors)
    ) from last_error


def query_overpass_json(query: str) -> Dict[str, Any]:
    """
    Выполняет произвольный Overpass QL запрос к зеркалам Overpass API и возвращает структурированный JSON.
    Автоматически ротирует зеркала при сетевых сбоях или таймаутах.
    """
    last_error = None
    attempted_errors: List[str] = []
    mirrors = config.overpass.mirrors

    for idx, mirror in enumerate(mirrors, start=1):
        try:
            endpoint = mirror if mirror.endswith("/interpreter") else f"{mirror.rstrip('/')}/interpreter"
            req = urllib.request.Request(
                endpoint,
                data=urllib.parse.urlencode({"data": query}).encode(),
                headers={"User-Agent": "RegionalTransportAnalytics/1.0 (Python Worker)"},
            )
            with urllib.request.urlopen(req, timeout=config.overpass.requests_timeout_sec) as resp:
                data = json.load(resp)
            if not isinstance(data.get("elements"), list):
                raise ValueError("Некорректный ответ Overpass (поле 'elements' отсутствует или повреждено)")
            return data
        except Exception as err:
            last_error = err
            err_repr = f"{type(err).__name__}: {str(err)[:100]}"
            attempted_errors.append(f"{mirror} -> {err_repr}")
            if idx < len(mirrors):
                time.sleep(1.0)

    raise OSMUnavailableError(
        f"Все доступные зеркала Overpass API завершились ошибкой:\n"
        + "\n".join(f"  • {e}" for e in attempted_errors)
    ) from last_error
