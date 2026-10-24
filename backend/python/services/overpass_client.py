import time
from typing import Callable, Any, List
import osmnx as ox

# Список проверенных публичных зеркал Overpass API в порядке приоритета
OVERPASS_MIRRORS: List[str] = [
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
]


def execute_with_overpass_fallback(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """
    Выполняет вызов функции загрузки данных OSMnx с автоматической ротацией зеркал Overpass API.
    Если текущее зеркало вернуло 502/504, 429 (rate limit), сбросило соединение или упало по таймауту,
    запрос автоматически повторяется на следующем доступном зеркале из списка.
    """
    last_error = None
    attempted_errors: List[str] = []

    for idx, mirror in enumerate(OVERPASS_MIRRORS, start=1):
        ox.settings.overpass_url = mirror
        try:
            print(f"[*] Попытка [{idx}/{len(OVERPASS_MIRRORS)}] через Overpass зеркало: {mirror}...")
            result = func(*args, **kwargs)
            return result
        except Exception as err:
            last_error = err
            err_repr = f"{type(err).__name__}: {str(err)[:100]}"
            print(f"[-] Зеркало {mirror} недоступно или отклонило запрос ({err_repr}).")
            attempted_errors.append(f"{mirror} -> {err_repr}")
            if idx < len(OVERPASS_MIRRORS):
                time.sleep(1.0)

    raise RuntimeError(
        f"Все доступные зеркала Overpass API завершились ошибкой:\n"
        + "\n".join(f"  • {e}" for e in attempted_errors)
    ) from last_error
