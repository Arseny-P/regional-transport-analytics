import os
from typing import Optional, Tuple

FIXTURES_DIR = os.path.dirname(os.path.abspath(__file__))


def find_fixture_files(
    alias: str,
    custom_dir: Optional[str] = None,
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
    search_dirs = []
    if custom_dir and os.path.exists(custom_dir):
        search_dirs.append(custom_dir)
    search_dirs.append(FIXTURES_DIR)

    data_dir = os.getenv("DATA_DIR")
    if data_dir and os.path.exists(data_dir) and data_dir not in search_dirs:
        search_dirs.append(data_dir)

    road_candidates = [
        f"{alias}_roads.graphml",
        f"{alias}.graphml",
        "kronshtadt_roads.graphml",
        "default_roads.graphml",
    ]

    fac_candidates = [
        f"{alias}_facilities.json",
        f"{alias}_facilities.geojson",
        f"{alias}.json",
        "kronshtadt_facilities.json",
        "default_facilities.json",
        "test_logistics_points.json",
    ]

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
