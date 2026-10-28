import os
import sys
import json
import argparse
from typing import Optional, List, Dict, Any

from models import (
    AnalysisRequest,
    AnalysisResponse,
    TerritoryBounds,
    TerritorySourceType,
    FacilitySourceType,
    AnalysisStatus,
)
from services import TerritoryAnalysisService


def parse_args():
    parser = argparse.ArgumentParser(
        description="Транспортно-логистический аналитический сервис: построение дорожной сети и логистического MultiGraph."
    )

    # 1. Параметры территории
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("MIN_LAT", "MIN_LON", "MAX_LAT", "MAX_LON"),
        help="Координаты исследуемой территории (Bounding Box): min_lat min_lon max_lat max_lon",
    )
    parser.add_argument(
        "--place",
        "--place-name",
        type=str,
        dest="place_name",
        help="Название территории для геокодирования OSM (например: 'Выборг, Россия')",
    )
    parser.add_argument(
        "--shushary",
        "--shushary-district",
        action="store_true",
        help="Демонстрационный запуск для логистического кластера Шушары (СПб)",
    )

    # 2. Логистические объекты
    parser.add_argument(
        "--facilities-file",
        type=str,
        help="Путь к пользовательскому JSON-файлу с логистическими объектами",
    )
    parser.add_argument(
        "--osm-pois",
        "--osm-points",
        action="store_true",
        help="Запросить логистические/промышленные объекты напрямую из OpenStreetMap",
    )
    parser.add_argument(
        "--osm-limit",
        type=int,
        default=100,
        help="Лимит количества объектов при выгрузке из OSM (по умолчанию: 15)",
    )

    # 3. Алгоритмы и параметры графа
    parser.add_argument(
        "--knn",
        type=int,
        help="Количество k-ближайших соседей для разреживания логистического графа (k-NN)",
    )
    parser.add_argument(
        "--refetch",
        action="store_true",
        help="Принудительно перезагрузить дорожную сеть из OSM, игнорируя локальный кэш",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data",
        help="Каталог для сохранения артефактов и кэша (по умолчанию: 'data')",
    )

    # 4. Входные/выходные данные для интеграции с Go
    parser.add_argument(
        "--input-json",
        type=str,
        help="Путь к файлу AnalysisRequest JSON (контракт прямого вызова из Go-бэкенда)",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        help="Путь для сохранения результата AnalysisResponse JSON",
    )

    return parser.parse_args()


