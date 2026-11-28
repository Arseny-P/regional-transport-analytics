import os
import time
import json
from typing import Dict, Any, List, Optional
import networkx as nx

from graph_service.domain.models import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    TerritorySourceType,
    FacilitySourceType,
    TerritoryBounds,
    LogisticsNode,
    RouteStatus,
    TransportMode,
)
from graph_service.config import config
from graph_service.domain.errors import (
    TerritoryValidationError,
    FacilityValidationError,
    OfflineDataNotFoundError,
)
from graph_service.algorithms.road_network_service import RoadNetworkService
from graph_service.algorithms.facility_service import FacilityService
from graph_service.algorithms.logistics_graph_service import LogisticsGraphService
from graph_service.algorithms.rail_network_service import RailNetworkService
from graph_service.algorithms.rail_facility_service import RailFacilityService
from graph_service.application.cancellation import CancellationToken, TaskCancelledException


class TerritoryAnalysisService:
    """
    Вызываемый интерфейс (Оркестратор) анализа произвольной территории.
    Инкапсулирует сквозной сценарий построения транспортно-логистического графа
    для вызова из Go-бэкенда или программных скриптов.
    """

    def __init__(self, default_storage_dir: str = "data"):
        self.default_storage_dir = default_storage_dir

    def run_analysis(
        self,
        request: AnalysisRequest,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> AnalysisResponse:
        """
        Запускает полный цикл анализа территории и возвращает структурированный AnalysisResponse.
        Поддерживает кооперативную отмену через CancellationToken.
        """
        if cancellation_token:
            cancellation_token.check_cancelled()

        if request.transport_mode == TransportMode.RAIL.value:
            return self.run_rail_analysis(request, cancellation_token)

        start_time = time.time()
        warnings: List[str] = []
        storage_dir = request.output_dir or self.default_storage_dir
        os.makedirs(storage_dir, exist_ok=True)

        road_service = RoadNetworkService(storage_dir=storage_dir)
        facility_service = FacilityService(storage_dir=storage_dir)
        logistics_service = LogisticsGraphService(storage_dir=storage_dir)

        # -----------------------------------------------------------------
        # 1. Валидация входных параметров территории
        # -----------------------------------------------------------------
        territory_meta: Dict[str, Any] = {"type": request.territory_type}

        try:
            if request.territory_type == TerritorySourceType.BBOX.value:
                if request.bbox is None:
                    raise TerritoryValidationError("Для territory_type='bbox' необходимо передать объект 'bbox'.")
                request.bbox.validate()
                territory_meta["bbox"] = request.bbox.to_dict()
                alias_base = request.output_alias or request.bbox.cache_key()
            elif request.territory_type == TerritorySourceType.PLACE_NAME.value:
                if not request.place_name:
                    raise TerritoryValidationError("Для territory_type='place_name' необходимо указать 'place_name'.")
                territory_meta["place_name"] = request.place_name
                alias_base = request.output_alias or request.place_name.lower().replace(" ", "_").replace(",", "")
            else:
                raise TerritoryValidationError(f"Неизвестный тип территории: '{request.territory_type}'.")
        except (TerritoryValidationError, ValueError) as val_err:
            return AnalysisResponse(
                status=AnalysisStatus.ERROR.value,
                territory=territory_meta,
                error_message=f"Ошибка валидации территории: {val_err}",
                warnings=warnings,
            )

        road_alias = f"{alias_base}_roads"
        logistics_alias = f"{alias_base}_logistics"

        # -----------------------------------------------------------------
        # 1.1 Валидация пользовательских объектов (до загрузки дорожной сети)
        # -----------------------------------------------------------------
        user_nodes: List[LogisticsNode] = []
        try:
            if request.facility_source in [FacilitySourceType.USER_DEFINED.value, FacilitySourceType.HYBRID.value]:
                if not request.facilities:
                    if request.facility_source == FacilitySourceType.USER_DEFINED.value:
                        raise FacilityValidationError("Передан пустой список пользовательских объектов ('facilities').")
                else:
                    user_nodes = facility_service.parse_and_validate_facilities(
                        facilities_data=request.facilities,
                        territory_bounds=request.bbox,
                        filter_outside=False,
                    )
        except (FacilityValidationError, ValueError) as fac_err:
            return AnalysisResponse(
                status=AnalysisStatus.ERROR.value,
                territory=territory_meta,
                error_message=f"Ошибка валидации объектов: {fac_err}",
                warnings=warnings,
            )

        if cancellation_token:
            cancellation_token.check_cancelled()

        # -----------------------------------------------------------------
        # 2. Получение дорожной сети (кэш, оффлайн-фикстура или OSM)
        # -----------------------------------------------------------------
        road_graph_path = os.path.join(storage_dir, f"{road_alias}.graphml")
        road_graph: Optional[nx.MultiDiGraph] = None

        try:
            if os.path.exists(road_graph_path) and not request.refetch:
                print(f"[*] Использование локального кэша дорожной сети: {road_graph_path}")
                road_graph = road_service.load_graphml(filename=road_alias)
            else:
                from graph_service.fixtures import find_fixture_files
                road_fixture, _ = find_fixture_files(alias=road_alias, custom_dir=config.fixtures_dir)
                if not road_fixture:
                    road_fixture, _ = find_fixture_files(alias=alias_base, custom_dir=config.fixtures_dir)

                if road_fixture and (config.osm_offline_mode or not request.refetch):
                    print(f"[*] Использование оффлайн-фикстуры дорожной сети: {road_fixture}")
                    road_graph = road_service.load_graphml(filename=road_fixture)
                elif config.osm_offline_mode:
                    raise OfflineDataNotFoundError(
                        f"Включен оффлайн-режим (OSM_OFFLINE_MODE), но фикстура дорожной сети "
                        f"для территории '{alias_base}' не найдена."
                    )
                else:
                    if request.territory_type == TerritorySourceType.BBOX.value:
                        road_graph = road_service.fetch_and_build_from_bbox(bbox=request.bbox)
                    else:
                        road_graph = road_service.fetch_and_build(
                            place_name=request.place_name,
                            which_result=request.which_result,
                        )

                    if request.save_artifacts:
                        road_service.save_graphml(road_graph, filename=road_alias)
        except Exception as osm_err:
            return AnalysisResponse(
                status=AnalysisStatus.ERROR.value,
                territory=territory_meta,
                error_message=f"Ошибка получения дорожной сети: {osm_err}",
                warnings=warnings,
            )

        if not road_graph or len(road_graph.nodes) == 0:
            return AnalysisResponse(
                status=AnalysisStatus.ERROR.value,
                territory=territory_meta,
                error_message="Построенный дорожный граф пуст. Проверьте границы территории.",
                warnings=warnings,
            )

        if cancellation_token:
            cancellation_token.check_cancelled()

        # -----------------------------------------------------------------
        # 3. Подготовка и валидация логистических объектов OSM (если требуются)
        # -----------------------------------------------------------------
        osm_nodes: List[LogisticsNode] = []

        try:
            if request.facility_source in [FacilitySourceType.OSM.value, FacilitySourceType.HYBRID.value]:
                if request.territory_type == TerritorySourceType.BBOX.value:
                    osm_nodes = facility_service.fetch_from_osm_bbox(
                        bbox=request.bbox,
                        tags=request.osm_tags,
                        limit=request.osm_facilities_limit,
                    )
                else:
                    osm_nodes = facility_service.fetch_from_osm(
                        place_name=request.place_name,
                        tags=request.osm_tags,
                        limit=request.osm_facilities_limit,
                        which_result=request.which_result,
                    )
        except FacilityValidationError as fac_err:
            return AnalysisResponse(
                status=AnalysisStatus.ERROR.value,
                territory=territory_meta,
                error_message=f"Ошибка валидации объектов: {fac_err}",
                warnings=warnings,
            )
        except OfflineDataNotFoundError as off_err:
            return AnalysisResponse(
                status=AnalysisStatus.ERROR.value,
                territory=territory_meta,
                error_message=f"Ошибка оффлайн-источника данных: {off_err}",
                warnings=warnings,
            )
        except Exception as fac_fetch_err:
            warnings.append(f"Не удалось получить объекты из OSM: {fac_fetch_err}")

        all_nodes = user_nodes + osm_nodes
        if not all_nodes:
            return AnalysisResponse(
                status=AnalysisStatus.ERROR.value,
                territory=territory_meta,
                error_message="Не найдено ни одного логистического объекта для анализа.",
                warnings=warnings,
            )

        if len(all_nodes) < 2:
            warnings.append(
                f"Найдено только {len(all_nodes)} объектов. Для расчета маршрутов между объектами требуется минимум 2."
            )

        if cancellation_token:
            cancellation_token.check_cancelled()

        # -----------------------------------------------------------------
        # 4. Привязка объектов к дорожной сети (Snapping)
        # -----------------------------------------------------------------
        try:
            snapped_nodes = facility_service.snap_to_road_network(
                road_graph=road_graph, 
                nodes=all_nodes,
                max_snap_distance_m=request.max_snap_distance_m if request.max_snap_distance_m is not None else 250.0,
            )
        except Exception as snap_err:
            return AnalysisResponse(
                status=AnalysisStatus.ERROR.value,
                territory=territory_meta,
                error_message=f"Ошибка пространственной привязки к дорогам: {snap_err}",
                warnings=warnings,
            )

        if cancellation_token:
            cancellation_token.check_cancelled()

        # -----------------------------------------------------------------
        # 5. Синтез дорожного графа маршрутов и расчет маршрутов
        # -----------------------------------------------------------------
        try:
            # 5.1. Расчет детальных маршрутов между парами складов
            routes = logistics_service.calculate_all_routes(
                road_graph=road_graph,
                nodes=snapped_nodes,
                k_neighbors=request.knn,
            )

            # 5.2. Синтез единого дорожного графа маршрутов (Спринт 4)
            route_road_graph = logistics_service.build_route_road_graph(
                road_graph=road_graph,
                nodes=snapped_nodes,
                routes=routes,
                k_neighbors=request.knn,
            )

            # 5.3. Синтез логистического графа склад-склад (для сохранения обратной совместимости)
            log_graph = logistics_service.build_logistics_graph(
                road_graph=road_graph,
                snapped_nodes=snapped_nodes,
                k_neighbors=request.knn,
            )
        except Exception as routing_err:
            return AnalysisResponse(
                status=AnalysisStatus.ERROR.value,
                territory=territory_meta,
                error_message=f"Ошибка синтеза логистического графа: {routing_err}",
                warnings=warnings,
            )

        # -----------------------------------------------------------------
        # 6. Экспорт артефактов
        # -----------------------------------------------------------------
        artifacts: Dict[str, Optional[str]] = {
            "road_graphml": road_graph_path if os.path.exists(road_graph_path) else None,
            "route_road_graphml": None,
            "route_road_geojson": None,
            "logistics_graphml": None,
            "logistics_geojson": None,
        }

        geojson_payload: Optional[Dict[str, Any]] = None

        if request.save_artifacts:
            # Экспорт итогового дорожного графа маршрутов (Спринт 4)
            route_graphml_file = logistics_service.save_graphml(log_graph=route_road_graph, filename=f"{alias_base}_route_roads")
            route_geojson_file = logistics_service.export_route_road_graph_to_geojson(route_graph=route_road_graph, filename=f"{alias_base}_route_roads")
            artifacts["route_road_graphml"] = route_graphml_file
            artifacts["route_road_geojson"] = route_geojson_file

            # Экспорт логистического графа склад-склад (для обратной совместимости)
            graphml_file = logistics_service.save_graphml(log_graph=log_graph, filename=logistics_alias)
            geojson_file = logistics_service.export_to_geojson(log_graph=log_graph, filename=logistics_alias)
            artifacts["logistics_graphml"] = graphml_file
            artifacts["logistics_geojson"] = geojson_file

            if request.include_geojson_payload and os.path.exists(geojson_file):
                with open(geojson_file, "r", encoding="utf-8") as gf:
                    geojson_payload = json.load(gf)

        # -----------------------------------------------------------------
        # 7. Формирование структурированного ответа (Summary, Hubs, Connections, Routes)
        # -----------------------------------------------------------------
        graph_summary = logistics_service.get_summary(log_graph=log_graph)
        road_subgraph_summary = logistics_service.get_route_road_graph_summary(route_graph=route_road_graph)

        hubs_data: List[Dict[str, Any]] = [node.to_dict() for node in snapped_nodes]

        connections_data: List[Dict[str, Any]] = []
        isolated_hubs: set = {n.id for n in snapped_nodes}
        connected_pairs_count = 0

        for u, v, k, data in log_graph.edges(keys=True, data=True):
            status_ab = data.get("route_status_ab")
            status_ba = data.get("route_status_ba")

            is_connected = (status_ab == RouteStatus.FOUND.value) or (status_ba == RouteStatus.FOUND.value)
            if is_connected:
                isolated_hubs.discard(u)
                isolated_hubs.discard(v)
                connected_pairs_count += 1

            def safe_km(val: Any) -> Optional[float]:
                if val in (None, ""):
                    return None
                try:
                    return round(float(val) / 1000.0, 3)
                except (ValueError, TypeError):
                    return None

            connections_data.append({
                "from_hub_id": u,
                "to_hub_id": v,
                "node_a_name": data.get("node_a_name"),
                "node_b_name": data.get("node_b_name"),
                "transport_mode": data.get("transport_mode", "road"),
                "route_status_ab": status_ab,
                "route_status_ba": status_ba,
                "distance_ab_km": safe_km(data.get("distance_ab_m")),
                "distance_ba_km": safe_km(data.get("distance_ba_m")),
                "total_distance_ab_km": safe_km(data.get("total_distance_ab_m")),
                "total_distance_ba_km": safe_km(data.get("total_distance_ba_m")),
            })

        if isolated_hubs and len(all_nodes) > 1:
            warnings.append(
                f"Обнаружены изолированные объекты, до которых не удалось построить маршрут: {list(isolated_hubs)}"
            )

        status_result = AnalysisStatus.SUCCESS.value
        if isolated_hubs and len(isolated_hubs) == len(snapped_nodes) and len(snapped_nodes) > 1:
            status_result = AnalysisStatus.PARTIAL_SUCCESS.value
            warnings.append("Ни один маршрут между объектами не был найден в графе дорог.")

        elapsed = round(time.time() - start_time, 2)
        snap_summary = facility_service.get_snap_summary(snapped_nodes)

        summary_data = {
            "total_road_nodes": len(road_graph.nodes),
            "total_road_edges": len(road_graph.edges),
            "total_hubs": len(snapped_nodes),
            "connected_hubs_count": snap_summary.get("connected_count", 0),
            "isolated_hubs_count": len(isolated_hubs),
            "unique_snap_road_nodes": snap_summary.get("unique_primary_nodes", 0),
            "avg_snap_distance_m": snap_summary.get("avg_snap_distance_m", 0.0),
            "max_snap_distance_m": snap_summary.get("max_snap_distance_m", 0.0),
            "total_connections": len(connections_data),
            "connected_pairs_count": connected_pairs_count,
            "avg_route_distance_km": graph_summary.get("avg_route_distance_km", 0.0),
            "route_graph_nodes": road_subgraph_summary["total_nodes"],
            "route_graph_edges": road_subgraph_summary["total_edges"],
            "route_graph_intersections": road_subgraph_summary["intersections_count"],
            "route_graph_road_segments": road_subgraph_summary["road_segments_count"],
            "route_graph_access_connectors": road_subgraph_summary["access_connectors_count"],
            "execution_time_sec": elapsed,
        }

        return AnalysisResponse(
            status=status_result,
            territory=territory_meta,
            summary=summary_data,
            artifacts=artifacts,
            hubs=hubs_data,
            connections=connections_data,
            routes=[r.to_dict() for r in routes],
            geojson=geojson_payload,
            warnings=warnings,
            graph_object=route_road_graph,
        )

    def run_rail_analysis(
        self,
        request: AnalysisRequest,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> AnalysisResponse:
        """
        Запускает полный цикл анализа железнодорожной сети территории.
        Поддерживает кооперативную отмену через CancellationToken.
        """
        if cancellation_token:
            cancellation_token.check_cancelled()

        start_time = time.time()
        warnings: List[str] = []
        storage_dir = request.output_dir or self.default_storage_dir
        os.makedirs(storage_dir, exist_ok=True)

        rail_network_service = RailNetworkService(storage_dir=storage_dir)
        rail_facility_service = RailFacilityService(storage_dir=storage_dir)

        # 1. Валидация входных параметров территории
        territory_meta: Dict[str, Any] = {"type": request.territory_type}

        try:
            if request.territory_type == TerritorySourceType.BBOX.value:
                if request.bbox is None:
                    raise TerritoryValidationError("Для territory_type='bbox' необходимо передать объект 'bbox'.")
                request.bbox.validate()
                territory_meta["bbox"] = request.bbox.to_dict()
                alias_base = request.output_alias or request.bbox.cache_key()
            else:
                raise TerritoryValidationError(
                    f"Для железнодорожного анализа поддерживается territory_type='bbox', получено '{request.territory_type}'."
                )
        except (TerritoryValidationError, ValueError) as val_err:
            return AnalysisResponse(
                status=AnalysisStatus.ERROR.value,
                territory=territory_meta,
                error_message=f"Ошибка валидации территории: {val_err}",
                warnings=warnings,
            )

        if cancellation_token:
            cancellation_token.check_cancelled()

        # 2. Построение железнодорожной сети (Overpass / оффлайн-фикстуры)
        try:
            G_geom, G_simple = rail_network_service.build_from_bbox(
                bbox=request.bbox,
                refetch=request.refetch,
            )
        except OfflineDataNotFoundError as off_err:
            return AnalysisResponse(
                status=AnalysisStatus.ERROR.value,
                territory=territory_meta,
                error_message=f"Ошибка оффлайн-источника данных OSM: {off_err}",
                warnings=warnings,
            )
        except Exception as osm_err:
            return AnalysisResponse(
                status=AnalysisStatus.ERROR.value,
                territory=territory_meta,
                error_message=f"Ошибка получения железнодорожной сети OSM: {osm_err}",
                warnings=warnings,
            )

        if len(G_simple.nodes) == 0:
            return AnalysisResponse(
                status=AnalysisStatus.ERROR.value,
                territory=territory_meta,
                error_message="Построенный железнодорожный граф пуст. Проверьте границы территории.",
                warnings=warnings,
            )

        if cancellation_token:
            cancellation_token.check_cancelled()

        # 3. Извлечение станций-кандидатов из загруженных элементов OSM
        ways_dict, point_tags, objs_elements = rail_network_service.fetch_data_from_bbox(
            bbox=request.bbox,
            refetch=request.refetch,
        )
        candidates = rail_facility_service.extract_station_candidates(objs_elements)

        # Привязка подтвержденных станций-якорей (если переданы в request.facilities)
        anchors_map: Dict[str, List[str]] = {}
        if request.facilities:
            for fac_item in request.facilities:
                fac_id = str(fac_item.get("id") or fac_item.get("facility_id") or "")
                anc_list = fac_item.get("anchor_node_ids") or []
                if fac_id and anc_list:
                    anchors_map[fac_id] = [str(a) for a in anc_list]

        facilities = rail_facility_service.bind_station_anchors(
            facilities=candidates,
            anchors_map=anchors_map,
            graph=G_simple,
        )

        # 4. Построение направленного графа маршрутизации
        routing_graph = rail_network_service.to_routing_graph(G_simple)
        routing_graph.graph["transport_mode"] = "rail"
        routing_graph.graph["physical_graph"] = G_simple
        routing_graph.graph["facilities"] = facilities

        G_simple.graph["transport_mode"] = "rail"
        G_simple.graph["facilities"] = facilities

        # Привязка станций в routing_graph при наличии якорей
        if anchors_map:
            rail_facility_service.bind_station_anchors(
                facilities=facilities,
                anchors_map=anchors_map,
                graph=routing_graph,
            )

        if cancellation_token:
            cancellation_token.check_cancelled()

        # 5. Экспорт артефактов (если включено)
        artifacts: Dict[str, Optional[str]] = {}
        geojson_payload: Optional[Dict[str, Any]] = None

        if request.save_artifacts:
            rail_alias = alias_base if alias_base.endswith("_rail") else f"{alias_base}_rail"
            rail_graphml_file = os.path.join(storage_dir, f"{rail_alias}_simple.graphml")
            try:
                nx.write_graphml(G_simple, rail_graphml_file)
                artifacts["rail_graphml"] = rail_graphml_file
            except Exception:
                pass

            try:
                rail_geojson_file = rail_network_service.export_to_geojson(
                    graph=G_simple,
                    filename=rail_alias,
                    facilities=facilities,
                )
                artifacts["rail_geojson"] = rail_geojson_file
                if request.include_geojson_payload and os.path.exists(rail_geojson_file):
                    with open(rail_geojson_file, "r", encoding="utf-8") as gf:
                        geojson_payload = json.load(gf)
            except Exception as geo_err:
                warnings.append(f"Не удалось экспортировать ЖД GeoJSON: {geo_err}")

        elapsed = round(time.time() - start_time, 2)
        connected_facs = rail_facility_service.get_connected_facilities(facilities)

        summary_data = {
            "total_rail_nodes": len(G_simple.nodes),
            "total_physical_segments": len(G_simple.edges),
            "total_directed_edges": len(routing_graph.edges),
            "station_candidates_count": len(candidates),
            "connected_stations_count": len(connected_facs),
            "switch_count": len([n for n, d in G_simple.nodes(data=True) if d.get("is_switch")]),
            "execution_time_sec": elapsed,
        }

        hubs_data: List[Dict[str, Any]] = [
            {
                "id": f.facility_id,
                "name": f.name,
                "latitude": f.latitude,
                "longitude": f.longitude,
                "anchor_node_ids": f.anchor_node_ids,
                "connection_status": f.connection_status,
                "cargo_status": f.cargo_status,
            }
            for f in facilities
        ]

        return AnalysisResponse(
            status=AnalysisStatus.SUCCESS.value,
            territory=territory_meta,
            summary=summary_data,
            artifacts=artifacts,
            hubs=hubs_data,
            connections=[],
            routes=[],
            geojson=geojson_payload,
            warnings=warnings,
            graph_object=routing_graph,
            facilities=facilities,
            physical_graph=G_simple,
        )


BuildGraphUseCase = TerritoryAnalysisService

