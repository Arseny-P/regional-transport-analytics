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
)
from graph_service.domain.errors import (
    TerritoryValidationError,
    FacilityValidationError,
)
from graph_service.algorithms.road_network_service import RoadNetworkService
from graph_service.algorithms.facility_service import FacilityService
from graph_service.algorithms.logistics_graph_service import LogisticsGraphService


class TerritoryAnalysisService:
    """
    Вызываемый интерфейс (Оркестратор) анализа произвольной территории.
    Инкапсулирует сквозной сценарий построения транспортно-логистического графа
    для вызова из Go-бэкенда или программных скриптов.
    """

    def __init__(self, default_storage_dir: str = "data"):
        self.default_storage_dir = default_storage_dir

    def run_analysis(self, request: AnalysisRequest) -> AnalysisResponse:
        """
        Запускает полный цикл анализа территории и возвращает структурированный AnalysisResponse.
        """
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
        # 2. Получение дорожной сети (кэш или OSM)
        # -----------------------------------------------------------------
        road_graph_path = os.path.join(storage_dir, f"{road_alias}.graphml")
        road_graph: Optional[nx.MultiDiGraph] = None

        try:
            if os.path.exists(road_graph_path) and not request.refetch:
                print(f"[*] Использование локального кэша дорожной сети: {road_graph_path}")
                road_graph = road_service.load_graphml(filename=road_alias)
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

        # -----------------------------------------------------------------
        # 3. Подготовка и валидация логистических объектов
        # -----------------------------------------------------------------
        user_nodes: List[LogisticsNode] = []
        osm_nodes: List[LogisticsNode] = []

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

        # -----------------------------------------------------------------
        # 4. Привязка объектов к дорожной сети (Snapping)
        # -----------------------------------------------------------------
        try:
            snapped_nodes = facility_service.snap_to_road_network(
                road_graph=road_graph, 
                nodes=all_nodes,
                max_snap_distance_m=request.max_snap_distance_m,
            )
        except Exception as snap_err:
            return AnalysisResponse(
                status=AnalysisStatus.ERROR.value,
                territory=territory_meta,
                error_message=f"Ошибка пространственной привязки к дорогам: {snap_err}",
                warnings=warnings,
            )

        # -----------------------------------------------------------------
        # 5. Синтез логистического MultiGraph и расчет маршрутов
        # -----------------------------------------------------------------
        try:
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
            "logistics_graphml": None,
            "logistics_geojson": None,
        }

        geojson_payload: Optional[Dict[str, Any]] = None

        if request.save_artifacts:
            graphml_file = logistics_service.save_graphml(log_graph=log_graph, filename=logistics_alias)
            geojson_file = logistics_service.export_to_geojson(log_graph=log_graph, filename=logistics_alias)
            artifacts["logistics_graphml"] = graphml_file
            artifacts["logistics_geojson"] = geojson_file

            if request.include_geojson_payload and os.path.exists(geojson_file):
                with open(geojson_file, "r", encoding="utf-8") as gf:
                    geojson_payload = json.load(gf)

        # -----------------------------------------------------------------
        # 7. Формирование структурированного ответа (Summary, Hubs, Connections)
        # -----------------------------------------------------------------
        graph_summary = logistics_service.get_summary(log_graph=log_graph)

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

        summary_data = {
            "total_road_nodes": len(road_graph.nodes),
            "total_road_edges": len(road_graph.edges),
            "total_hubs": len(snapped_nodes),
            "total_connections": len(connections_data),
            "connected_pairs_count": connected_pairs_count,
            "isolated_hubs_count": len(isolated_hubs),
            "avg_route_distance_km": graph_summary.get("avg_route_distance_km", 0.0),
            "execution_time_sec": elapsed,
        }

        return AnalysisResponse(
            status=status_result,
            territory=territory_meta,
            summary=summary_data,
            artifacts=artifacts,
            hubs=hubs_data,
            connections=connections_data,
            geojson=geojson_payload,
            warnings=warnings,
        )


BuildGraphUseCase = TerritoryAnalysisService