def main():
    args = parse_args()
    service = TerritoryAnalysisService(default_storage_dir=args.data_dir)

    print("=" * 65)
    print("ТРАНСПОРТНО-ЛОГИСТИЧЕСКИЙ АНАЛИТИЧЕСКИЙ СЕРВИС (СПРИНТ 2)")
    print("Модульная архитектура: Arbitrary Territory + MultiGraph + Go DTO")
    print("=" * 65)

    # СЦЕНАРИЙ А: Прямой вызов через контрактный JSON от Go-бэкенда
    if args.input_json:
        if not os.path.exists(args.input_json):
            print(f"[-] Ошибка: входной файл JSON не найден: {args.input_json}", file=sys.stderr)
            sys.exit(1)

        print(f"[*] Загрузка входного запроса из JSON: {args.input_json}")
        with open(args.input_json, "r", encoding="utf-8") as f:
            req_data = json.load(f)

        request = AnalysisRequest.from_dict(req_data)
        if args.refetch:
            request.refetch = True
        if args.knn is not None:
            request.knn = args.knn

        response = service.run_analysis(request)

        if args.output_json:
            with open(args.output_json, "w", encoding="utf-8") as out_f:
                json.dump(response.to_dict(), out_f, ensure_ascii=False, indent=2)
            print(f"[+] Результат анализа успешно сохранен в JSON: {args.output_json}")

        print_response_summary(response)
        sys.exit(0 if response.status == AnalysisStatus.SUCCESS.value else 1)

    # СЦЕНАРИЙ Б: Интерактивный запуск через аргументы командной строки
    territory_type = TerritorySourceType.PLACE_NAME.value
    bbox_obj: Optional[TerritoryBounds] = None
    place_name: Optional[str] = None
    which_result: Optional[int] = None
    output_alias: Optional[str] = None
    seed_points_file: Optional[str] = None

    if args.bbox:
        min_lat, min_lon, max_lat, max_lon = args.bbox
        territory_type = TerritorySourceType.BBOX.value
        bbox_obj = TerritoryBounds(
            min_lat=min_lat,
            min_lon=min_lon,
            max_lat=max_lat,
            max_lon=max_lon,
        )
        output_alias = bbox_obj.cache_key()
        area_title = f"BBox (lat: [{bbox_obj.min_lat}, {bbox_obj.max_lat}], lon: [{bbox_obj.min_lon}, {bbox_obj.max_lon}])"
    elif args.shushary:
        territory_type = TerritorySourceType.PLACE_NAME.value
        place_name = "Шушары, Санкт-Петербург, Россия"
        which_result = 3
        output_alias = "shushary"
        seed_points_file = "test_shushary_points.json"
        area_title = place_name
    elif args.place_name:
        territory_type = TerritorySourceType.PLACE_NAME.value
        place_name = args.place_name
        output_alias = place_name.lower().replace(" ", "_").replace(",", "")
        area_title = place_name
    else:
        # По умолчанию: демонстрация на полигоне Кронштадта
        territory_type = TerritorySourceType.PLACE_NAME.value
        place_name = "Кронштадт, Россия"
        which_result = None
        output_alias = "kronshtadt"
        seed_points_file = "test_logistics_points.json"
        area_title = place_name

    print(f"Целевая территория: {area_title}")

    # Загрузка объектов
    user_facilities: List[Dict[str, Any]] = []
    facilities_path = args.facilities_file
    if not facilities_path and seed_points_file:
        facilities_path = os.path.join(args.data_dir, seed_points_file)

    if facilities_path and os.path.exists(facilities_path):
        print(f"[*] Чтение логистических объектов из файла: {facilities_path}")
        with open(facilities_path, "r", encoding="utf-8") as f:
            user_facilities = json.load(f)

    if args.osm_pois or (not user_facilities):
        if not user_facilities:
            print("[*] Пользовательский файл объектов не передан: активирован автоматический поиск объектов в OpenStreetMap.")
        facility_source = FacilitySourceType.HYBRID.value if user_facilities else FacilitySourceType.OSM.value
    else:
        facility_source = FacilitySourceType.USER_DEFINED.value


    request = AnalysisRequest(
        territory_type=territory_type,
        bbox=bbox_obj,
        place_name=place_name,
        which_result=which_result,
        facility_source=facility_source,
        facilities=user_facilities,
        osm_facilities_limit=args.osm_limit,
        knn=args.knn,
        output_dir=args.data_dir,
        output_alias=output_alias,
        save_artifacts=True,
        include_geojson_payload=True,
        refetch=args.refetch,
    )

    response = service.run_analysis(request)

    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as out_f:
            json.dump(response.to_dict(), out_f, ensure_ascii=False, indent=2)
        print(f"\n[+] Структурированный ответ сохранен в: {args.output_json}")

    print_response_summary(response)


def print_response_summary(response: AnalysisResponse):
    print("\n" + "=" * 65)
    print(f"РЕЗУЛЬТАТЫ АНАЛИЗА: СТАТУС [{response.status.upper()}]")
    print("=" * 65)

    if response.error_message:
        print(f"[-] Сообщение об ошибке: {response.error_message}")

    summary = response.summary
    if summary:
        print(f"• Дорожная сеть: {summary.get('total_road_nodes', 0)} узлов, {summary.get('total_road_edges', 0)} ребер")
        print(f"• Логистических хабов: {summary.get('total_hubs', 0)} (изолированных: {summary.get('isolated_hubs_count', 0)})")
        print(f"• Построено связей: {summary.get('total_connections', 0)} (связанных пар: {summary.get('connected_pairs_count', 0)})")
        print(f"• Средняя протяженность маршрута: {summary.get('avg_route_distance_km', 0.0)} км")
        print(f"• Время выполнения анализа: {summary.get('execution_time_sec', 0.0)} сек.")

    if response.artifacts:
        print("\nСозданные артефакты:")
        for k, v in response.artifacts.items():
            if v:
                print(f"  • {k}: {v}")

    if response.connections:
        print("\nПримеры рассчитанных связей (с раздельными плечами A→B и B→A):")
        for conn in response.connections[:3]:
            pair_name = f"{conn.get('node_a_name')} ⟷ {conn.get('node_b_name')}"
            dist_ab = f"{conn.get('total_distance_ab_km')} км" if conn.get('total_distance_ab_km') is not None else "Н/Д"
            dist_ba = f"{conn.get('total_distance_ba_km')} км" if conn.get('total_distance_ba_km') is not None else "Н/Д"
            print(f"  • {pair_name}:")
            print(f"      ➔ Вперёд (A->B): {dist_ab} [статус: {conn.get('route_status_ab')}]")
            print(f"      ⬅ Обратно (B->A): {dist_ba} [статус: {conn.get('route_status_ba')}]")

    if response.warnings:
        print("\nПредупреждения:")
        for w in response.warnings:
            print(f"  [!] {w}")
    print("=" * 65)


if __name__ == "__main__":
    main()