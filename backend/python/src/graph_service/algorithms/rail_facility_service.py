import os
import json
from typing import Dict, Any, List, Optional, Set
import networkx as nx

from graph_service.domain.models import (
    RailFacility,
    RailObjectType,
    RailNodeKind,
    RailConnectionStatus,
)


class RailFacilityService:
    """
    Сервис управления железнодорожными станциями и логистическими объектами:
    - Извлечение станций-кандидатов из сырых данных OSM.
    - Отсев станций метрополитена.
    - Управление подтвержденными точками подключения (anchor_node_ids).
    - Интеграция точек подключения в граф без создания искусственных внутренних соединений.
    """

    def __init__(self, storage_dir: str = "data"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)

    @staticmethod
    def is_subway_station(tags: Dict[str, Any]) -> bool:
        """
        Проверяет, относится ли станция к метрополитену (должна быть исключена).
        """
        station_type = str(tags.get("station", "")).strip().lower()
        subway_flag = str(tags.get("subway", "")).strip().lower()
        network = str(tags.get("network", "")).strip().lower()
        operator = str(tags.get("operator", "")).strip().lower()

        if station_type == "subway" or subway_flag in {"yes", "true", "1"}:
            return True
        if "метро" in network or "метро" in operator:
            return True
        return False

    def extract_station_candidates(
        self, elements: List[Dict[str, Any]]
    ) -> List[RailFacility]:
        """
        Извлекает кандидатов железнодорожных станций из элементов OSM:
        - Отбирает railway=station.
        - Исключает станции метрополитена.
        - Сохраняет исходные координаты, теги и статус connection_status=not_checked.
        """
        candidates: List[RailFacility] = []

        for el in elements:
            tags = el.get("tags", {})
            if tags.get("railway") != "station":
                continue

            # Отсев метро
            if self.is_subway_station(tags):
                continue

            lat = el.get("lat")
            lon = el.get("lon")
            if lat is None or lon is None:
                center = el.get("center", {})
                lat = center.get("lat")
                lon = center.get("lon")

            if lat is None or lon is None:
                continue

            name = tags.get("name") or f"Станция {el['id']}"
            osm_type = el.get("type", "node")
            source_id = f"{osm_type}/{el['id']}"
            facility_id = f"station:{el['id']}"

            # Проверка оснований для грузовой роли
            is_cargo = (
                str(tags.get("cargo", "")).lower() in {"yes", "true", "1"}
                or tags.get("station") == "freight"
                or tags.get("transport") == "freight"
            )
            cargo_status = "verified" if is_cargo else "unknown"
            cargo_evidence = "osm_tag:cargo=yes" if is_cargo else None

            facility = RailFacility(
                facility_id=facility_id,
                name=name,
                latitude=float(lat),
                longitude=float(lon),
                anchor_node_ids=[],
                connection_status=RailConnectionStatus.NOT_CHECKED.value,
                cargo_status=cargo_status,
                cargo_evidence=cargo_evidence,
                source_osm_ids=[source_id],
                source_tags=tags,
            )
            candidates.append(facility)

        return candidates

    def bind_station_anchors(
        self,
        facilities: List[RailFacility],
        anchors_map: Dict[str, List[str]],
        graph: Optional[nx.Graph] = None,
    ) -> List[RailFacility]:
        """
        Привязывает проверенные точки подключения (anchor_node_ids) к станциям:
        - Станция остается единым объектом, но может иметь список anchor_node_ids.
        - Валидирует наличие узлов-якорей в графе.
        - Обновляет атрибуты узлов в графе (object_type='rail_facility', node_kind='station').
        - СТРОГОЕ ПРАВИЛО: не создает искусственных рёбер между точками подключения
          одной станции («бесплатные соединения» запрещены; движение между путями
          станции возможно только по реальным рельсам).
        """
        graph_nodes = set(graph.nodes()) if graph is not None else None

        for fac in facilities:
            # Поиск по facility_id или точному имени
            raw_anchors = (
                anchors_map.get(fac.facility_id)
                or anchors_map.get(fac.name)
                or anchors_map.get(str(fac.source_osm_ids[0]).split("/")[-1])
            )

            if not raw_anchors:
                continue

            valid_anchors = []
            for anc in raw_anchors:
                anc_str = str(anc)
                # Нормализация префикса (например, osm_node:123 или просто 123)
                matched_id = None
                if graph_nodes:
                    if anc_str in graph_nodes:
                        matched_id = anc_str
                    elif f"osm_node:{anc_str}" in graph_nodes:
                        matched_id = f"osm_node:{anc_str}"
                    else:
                        for gn in graph_nodes:
                            if gn.endswith(f":{anc_str}") or gn == anc_str:
                                matched_id = gn
                                break
                else:
                    matched_id = anc_str

                if matched_id:
                    valid_anchors.append(matched_id)
                    if graph is not None and matched_id in graph:
                        graph.nodes[matched_id]["object_type"] = RailObjectType.RAIL_FACILITY.value
                        graph.nodes[matched_id]["node_kind"] = RailNodeKind.STATION.value
                        graph.nodes[matched_id]["facility_id"] = fac.facility_id
                        graph.nodes[matched_id]["facility_name"] = fac.name

            if valid_anchors:
                fac.anchor_node_ids = valid_anchors
                fac.connection_status = RailConnectionStatus.CONNECTED.value
            else:
                fac.connection_status = RailConnectionStatus.NOT_CONNECTED.value

        return facilities

    @staticmethod
    def get_connected_facilities(facilities: List[RailFacility]) -> List[RailFacility]:
        """
        Возвращает только те станции, у которых есть подтвержденные точки подключения к сети.
        """
        return [
            f
            for f in facilities
            if f.connection_status == RailConnectionStatus.CONNECTED.value and len(f.anchor_node_ids) > 0
        ]

    @staticmethod
    def get_verified_station_count(facilities: List[RailFacility]) -> int:
        """
        Возвращает количество уникальных проверенных станций, подключенных к сети.
        """
        connected = [
            f for f in facilities if f.connection_status == RailConnectionStatus.CONNECTED.value
        ]
        unique_names = {f.name for f in connected}
        return len(unique_names)
