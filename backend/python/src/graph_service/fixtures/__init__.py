import os
from typing import Optional, Tuple

FIXTURES_DIR = os.path.dirname(os.path.abspath(__file__))


def find_fixture_files(
    alias: str,
    custom_dir: Optional[str] = None,
    allow_default: Optional[bool] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Ищет локальные фикстуры дорог (.graphml) и объектов (.json / .geojson)
    по переданному алиасу/ключу BBox.

    Проверяет директории:
    1. custom_dir (если передан)
    2. FIXTURES_DIR (встроенные фикстуры пакета)
    3. DATA_DIR из окружения

    Возвращает кортеж (road_path, facilities_path).
    """
    if allow_default is None:
        allow_default = os.getenv("OSM_OFFLINE_ALLOW_DEFAULT", "false").lower() in ("true", "1", "yes")

    search_dirs = []
    if custom_dir and os.path.exists(custom_dir):
        search_dirs.append(custom_dir)
    search_dirs.append(FIXTURES_DIR)

    data_dir = os.getenv("DATA_DIR")
    if data_dir and os.path.exists(data_dir) and data_dir not in search_dirs:
        search_dirs.append(data_dir)

    # 1. Приоритетные кандидаты, привязанные к конкретному алиасу / территории
    alias_lower = alias.lower()
    road_candidates = [
        f"{alias}_roads.graphml",
        f"{alias}.graphml",
    ]
    fac_candidates = [
        f"{alias}_facilities.json",
        f"{alias}_facilities.geojson",
        f"{alias}.json",
    ]

    if "kronshtadt" in alias_lower or "kronstadt" in alias_lower or "кронштадт" in alias_lower:
        road_candidates.append("kronshtadt_roads.graphml")
        fac_candidates.append("kronshtadt_facilities.json")

    # 2. Дефолтные кандидаты — только если разрешен fallback или запрошен default/test
    if allow_default or alias_lower in ("default", "test", "demo", "sample"):
        road_candidates.extend(["kronshtadt_roads.graphml", "default_roads.graphml"])
        fac_candidates.extend(["kronshtadt_facilities.json", "default_facilities.json", "test_logistics_points.json"])

    road_path: Optional[str] = None
    fac_path: Optional[str] = None

    for d in search_dirs:
        if not road_path:
            for rc in road_candidates:
                candidate_path = os.path.join(d, rc)
                if os.path.exists(candidate_path):
                    road_path = candidate_path
                    break

        if not fac_path:
            for fc in fac_candidates:
                candidate_path = os.path.join(d, fc)
                if os.path.exists(candidate_path):
                    fac_path = candidate_path
                    break

        if road_path and fac_path:
            break

    return road_path, fac_path


def find_rail_fixture_files(
    alias: str,
    custom_dir: Optional[str] = None,
    allow_default: Optional[bool] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Ищет локальные фикстуры железнодорожных путей (.json) и объектов инфраструктуры (.json)
    по переданному алиасу/ключу BBox.

    Возвращает кортеж (rail_ways_path, rail_objects_path).
    """
    if allow_default is None:
        allow_default = os.getenv("OSM_OFFLINE_ALLOW_DEFAULT", "false").lower() in ("true", "1", "yes")

    search_dirs = []
    if custom_dir and os.path.exists(custom_dir):
        search_dirs.append(custom_dir)
    search_dirs.append(FIXTURES_DIR)

    data_dir = os.getenv("DATA_DIR")
    if data_dir and os.path.exists(data_dir) and data_dir not in search_dirs:
        search_dirs.append(data_dir)

    alias_lower = alias.lower()
    ways_candidates = [
        f"{alias}_rail_ways.json",
        f"{alias}_ways.json",
        f"{alias}.json",
    ]
    objects_candidates = [
        f"{alias}_rail_objects.json",
        f"{alias}_objects.json",
    ]

    if "shushary" in alias_lower or "шушары" in alias_lower:
        ways_candidates.extend(["shushary_rail_ways.json", "bbox_59.7950_30.3850_59.8240_30.4410_rail_ways.json"])
        objects_candidates.extend(["shushary_rail_objects.json", "bbox_59.7950_30.3850_59.8240_30.4410_rail_objects.json"])

    if allow_default or alias_lower in ("default", "test", "demo", "sample"):
        ways_candidates.append("shushary_rail_ways.json")
        objects_candidates.append("shushary_rail_objects.json")

    ways_path: Optional[str] = None
    objs_path: Optional[str] = None

    for d in search_dirs:
        if not ways_path:
            for wc in ways_candidates:
                candidate_path = os.path.join(d, wc)
                if os.path.exists(candidate_path):
                    ways_path = candidate_path
                    break

        if not objs_path:
            for oc in objects_candidates:
                candidate_path = os.path.join(d, oc)
                if os.path.exists(candidate_path):
                    objs_path = candidate_path
                    break

        if ways_path and objs_path:
            break

    return ways_path, objs_path
