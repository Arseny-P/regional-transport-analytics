import os
import sys
from services import RoadNetworkService, FacilityService, LogisticsGraphService

def main():
    DATA_DIR = "data"
    road_service = RoadNetworkService(storage_dir=DATA_DIR)
    facility_service = FacilityService(storage_dir=DATA_DIR)
    logistics_service = LogisticsGraphService(storage_dir=DATA_DIR)
    
    AREA_NAME = "Кронштадт, Россия"
    ROAD_GRAPH_ALIAS = "kronshtadt_network"
    LOGISTICS_GRAPH_ALIAS = "kronshtadt_logistics"
    SEED_POINTS_FILE = "test_logistics_points.json"

    print("=" * 60)
    print("ТРАНСПОРТНО-ЛОГИСТИЧЕСКИЙ АНАЛИТИЧЕСКИЙ СЕРВИС")
    print("Модульная архитектура: RoadNetwork + Facilities + LogisticsGraph")
    print("=" * 60)

    # ----------------------------------------------------
    # ШАГ 1: Получение автомобильной дорожной сети
    # ----------------------------------------------------
    print("\n>>> ШАГ 1: Загрузка автомобильной дорожной сети...")
    road_graph_path = os.path.join(DATA_DIR, f"{ROAD_GRAPH_ALIAS}.graphml")
    
    if os.path.exists(road_graph_path) and "--refetch" not in sys.argv:
        print(f"[*] Использование локального кэша дорожного графа: {road_graph_path}")
        road_graph = road_service.load_graphml(filename=ROAD_GRAPH_ALIAS)
    else:
        print(f"[*] Скачивание дорожной сети из OSM для: '{AREA_NAME}'...")
        road_graph = road_service.fetch_and_build(place_name=AREA_NAME)
        road_service.save_graphml(road_graph, filename=ROAD_GRAPH_ALIAS)
        road_service.export_to_geojson(road_graph, filename=ROAD_GRAPH_ALIAS)

    road_summary = road_service.get_summary(road_graph)
    print(f"[V] Дорожная сеть готова: {road_summary['total_nodes']} перекрестков, {road_summary['total_edges']} сегментов дорог.")

    # ----------------------------------------------------
    # ШАГ 2: Подготовка набора логистических объектов
    # ----------------------------------------------------
    print("\n>>> ШАГ 2: Подготовка логистических объектов...")
    points = facility_service.load_from_json(filepath=SEED_POINTS_FILE)
    print(f"[*] Загружено {len(points)} объектов из seed-файла:")
    for p in points:
        print(f"   • [{p['type'].upper()}] {p['name']} (lat: {p['lat']}, lon: {p['lon']})")

    # Демонстрация универсальной выгрузки из OSM по ключу
    use_osm_pois = "--osm-pois" in sys.argv or "--osm-points" in sys.argv
    osm_points = []
    if use_osm_pois:
        print("\n[*] Запрос объектов напрямую из OSM...")
        osm_points = facility_service.fetch_from_osm(place_name=AREA_NAME, limit=5)
        if osm_points:
            print(f"[*] Получено {len(osm_points)} объектов из OSM:")
            for op in osm_points:
                print(f"   • {op['name']} ({op['type']})")

    # ----------------------------------------------------
    # ШАГ 3: Привязка логистических объектов к дорожной сети
    # ----------------------------------------------------
    print("\n>>> ШАГ 3: Привязка (Snapping) логистических объектов к графу дорог...")
    active_points = osm_points + points if (use_osm_pois and osm_points) else points
    snapped_nodes = facility_service.snap_to_road_network(road_graph=road_graph, nodes=active_points)
    print(f"[V] Все {len(snapped_nodes)} объектов успешно привязаны к вершинам графа OSM.")

    # ----------------------------------------------------
    # ШАГ 4: Построение логистического MultiGraph
    # ----------------------------------------------------
    print("\n>>> ШАГ 4: Расчет автомобильных маршрутов и синтез логистического MultiGraph...")
    log_graph = logistics_service.build_logistics_graph(road_graph=road_graph, snapped_nodes=snapped_nodes)

    summary = logistics_service.get_summary(log_graph=log_graph)
    print(f"\n--- Сводка логистического MultiGraph ---")
    print(f"Хабов (вершин): {summary['total_hubs']}")
    print(f"Логистических связей: {summary['total_connections']}")
    print(f"Средняя длина маршрута: {summary['avg_route_distance_km']} км")
    
    print("\nПримеры рассчитанных связей (с раздельными плечами A→B и B→A):")
    for conn in summary["sample_connections"]:
        print(f"  • {conn['pair']} [{conn['mode'].upper()}]:")
        print(f"      ➔ Вперёд (A->B): {conn['dist_ab_km']} км (статус: {conn['status_ab']})")
        print(f"      ⬅ Обратно (B->A): {conn['dist_ba_km']} км (статус: {conn['status_ba']})")

    # ----------------------------------------------------
    # ШАГ 5: Экспорт и сериализация логистического графа
    # ----------------------------------------------------
    print("\n>>> ШАГ 5: Экспорт и сериализация логистического графа...")
    graphml_path = logistics_service.save_graphml(log_graph=log_graph, filename=LOGISTICS_GRAPH_ALIAS)
    geojson_path = logistics_service.export_to_geojson(log_graph=log_graph, filename=LOGISTICS_GRAPH_ALIAS)

    # ----------------------------------------------------
    # ШАГ 6: Проверка повторной оффлайн-загрузки
    # ----------------------------------------------------
    print("\n>>> ШАГ 6: Проверка повторной загрузки из GraphML...")
    restored_log_graph = logistics_service.load_graphml(filename=LOGISTICS_GRAPH_ALIAS)
    
    assert len(log_graph.nodes) == len(restored_log_graph.nodes), "Не совпало количество вершин!"
    assert len(log_graph.edges) == len(restored_log_graph.edges), "Не совпало количество ребер!"
    print(f"[V] Тест оффлайн-восстановления пройден успешно! Совпадение 100%.")

    print("\n" + "=" * 60)
    print("ИТОГИ ВЫПОЛНЕНИЯ СПРИНТ-ЗАДАЧИ:")
    print(f"1. Дорожная сеть:           {road_graph_path}")
    print(f"2. Логистический GraphML:   {graphml_path} (для ML)")
    print(f"3. Логистический GeoJSON:   {geojson_path} (для Frontend)")
    print("=" * 60)

if __name__ == "__main__":
    main()