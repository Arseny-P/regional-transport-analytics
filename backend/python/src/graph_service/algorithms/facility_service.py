import os
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import isfinite
from numbers import Integral
from typing import List, Dict, Any, Optional, Tuple, Set
import networkx as nx
import osmnx as ox
import pandas as pd
from shapely.geometry import Point, LineString
from shapely.ops import substring
from graph_service.domain.models import (
    LogisticsNode,
    VerificationStatus,
    GraphRole,
    TransportMode,
    TerritoryBounds,
)
from graph_service.domain.errors import FacilityValidationError
import geopandas as gpd
from graph_service.http.osm_client import execute_with_overpass_fallback


WAREHOUSE_OSM_TAGS = {
    "building": ["warehouse"],
    "building:use": ["warehouse"],
    "industrial": ["warehouse", "logistics"],
    "amenity": ["warehouse"],
}

WAREHOUSE_TAGS = ("building:use", "building", "industrial")
TAGS_TO_KEEP = (*WAREHOUSE_TAGS, "landuse", "amenity", "name", "operator", "disused", "abandoned")
POLYGON_TYPES = {"Polygon", "MultiPolygon"}
WAREHOUSE_WORDS = ("склад", "логист", "распределительн", "warehouse", "logistics")


@dataclass(frozen=True)
class WarehouseInput:
    osm_id: str
    tags: Mapping[str, object]
    latitude: float | None
    longitude: float | None
    polygon_area_m2: float | None = None
    enclosing_site_ids: tuple[str, ...] = ()


class FacilityService:
    """
    Сервис управления логистическими объектами (хабы, склады, порты):
    загрузка, фильтрация, умный поиск в OSM и пространственная привязка (snapping) к дорожной сети.
    """

    EXCLUDE_KEYWORDS = [
        "котельная", "тэц", "трансформатор", "подстанция", "гараж", 
        "кнс", "насосная", "гск", "свалка", "шиномонтаж", "автомойка"
    ]

    EXCLUDE_DEPOT_TYPES = {
        "bus", "tram", "subway", "trolleybus", "passengers", "metro"
    }

    LOGISTICS_KEYWORDS = [
        "склад", "терминал", "логистическ", "распределительн", "рц", "грузов",
        "порт", "логистик", "warehouse", "terminal", "logistics", "freight", "cargo"
    ]

    DEFAULT_OSM_TAGS = {
        "landuse": ["industrial", "port", "depot", "logistics"],
        "building": ["warehouse", "industrial"],
        "harbour": True,
        "amenity": ["post_office"],
        "industrial": ["warehouse", "port", "depot", "logistics"],
        "railway": ["yard", "loading_ramp"],
        "port": ["cargo"],
    }

    WAREHOUSE_OSM_TAGS = WAREHOUSE_OSM_TAGS
    WAREHOUSE_TAGS = WAREHOUSE_TAGS
    TAGS_TO_KEEP = TAGS_TO_KEEP
    POLYGON_TYPES = POLYGON_TYPES
    WAREHOUSE_WORDS = WAREHOUSE_WORDS

    def __init__(self, storage_dir: str = "data"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        self.last_audit_log: List[Dict[str, Any]] = []

    def parse_and_validate_facilities(
        self,
        facilities_data: List[Dict[str, Any]],
        territory_bounds: Optional[TerritoryBounds] = None,
        filter_outside: bool = False,
    ) -> List[LogisticsNode]:
        """
        Валидирует и преобразует произвольный пользовательский набор объектов в список LogisticsNode.
        Проверяет наличие координат, корректность диапазонов, уникальность ID и границы территории.
        """
        if not isinstance(facilities_data, list):
            raise FacilityValidationError("Набор данных логистических объектов должен быть списком (list).")

        if not facilities_data:
            raise FacilityValidationError("Передан пустой список логистических объектов.")

        nodes: List[LogisticsNode] = []
        seen_ids = set()

        for idx, item in enumerate(facilities_data, start=1):
            if not isinstance(item, dict):
                raise FacilityValidationError(f"Элемент #{idx} должен быть словарем (dict), получено: {type(item).__name__}")

            raw_id = item.get("id")
            node_id = str(raw_id).strip() if raw_id is not None and str(raw_id).strip() else f"node_{idx}"
            if node_id in seen_ids:
                node_id = f"{node_id}_{idx}"
            seen_ids.add(node_id)

            name = str(item.get("name") or f"Объект #{idx}").strip()
            obj_type = str(item.get("type") or item.get("object_type") or "facility").strip()

            lat_val = item.get("lat") if "lat" in item else item.get("latitude")
            lon_val = item.get("lon") if "lon" in item else item.get("longitude")

            if lat_val is None or lon_val is None:
                raise FacilityValidationError(f"Объект '{name}' (ID: {node_id}) не содержит обязательных координат 'lat' / 'lon'.")

            try:
                lat = float(lat_val)
                lon = float(lon_val)
            except (ValueError, TypeError):
                raise FacilityValidationError(f"Координаты объекта '{name}' (ID: {node_id}) должны быть числами. Получено: lat={lat_val}, lon={lon_val}")

            if not (-90.0 <= lat <= 90.0):
                raise FacilityValidationError(f"Широта объекта '{name}' ({lat}) вне диапазона [-90, 90].")
            if not (-180.0 <= lon <= 180.0):
                raise FacilityValidationError(f"Долгота объекта '{name}' ({lon}) вне диапазона [-180, 180].")

            if territory_bounds is not None and not territory_bounds.contains(lat, lon):
                warning_msg = f"[!] Внимание: объект '{name}' ({lat:.4f}, {lon:.4f}) находится за пределами территории {territory_bounds.to_dict()}."
                if filter_outside:
                    print(f"{warning_msg} Объект отфильтрован.")
                    continue
                else:
                    print(warning_msg)

            node = LogisticsNode(
                id=node_id,
                name=name,
                object_type=obj_type,
                latitude=round(lat, 6),
                longitude=round(lon, 6),
                region_ids=item.get("region_ids", ["custom-region"]),
                source_osm_ids=item.get("source_osm_ids", []),
                verification_status=item.get("verification_status", VerificationStatus.VERIFIED.value),
                transport_modes=item.get("transport_modes", [TransportMode.ROAD.value]),
                identification_basis=item.get("identification_basis", {"source": "user_input"}),
                parent_site_id=item.get("parent_site_id"),
                graph_role=item.get("graph_role", GraphRole.NODE_CANDIDATE.value),
            )
            nodes.append(node)

        if not nodes:
            raise FacilityValidationError("После валидации и фильтрации не осталось ни одного валидного объекта.")

        return nodes

    def load_from_json(self, filepath: str, territory_bounds: Optional[TerritoryBounds] = None) -> List[LogisticsNode]:
        """
        Загружает тестовый или пользовательский набор логистических объектов из JSON-файла с валидацией.
        """
        if not os.path.isabs(filepath):
            filepath = os.path.join(self.storage_dir, filepath)

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Файл логистических объектов не найден: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            raw_data: List[Dict[str, Any]] = json.load(f)

        nodes = self.parse_and_validate_facilities(raw_data, territory_bounds=territory_bounds)
        print(f"[+] Загружено и валидировано {len(nodes)} логистических объектов из файла: {filepath}")
        return nodes

    @staticmethod
    def _format_osm_id(idx_val: Any, row: Any = None) -> str:
        """
        Форматирует ID элемента в устойчивый вид согласно спецификации PM (п. 3.4):
        osm:way/12345, osm:relation/67890, osm:node/111.
        """
        if isinstance(idx_val, tuple) and len(idx_val) == 2:
            return f"osm:{idx_val[0]}/{idx_val[1]}"
        
        elem_type = None
        if hasattr(row, "get"):
            elem_type = row.get("element_type")
        elif hasattr(row, "element_type"):
            elem_type = getattr(row, "element_type")

        if elem_type and not str(idx_val).startswith(str(elem_type)):
            return f"osm:{elem_type}/{idx_val}"
        idx_str = str(idx_val)
        if idx_str.startswith("osm:"):
            return idx_str
        return f"osm:{idx_str}"

    def _extract_nodes_from_gdf(
        self,
        gdf: Any,
        limit: int = 15,
        region_id: str = "ru-spb",
    ) -> List[LogisticsNode]:
        """
        Извлекает, классифицирует и разделяет логистические объекты на здания и территории
        согласно пунктам 3.2 и 3.3 спецификации PM.
        """
        if gdf.empty:
            return []

        # 1. Первичная фильтрация и извлечение кандидатов (п. 3.2)
        candidates: List[Dict[str, Any]] = []

        for idx, row in gdf.iterrows():
            raw_name = row.get("name")
            if pd.isna(raw_name) or str(raw_name).strip().lower() in ("nan", "none", ""):
                name = ""
            else:
                name = str(raw_name).strip()
            name_lower = name.lower()

            # Исключаем паразитные нелогистические объекты (котельные, ТЭЦ, гаражи, свалки)
            if any(kw in name_lower for kw in self.EXCLUDE_KEYWORDS):
                continue

            # Фильтрация пассажирских депо
            depot_val = str(row.get("depot") or "").strip().lower()
            if depot_val in self.EXCLUDE_DEPOT_TYPES:
                continue

            # Фильтрация пассажирских ж/д станций (п. 3.2: railway=station не доказывает грузовую функцию)
            railway_val = str(row.get("railway") or "").strip().lower()
            if railway_val == "station":
                has_cargo = (
                    pd.notna(row.get("cargo"))
                    or (pd.notna(row.get("service")) and row.get("service") in ["spur", "siding"])
                    or any(kw in name_lower for kw in ["грузов", "товарн", "сортировочн", "cargo", "freight", "yard", "ramp"])
                )
                if not has_cargo:
                    continue

            # Проверка landuse=industrial (п. 3.1 & 3.2: сам по себе не подтверждает логистическую роль)
            is_generic_industrial = (
                row.get("landuse") == "industrial"
                and pd.isna(row.get("industrial"))
                and pd.isna(row.get("building"))
                and pd.isna(row.get("harbour"))
                and pd.isna(row.get("amenity"))
                and pd.isna(row.get("railway"))
                and pd.isna(row.get("port"))
            )
            matched_kw = next((kw for kw in self.LOGISTICS_KEYWORDS if kw in name_lower), None)

            # Если объект — общая безымянная промзона без признаков логистики, не делаем из нее узел
            if is_generic_industrial and not matched_kw:
                continue

            geom = row.geometry
            if geom.geom_type in ["Polygon", "MultiPolygon"]:
                point = geom.representative_point()
            else:
                point = geom.centroid

            # Определение типа объекта и основания классификации (п. 3.2)
            obj_type = "facility"
            primary_tag = None
            tag_strength = "contextual"

            # Приоритет тегов классификации
            if pd.notna(row.get("building")):
                b_val = str(row.get("building")).strip()
                obj_type = f"building_{b_val}" if b_val != "yes" else "warehouse"
                primary_tag = f"building={b_val}"
                if b_val == "warehouse":
                    tag_strength = "strong"
            elif pd.notna(row.get("industrial")):
                ind_val = str(row.get("industrial")).strip()
                obj_type = f"industrial_{ind_val}"
                primary_tag = f"industrial={ind_val}"
                if ind_val in ["warehouse", "logistics", "port"]:
                    tag_strength = "strong"
            elif pd.notna(row.get("harbour")) or pd.notna(row.get("port")):
                obj_type = "port"
                primary_tag = "harbour=yes" if pd.notna(row.get("harbour")) else f"port={row.get('port')}"
                tag_strength = "strong"
            elif pd.notna(row.get("railway")):
                rw_val = str(row.get("railway")).strip()
                obj_type = f"railway_{rw_val}"
                primary_tag = f"railway={rw_val}"
                tag_strength = "strong" if rw_val in ["yard", "loading_ramp"] else "contextual"
            elif pd.notna(row.get("amenity")):
                am_val = str(row.get("amenity")).strip()
                obj_type = am_val
                primary_tag = f"amenity={am_val}"
            elif pd.notna(row.get("landuse")):
                lu_val = str(row.get("landuse")).strip()
                obj_type = f"landuse_{lu_val}"
                primary_tag = f"landuse={lu_val}"

            osm_id_str = self._format_osm_id(row.name if hasattr(row, "name") else idx, row)

            is_building = pd.notna(row.get("building"))
            is_site = not is_building and geom.geom_type in ["Polygon", "MultiPolygon"]

            identification_basis = {
                "matched_tag": primary_tag,
                "tag_strength": tag_strength,
                "name_matched_keyword": matched_kw,
            }

            fallback_title = "Логистический комплекс" if is_site else "Складской объект"
            display_name = name if name else f"{fallback_title} #{len(candidates) + 1} ({obj_type})"

            candidates.append({
                "row_name": row.name if hasattr(row, "name") else idx,
                "osm_id_str": osm_id_str,
                "name": display_name,
                "object_type": obj_type,
                "latitude": round(float(point.y), 6),
                "longitude": round(float(point.x), 6),
                "geometry": geom,
                "is_building": is_building,
                "is_site": is_site,
                "identification_basis": identification_basis,
                "verification_status": (
                    VerificationStatus.VERIFIED.value 
                    if tag_strength == "strong" and matched_kw 
                    else VerificationStatus.CANDIDATE.value
                ),
            })

        if not candidates:
            return []

        # 2. Разделение здания и комплекса (п. 3.3: Spatial Join)
        # Проверяем вхождение зданий в полигоны площадок/территорий
        sites = [c for c in candidates if c["is_site"]]
        nodes: List[LogisticsNode] = []

        # Формируем итоговые объекты LogisticsNode
        for c in candidates:
            parent_site_id: Optional[str] = None
            graph_role = GraphRole.NODE_CANDIDATE.value

            if c["is_building"] and sites:
                # Проверяем, находится ли здание внутри какой-либо площадки
                b_geom = c["geometry"]
                b_pt = b_geom.representative_point() if b_geom.geom_type in ["Polygon", "MultiPolygon"] else b_geom
                for s in sites:
                    s_geom = s["geometry"]
                    if s_geom.contains(b_pt) or s_geom.intersects(b_geom):
                        parent_site_id = f"hub_site_{s['osm_id_str'].replace(':', '_').replace('/', '_')}"
                        graph_role = GraphRole.NESTED_CANDIDATE.value
                        c["identification_basis"]["spatial_relation"] = f"located_within:{parent_site_id}"
                        # Добавляем отметку в родительский сайт
                        nested_list = s["identification_basis"].setdefault("contains_buildings", [])
                        nested_list.append(c["osm_id_str"])
                        break

            node_id = (
                f"hub_site_{c['osm_id_str'].replace(':', '_').replace('/', '_')}"
                if c["is_site"]
                else f"hub_{len(nodes) + 1}_{c['object_type']}"
            )

            node = LogisticsNode(
                id=node_id,
                name=c["name"],
                object_type=c["object_type"],
                latitude=c["latitude"],
                longitude=c["longitude"],
                region_ids=[region_id],
                source_osm_ids=[c["osm_id_str"]],
                verification_status=c["verification_status"],
                transport_modes=[TransportMode.ROAD.value],
                identification_basis=c["identification_basis"],
                parent_site_id=parent_site_id,
                graph_role=graph_role,
            )
            nodes.append(node)

        # Сортировка: сначала самостоятельные вершины (территории и отдельные склады), затем вложенные
        nodes.sort(key=lambda n: 0 if n.graph_role == GraphRole.NODE_CANDIDATE.value else 1)
        selected_nodes = nodes[:limit]

        print(f"[+] Из OSM отфильтровано и отобрано {len(selected_nodes)} логистических объектов "
              f"({sum(1 for n in selected_nodes if n.graph_role == GraphRole.NODE_CANDIDATE.value)} самостоятельных, "
              f"{sum(1 for n in selected_nodes if n.graph_role == GraphRole.NESTED_CANDIDATE.value)} вложенных в комплексы).")
        return selected_nodes

    # =========================================================================
    # Правила отбора складов #64 (Sprint 4 Issue 2)
    # =========================================================================

    @staticmethod
    def _text(tags: Mapping[str, object], key: str) -> str:
        value = tags.get(key)
        return value.strip() if isinstance(value, str) else ""

    @classmethod
    def _normalized(cls, tags: Mapping[str, object], key: str) -> str:
        return " ".join(cls._text(tags, key).casefold().split())

    @classmethod
    def _classify(cls, tags: Mapping[str, object]) -> Tuple[str, str, str, List[str]]:
        matched = [
            f"{key}=warehouse"
            for key in cls.WAREHOUSE_TAGS
            if cls._normalized(tags, key) == "warehouse"
        ]
        if matched:
            use = cls._normalized(tags, "building:use")
            if use and use != "warehouse":
                return "review", "", "conflicting_building_use", matched + [f"building:use={use}"]
            if any(cls._normalized(tags, key) == "yes" for key in ("disused", "abandoned")):
                return "review", "", "inactive_object", matched
            kind = "building" if matched[0].startswith("building") else "site"
            return "eligible", kind, "warehouse_tag", matched

        if cls._normalized(tags, "industrial") == "logistics":
            return "review", "", "warehouse_use_to_check", ["industrial=logistics"]
        if cls._normalized(tags, "amenity") == "warehouse":
            return "review", "", "warehouse_use_to_check", ["amenity=warehouse"]
        name = cls._normalized(tags, "name")
        if any(word in name for word in cls.WAREHOUSE_WORDS):
            return "review", "", "warehouse_word_in_name", []
        return "excluded", "", "no_warehouse_evidence", []

    @staticmethod
    def _footprint(obj: WarehouseInput) -> Optional[float]:
        area = obj.polygon_area_m2
        return area if area is not None and isfinite(area) and area > 0 else None

    @classmethod
    def select_warehouses(
        cls,
        objects: Iterable[WarehouseInput],
        *,
        region_id: str = "custom",
        limit: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Отбор самостоятельных складов для дорожного графа согласно правилам #64.
        Возвращает:
          - аргументы для создания LogisticsNode (выбранные склады)
          - журнал аудита/решений по всем OSM ID.
        """
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, Integral) or limit < 1:
                raise ValueError("limit должен быть положительным целым числом или None")

        by_id: Dict[str, WarehouseInput] = {}
        for obj in objects:
            by_id.setdefault(obj.osm_id, obj)

        audit: Dict[str, Dict[str, Any]] = {}
        for osm_id, obj in by_id.items():
            decision, kind, reason, tags = cls._classify(obj.tags)
            if decision == "eligible":
                lat, lon = obj.latitude, obj.longitude
                if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    decision, reason = "review", "missing_or_invalid_geometry"
            audit[osm_id] = {
                "osm_id": osm_id,
                "name": cls._text(obj.tags, "name"),
                "operator": cls._text(obj.tags, "operator"),
                "kind": kind,
                "decision": decision,
                "reason": reason,
                "matched_tags": tags,
                "source_tags": {
                    key: value for key, value in obj.tags.items()
                    if isinstance(value, str) and value.strip()
                },
                "parent_osm_id": None,
                "warehouse_area_m2": cls._footprint(obj) if kind == "building" else None,
            }

        # Вложенность и подтверждение принадлежности проверяются до применения лимита.
        proposed_parents: Dict[str, str] = {}
        ambiguous_sites: Set[str] = set()
        for osm_id, obj in by_id.items():
            if audit[osm_id]["decision"] != "eligible" or audit[osm_id]["kind"] != "building":
                continue
            plausible_sites = []
            matching_sites = []
            child_operator = cls._normalized(obj.tags, "operator")
            child_name = cls._normalized(obj.tags, "name")

            for site_id in set(obj.enclosing_site_ids):
                site = audit.get(site_id)
                if not site or site["decision"] != "eligible" or site["kind"] != "site":
                    continue
                site_tags = by_id[site_id].tags
                site_operator = cls._normalized(site_tags, "operator")
                if child_operator and site_operator and child_operator != site_operator:
                    continue
                plausible_sites.append(site_id)
                same_operator = bool(child_operator and child_operator == site_operator)
                same_name = bool(child_name and child_name == cls._normalized(site_tags, "name"))
                if same_operator or same_name:
                    matching_sites.append(site_id)

            if len(plausible_sites) == 1 and matching_sites:
                proposed_parents[osm_id] = matching_sites[0]
            elif plausible_sites:
                ambiguous_sites.update(plausible_sites)

        for site_id in ambiguous_sites:
            audit[site_id].update(decision="review", reason="ambiguous_complex_membership")

        members: Dict[str, List[str]] = {}
        for building_id, site_id in proposed_parents.items():
            if site_id in ambiguous_sites:
                continue
            audit[building_id].update(
                decision="grouped", reason="same_complex", parent_osm_id=site_id,
            )
            members.setdefault(site_id, []).append(building_id)

        for site_id, child_ids in members.items():
            areas = [cls._footprint(by_id[child_id]) for child_id in child_ids]
            known_areas = [area for area in areas if area is not None]
            if known_areas:
                audit[site_id]["warehouse_area_m2"] = sum(known_areas)

        ready = sorted(osm_id for osm_id, row in audit.items() if row["decision"] == "eligible")
        if limit is not None and len(ready) > limit:
            def priority(osm_id: str):
                row = audit[osm_id]
                area = row["warehouse_area_m2"]
                info_count = bool(row["name"]) + bool(row["operator"])
                return area is None, -(area or 0), -info_count, osm_id

            ready.sort(key=priority)
            for osm_id in ready[limit:]:
                audit[osm_id].update(decision="over_limit", reason="selection_limit")
            ready = ready[:limit]

        selected: List[Dict[str, Any]] = []
        for osm_id in ready:
            obj, row = by_id[osm_id], audit[osm_id]
            row["decision"] = "selected"
            source_ids = [osm_id, *sorted(members.get(osm_id, []))]
            node_id = "warehouse_" + osm_id.replace(":", "_").replace("/", "_")
            label = "Складской комплекс" if row["kind"] == "site" else "Склад"
            selected.append({
                "id": node_id,
                "name": row["name"] or f"{label} ({osm_id})",
                "object_type": "warehouse",
                "latitude": round(float(obj.latitude), 6) if obj.latitude is not None else None,
                "longitude": round(float(obj.longitude), 6) if obj.longitude is not None else None,
                "region_ids": [region_id],
                "source_osm_ids": source_ids,
                "verification_status": VerificationStatus.CANDIDATE.value,
                "transport_modes": [TransportMode.ROAD.value],
                "graph_role": GraphRole.NODE_CANDIDATE.value,
                "identification_basis": {
                    "matched_tag": row["matched_tags"][0] if row["matched_tags"] else "warehouse",
                    "matched_tags": row["matched_tags"],
                    "tag_strength": "strong",
                    "warehouse_kind": row["kind"],
                    "warehouse_area_m2": row["warehouse_area_m2"],
                    "operator": row["operator"] or None,
                },
            })

        return selected, [audit[osm_id] for osm_id in sorted(audit)]

    @classmethod
    def select_warehouses_from_gdf(
        cls,
        features: Any,
        *,
        region_id: str = "custom",
        limit: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Преобразовать выгрузку OSMnx (GeoDataFrame) и применить правила отбора #64.
        """
        if features is None or getattr(features, "empty", True):
            return cls.select_warehouses([], region_id=region_id, limit=limit)

        import geopandas as gpd

        if getattr(features, "crs", None) is None:
            features = features.copy()
            features.set_crs("EPSG:4326", inplace=True)

        work = features.loc[~features.index.duplicated()].to_crs("EPSG:4326")
        if work.index.nlevels == 2:
            work.index = [f"osm:{element}/{osm_id}" for element, osm_id in work.index]
        else:
            work.index = [cls._format_osm_id(idx, row) for idx, row in work.iterrows()]

        geometry_column = work.geometry.name
        geometry = work.geometry
        valid = geometry.is_valid & ~geometry.is_empty
        polygons = valid & geometry.geom_type.isin(cls.POLYGON_TYPES)
        supported = polygons | (valid & geometry.geom_type.eq("Point"))

        tag_rows = work.reindex(columns=cls.TAGS_TO_KEEP).to_dict(orient="index")
        decisions = {osm_id: cls._classify(tags) for osm_id, tags in tag_rows.items()}
        buildings = [
            osm_id for osm_id, (decision, kind, _, _) in decisions.items()
            if decision == "eligible" and kind == "building" and supported.loc[osm_id]
        ]
        sites = [
            osm_id for osm_id, (decision, kind, _, _) in decisions.items()
            if decision == "eligible" and kind == "site" and polygons.loc[osm_id]
        ]
        footprints = geometry.loc[[osm_id for osm_id in buildings if polygons.loc[osm_id]]]
        areas = footprints.to_crs("EPSG:6933").area.to_dict() if len(footprints) else {}

        enclosing: Dict[str, Tuple[str, ...]] = {}
        if buildings and sites:
            site_shapes = work.loc[sites, [geometry_column]].assign(site_osm_id=sites)
            try:
                matches = gpd.sjoin(
                    work.loc[buildings, [geometry_column]],
                    site_shapes,
                    how="inner",
                    predicate="covered_by",
                )
                if not matches.empty:
                    enclosing = matches.groupby(level=0)["site_osm_id"].agg(tuple).to_dict()
            except Exception:
                enclosing = {}

        objects = []
        for osm_id, tags in tag_rows.items():
            point = geometry.loc[osm_id].representative_point() if supported.loc[osm_id] else None
            objects.append(WarehouseInput(
                osm_id=osm_id,
                tags=tags,
                latitude=float(point.y) if point is not None else None,
                longitude=float(point.x) if point is not None else None,
                polygon_area_m2=areas.get(osm_id),
                enclosing_site_ids=enclosing.get(osm_id, ()),
            ))

        return cls.select_warehouses(objects, region_id=region_id, limit=limit)

    def select_warehouse_nodes_from_gdf(
        self,
        features: Any,
        *,
        region_id: str = "custom",
        limit: Optional[int] = None,
    ) -> Tuple[List[LogisticsNode], List[Dict[str, Any]]]:
        """
        Преобразует выгрузку OSMnx в валидированные объекты LogisticsNode по правилам #64.
        Также сохраняет журнал аудита в self.last_audit_log.
        """
        selected_dicts, audit = self.select_warehouses_from_gdf(
            features=features,
            region_id=region_id,
            limit=limit,
        )
        nodes: List[LogisticsNode] = []
        for d in selected_dicts:
            nodes.append(LogisticsNode(**d))
        self.last_audit_log = audit
        return nodes, audit

    def fetch_from_osm_bbox(
        self,
        bbox: TerritoryBounds,
        tags: Optional[Dict[str, Any]] = None,
        limit: int = 15,
        region_id: str = "custom",
        use_rules_64: bool = True,
    ) -> List[LogisticsNode]:
        """
        Автоматически находит логистические/промышленные объекты в OSM внутри заданного BBox.
        """
        bbox.validate()
        query_tags = tags or (self.WAREHOUSE_OSM_TAGS if use_rules_64 else self.DEFAULT_OSM_TAGS)

        print(f"[*] Поиск логистических объектов в OSM для BBox: "
              f"lat=[{bbox.min_lat}, {bbox.max_lat}], lon=[{bbox.min_lon}, {bbox.max_lon}]...")
        try:
            gdf = execute_with_overpass_fallback(
                ox.features_from_bbox,
                bbox=bbox.to_osmnx_bbox(),
                tags=query_tags,
            )
        except Exception as e:
            print(f"[-] Ошибка при запросе к OSM Overpass API по BBox: {e}")
            return []

        if gdf is None or getattr(gdf, "empty", True):
            print("[-] Подходящих объектов в указанном BBox не найдено.")
            return []

        if use_rules_64:
            nodes, audit = self.select_warehouse_nodes_from_gdf(gdf, limit=limit, region_id=region_id)
            print(f"[+] Из OSM по правилам #64 отобрано {len(nodes)} складов (всего проверено объектов: {len(audit)}).")
            return nodes

        return self._extract_nodes_from_gdf(gdf=gdf, limit=limit, region_id=region_id)

    def fetch_from_osm(
        self, 
        place_name: str, 
        tags: Optional[Dict[str, Any]] = None,
        limit: int = 15,
        region_id: str = "ru-spb",
        which_result: Optional[int] = None,
        use_rules_64: bool = True,
    ) -> List[LogisticsNode]:
        """
        Автоматически находит логистические/промышленные объекты в OSM по названию территории с умной фильтрацией.
        """
        query_tags = tags or (self.WAREHOUSE_OSM_TAGS if use_rules_64 else self.DEFAULT_OSM_TAGS)

        print(f"[*] Поиск логистических объектов в OSM для: '{place_name}'...")
        try:
            kwargs = {"tags": query_tags}
            if which_result is not None:
                kwargs["which_result"] = which_result
            gdf = execute_with_overpass_fallback(
                ox.features_from_place,
                place_name,
                **kwargs,
            )
        except Exception as e:
            print(f"[-] Ошибка при запросе к OSM Overpass API: {e}")
            return []

        if gdf is None or getattr(gdf, "empty", True):
            print("[-] Подходящих объектов в указанной локации не найдено.")
            return []

        if use_rules_64:
            nodes, audit = self.select_warehouse_nodes_from_gdf(gdf, limit=limit, region_id=region_id)
            print(f"[+] Из OSM по правилам #64 отобрано {len(nodes)} складов (всего проверено объектов: {len(audit)}).")
            return nodes

        return self._extract_nodes_from_gdf(gdf=gdf, limit=limit, region_id=region_id)

    def _split_edge_for_virtual_node(
        self,
        road_graph: nx.MultiDiGraph,
        u: int,
        v: int,
        key: int,
        proj_pt: Point,
        cut_dist: float,
        virtual_node_id: int,
    ) -> bool:
        """
        Врезает виртуальную вершину virtual_node_id прямо в дорожный сегмент (u, v)
        в точке перпендикулярной проекции объекта proj_pt, разбивая ребро и сохраняя
        непрерывность и направленность движения.
        """
        if not road_graph.has_edge(u, v, key):
            return False

        fwd_data = dict(road_graph[u][v][key])
        orig_len = float(fwd_data.get("length", 100.0))
        geom = fwd_data.get("geometry")
        if geom is None or not isinstance(geom, LineString):
            geom = LineString([
                (road_graph.nodes[u]["x"], road_graph.nodes[u]["y"]),
                (road_graph.nodes[v]["x"], road_graph.nodes[v]["y"])
            ])

        total_geom_len = max(geom.length, 1e-9)
        ratio = max(0.01, min(0.99, cut_dist / total_geom_len))
        len_1 = max(1.0, round(orig_len * ratio, 1))
        len_2 = max(1.0, round(orig_len - len_1, 1))

        sub_geom1 = substring(geom, 0, cut_dist)
        sub_geom2 = substring(geom, cut_dist, geom.length)

        # 1. Добавляем виртуальную вершину прямо на полотно дороги
        road_graph.add_node(
            virtual_node_id,
            x=float(proj_pt.x),
            y=float(proj_pt.y),
            osmid=virtual_node_id,
            is_virtual=True,
        )

        # 2. Прямые ребра (u -> virt) и (virt -> v)
        data_u_virt = dict(fwd_data)
        data_u_virt["length"] = len_1
        data_u_virt["geometry"] = sub_geom1
        road_graph.add_edge(u, virtual_node_id, key=0, **data_u_virt)

        data_virt_v = dict(fwd_data)
        data_virt_v["length"] = len_2
        data_virt_v["geometry"] = sub_geom2
        road_graph.add_edge(virtual_node_id, v, key=0, **data_virt_v)

        road_graph.remove_edge(u, v, key=key)

        # 3. Обратные ребра (если улица двусторонняя, v -> u)
        if road_graph.has_edge(v, u):
            for rev_k in list(road_graph[v][u].keys()):
                rev_data = dict(road_graph[v][u][rev_k])
                rev_geom = rev_data.get("geometry")
                if rev_geom is not None and isinstance(rev_geom, LineString):
                    rev_cut = rev_geom.project(proj_pt)
                    rev_sub1 = substring(rev_geom, 0, rev_cut)
                    rev_sub2 = substring(rev_geom, rev_cut, rev_geom.length)
                else:
                    rev_sub1 = LineString([
                        (road_graph.nodes[v]["x"], road_graph.nodes[v]["y"]),
                        (proj_pt.x, proj_pt.y)
                    ])
                    rev_sub2 = LineString([
                        (proj_pt.x, proj_pt.y),
                        (road_graph.nodes[u]["x"], road_graph.nodes[u]["y"])
                    ])

                data_v_virt = dict(rev_data)
                data_v_virt["length"] = len_2
                data_v_virt["geometry"] = rev_sub1
                road_graph.add_edge(v, virtual_node_id, key=rev_k, **data_v_virt)

                data_virt_u = dict(rev_data)
                data_virt_u["length"] = len_1
                data_virt_u["geometry"] = rev_sub2
                road_graph.add_edge(virtual_node_id, u, key=rev_k, **data_virt_u)

                road_graph.remove_edge(v, u, key=rev_k)

        return True

    def snap_to_road_network(
        self, 
        road_graph: nx.MultiDiGraph, 
        nodes: List[Any],
        filter_disconnected: bool = True,
        max_snap_distance_m: Optional[float] = None,
    ) -> List[LogisticsNode]:
        """
        Умная пространственная привязка (Smart Snapping) объектов к дорожной сети OSM:
        1. Выделяет основную связную компоненту дорог (Largest Connected Component),
           исключая изолированные тупики и оторванные от мира островки дорог.
        2. Анализирует ближайшие дорожные рёбра и перекрёстки (nearest_edges + nearest_nodes).
        3. Проверяет направленность движения (in_degree и out_degree) для исключения
           односторонних тупиков-ловушек (sinks/sources).
        4. Формирует устойчивый пул точек подключения (access_nodes) с разделением
           на въездные и выездные точки.
        """
        if not nodes:
            return []
        if len(road_graph.nodes) == 0:
            raise ValueError("Дорожный граф пуст, невозможно выполнить привязку объектов.")

        if "crs" not in road_graph.graph:
            road_graph.graph["crs"] = "epsg:4326"

        log_nodes: List[LogisticsNode] = []
        for n in nodes:
            if isinstance(n, LogisticsNode):
                log_nodes.append(n)
            elif isinstance(n, dict):
                log_nodes.append(
                    LogisticsNode(
                        id=str(n["id"]),
                        name=str(n["name"]),
                        object_type=str(n.get("type") or n.get("object_type", "facility")),
                        latitude=float(n.get("lat") or n.get("latitude")),
                        longitude=float(n.get("lon") or n.get("longitude")),
                        region_ids=n.get("region_ids", ["ru-spb"]),
                        source_osm_ids=n.get("source_osm_ids", []),
                        verification_status=n.get("verification_status", VerificationStatus.CANDIDATE.value),
                        transport_modes=n.get("transport_modes", [TransportMode.ROAD.value]),
                        identification_basis=n.get("identification_basis", {}),
                        parent_site_id=n.get("parent_site_id"),
                        graph_role=n.get("graph_role", GraphRole.NODE_CANDIDATE.value),
                    )
                )

        # 0. Валидация координат складов
        valid_nodes: List[LogisticsNode] = []
        invalid_nodes: List[LogisticsNode] = []
        for n in log_nodes:
            if (
                n.latitude is None
                or n.longitude is None
                or not isfinite(n.latitude)
                or not isfinite(n.longitude)
                or not (-90.0 <= n.latitude <= 90.0)
                or not (-180.0 <= n.longitude <= 180.0)
            ):
                n.nearest_osm_node = None
                n.osm_node_lat = None
                n.osm_node_lon = None
                n.snap_distance_m = None
                n.snap_kind = "unconnected"
                n.access_nodes = []
                n.is_isolated = True
                n.isolation_reason = "Отсутствуют или некорректны координаты склада"
                n.identification_basis["connection_status"] = "isolated"
                n.identification_basis["isolation_reason"] = n.isolation_reason
                n.identification_basis["snap_kind"] = "unconnected"
                invalid_nodes.append(n)
            else:
                valid_nodes.append(n)

        if not valid_nodes:
            return invalid_nodes

        # 1. Определение основной связной компоненты (Largest Connected Component)
        # Исключаем изолированные островки, где проезд отрезан от остальной сети
        if filter_disconnected and len(road_graph.nodes) > 1:
            try:
                weak_components = list(nx.weakly_connected_components(road_graph))
                largest_cc = max(weak_components, key=len)
                if len(largest_cc) >= 2:
                    active_graph = road_graph.subgraph(largest_cc)
                else:
                    active_graph = road_graph
            except Exception:
                active_graph = road_graph
        else:
            active_graph = road_graph

        lons = [n.longitude for n in valid_nodes]
        lats = [n.latitude for n in valid_nodes]

        # 2. Поиск ближайших вершин в связной компоненте
        primary_node_ids = ox.nearest_nodes(active_graph, X=lons, Y=lats)
        if not isinstance(primary_node_ids, (list, tuple)) and not hasattr(primary_node_ids, "__iter__"):
            primary_node_ids = [primary_node_ids]

        # 3. Поиск ближайших рёбер в связной компоненте (если есть рёбра)
        nearest_edge_tuples = []
        if len(active_graph.edges) > 0:
            try:
                edge_res = ox.nearest_edges(active_graph, X=lons, Y=lats)
                if hasattr(edge_res, "tolist"):
                    edge_list = edge_res.tolist()
                elif isinstance(edge_res, (list, tuple)):
                    edge_list = list(edge_res)
                else:
                    edge_list = [edge_res]

                if len(valid_nodes) == 1 and len(edge_list) > 0 and not isinstance(edge_list[0], (list, tuple)):
                    nearest_edge_tuples = [tuple(edge_list)]
                else:
                    nearest_edge_tuples = [tuple(e) if isinstance(e, (list, tuple)) else e for e in edge_list]
            except Exception:
                nearest_edge_tuples = [None] * len(valid_nodes)
        else:
            nearest_edge_tuples = [None] * len(valid_nodes)

        snapped_nodes: List[LogisticsNode] = list(invalid_nodes)

        for idx, (node, primary_id) in enumerate(zip(valid_nodes, primary_node_ids)):
            primary_id_native = int(primary_id)
            split_succeeded = False
            snap_kind = "osm_node"
            best_node_id = primary_id_native
            best_lat = float(road_graph.nodes[primary_id_native]["y"])
            best_lon = float(road_graph.nodes[primary_id_native]["x"])
            best_dist = ox.distance.great_circle(node.latitude, node.longitude, best_lat, best_lon)
            access_pool: List[int] = [primary_id_native]

            # 1. Попытка перпендикулярной врезки к ближайшему дорожному сегменту (Edge Splitting)
            if idx < len(nearest_edge_tuples) and nearest_edge_tuples[idx] is not None:
                e_data = nearest_edge_tuples[idx]
                if isinstance(e_data, tuple) and len(e_data) >= 2:
                    u_cand, v_cand = int(e_data[0]), int(e_data[1])
                    e_key = int(e_data[2]) if len(e_data) > 2 else 0

                    if road_graph.has_edge(u_cand, v_cand, e_key):
                        e_attrs = road_graph[u_cand][v_cand][e_key]
                        geom = e_attrs.get("geometry")
                        if geom is None or not isinstance(geom, LineString):
                            geom = LineString([
                                (road_graph.nodes[u_cand]["x"], road_graph.nodes[u_cand]["y"]),
                                (road_graph.nodes[v_cand]["x"], road_graph.nodes[v_cand]["y"])
                            ])

                        fac_pt = Point(node.longitude, node.latitude)
                        cut_dist = geom.project(fac_pt)
                        proj_pt = geom.interpolate(cut_dist)
                        proj_lon, proj_lat = float(proj_pt.x), float(proj_pt.y)

                        proj_dist_m = ox.distance.great_circle(node.latitude, node.longitude, proj_lat, proj_lon)
                        dist_to_u = ox.distance.great_circle(proj_lat, proj_lon, road_graph.nodes[u_cand]["y"], road_graph.nodes[u_cand]["x"])
                        dist_to_v = ox.distance.great_circle(proj_lat, proj_lon, road_graph.nodes[v_cand]["y"], road_graph.nodes[v_cand]["x"])

                        # Проверяем, что улица сквозная (не ведет в односторонний тупик без выезда)
                        is_bidirectional = road_graph.has_edge(v_cand, u_cand)
                        has_exit = is_bidirectional or (road_graph.out_degree(v_cand) > 0)

                        if has_exit:
                            if dist_to_u < 8.0:
                                # Проекция находится в пределах 8 метров от перекрёстка u
                                best_node_id = u_cand
                                best_lat = float(road_graph.nodes[u_cand]["y"])
                                best_lon = float(road_graph.nodes[u_cand]["x"])
                                best_dist = ox.distance.great_circle(node.latitude, node.longitude, best_lat, best_lon)
                                access_pool = [u_cand]
                                if v_cand in road_graph and v_cand != u_cand:
                                    access_pool.append(v_cand)
                                split_succeeded = True
                                snap_kind = "osm_node"
                            elif dist_to_v < 8.0:
                                # Проекция находится в пределах 8 метров от перекрёстка v
                                best_node_id = v_cand
                                best_lat = float(road_graph.nodes[v_cand]["y"])
                                best_lon = float(road_graph.nodes[v_cand]["x"])
                                best_dist = ox.distance.great_circle(node.latitude, node.longitude, best_lat, best_lon)
                                access_pool = [v_cand]
                                if u_cand in road_graph and u_cand != v_cand:
                                    access_pool.append(u_cand)
                                split_succeeded = True
                                snap_kind = "osm_node"
                            else:
                                virtual_id = 9_000_000_000 + (idx + 1)
                                while virtual_id in road_graph:
                                    virtual_id += 1
                                if self._split_edge_for_virtual_node(road_graph, u_cand, v_cand, e_key, proj_pt, cut_dist, virtual_id):
                                    best_node_id = virtual_id
                                    best_lat = proj_lat
                                    best_lon = proj_lon
                                    best_dist = proj_dist_m
                                    access_pool = [virtual_id]
                                    if u_cand in road_graph and u_cand != virtual_id:
                                        access_pool.append(u_cand)
                                    if v_cand in road_graph and v_cand != virtual_id:
                                        access_pool.append(v_cand)
                                    split_succeeded = True
                                    snap_kind = "virtual_node"

            # 2. Если врезка не удалась — резервный выбор из перекрёстков-кандидатов с защитой от тупиков
            if not split_succeeded:
                candidate_pool = {primary_id_native}
                if idx < len(nearest_edge_tuples) and nearest_edge_tuples[idx] is not None:
                    e_data = nearest_edge_tuples[idx]
                    if isinstance(e_data, tuple) and len(e_data) >= 2:
                        u_cand, v_cand = int(e_data[0]), int(e_data[1])
                        if u_cand in road_graph:
                            candidate_pool.add(u_cand)
                        if v_cand in road_graph:
                            candidate_pool.add(v_cand)

                nodes_to_expand = list(candidate_pool)
                for cid in nodes_to_expand:
                    if cid in road_graph:
                        for neighbor in road_graph.successors(cid):
                            candidate_pool.add(int(neighbor))
                        for predecessor in road_graph.predecessors(cid):
                            candidate_pool.add(int(predecessor))

                candidate_details = []
                for cand_id in candidate_pool:
                    if cand_id in road_graph.nodes:
                        cand_data = road_graph.nodes[cand_id]
                        c_lat = float(cand_data.get("y"))
                        c_lon = float(cand_data.get("x"))
                        d = ox.distance.great_circle(node.latitude, node.longitude, c_lat, c_lon)

                        in_deg = road_graph.in_degree(cand_id)
                        out_deg = road_graph.out_degree(cand_id)

                        is_transit = (in_deg > 0 and out_deg > 0)
                        penalty = 0.0 if is_transit else 100.0
                        score = d + penalty

                        candidate_details.append({
                            "id": cand_id,
                            "dist": d,
                            "score": score,
                            "lat": c_lat,
                            "lon": c_lon,
                            "in_deg": in_deg,
                            "out_deg": out_deg,
                            "is_transit": is_transit,
                        })

                candidate_details.sort(key=lambda x: (x["score"], x["dist"]))

                best_cand = candidate_details[0]
                best_node_id = best_cand["id"]
                best_dist = best_cand["dist"]
                best_lat = best_cand["lat"]
                best_lon = best_cand["lon"]

                access_pool = [best_node_id]
                remaining = sorted(
                    [c for c in candidate_details if c["id"] != best_node_id],
                    key=lambda x: (not x["is_transit"], x["dist"])
                )
                for c in remaining:
                    if max_snap_distance_m is not None and c["dist"] > max_snap_distance_m:
                        continue
                    if len(access_pool) >= 5:
                        break
                    access_pool.append(c["id"])

            if max_snap_distance_m is not None and best_dist > max_snap_distance_m:
                node.nearest_osm_node = None
                node.osm_node_lat = None
                node.osm_node_lon = None
                node.snap_distance_m = round(float(best_dist), 1)
                node.snap_kind = "unconnected"
                node.access_nodes = []
                node.is_isolated = True
                node.isolation_reason = (
                    f"Превышен лимит расстояния до автодороги: {round(float(best_dist), 1)} м > {max_snap_distance_m:.1f} м "
                    f"(объект в акватории или нет подъездных путей)"
                )
                node.identification_basis["connection_status"] = "isolated"
                node.identification_basis["isolation_reason"] = node.isolation_reason
                node.identification_basis["snap_kind"] = "unconnected"
                node.identification_basis["snap_distance_m"] = node.snap_distance_m
                snapped_nodes.append(node)
                print(f"  [SmartSnap] '{node.name}' -> [!] ИЗОЛИРОВАН: расстояние до дорожной сети {node.snap_distance_m} м > {max_snap_distance_m:.1f} м (морская акватория / нет автодорог)")
                continue

            node.nearest_osm_node = best_node_id
            node.osm_node_lat = best_lat
            node.osm_node_lon = best_lon
            node.snap_distance_m = round(float(best_dist), 1)
            node.snap_kind = snap_kind
            node.access_nodes = access_pool
            node.is_isolated = False
            node.isolation_reason = None
            node.identification_basis["connection_status"] = "connected"
            node.identification_basis["snap_kind"] = snap_kind
            node.identification_basis["snap_distance_m"] = node.snap_distance_m
            node.identification_basis["options_count"] = len(node.access_nodes)
            snapped_nodes.append(node)

            warning_tag = " [!] ДАЛЕКО" if best_dist > 300 else ""
            is_virt = bool(road_graph.nodes.get(best_node_id, {}).get("is_virtual", False))
            tag = " (виртуальный узел на ребре)" if is_virt else " (перекресток)"
            print(f"  [SmartSnap] '{node.name}' -> {len(node.access_nodes)} точек подключения "
                  f"(осн. узел {best_node_id}{tag}, плечо: {node.snap_distance_m} м){warning_tag}")

        return snapped_nodes

    @staticmethod
    def get_snap_report(warehouses: List[LogisticsNode]) -> List[Dict[str, Any]]:
        """
        Формирует подробный отчет по привязке складов к дорожной сети (#64):
        ID склада, координаты, дорожная точка, расстояние, варианты и причина отсутствия привязки.
        """
        report: List[Dict[str, Any]] = []
        for w in warehouses:
            has_snap = bool(w.nearest_osm_node is not None and not w.is_isolated)
            kind = getattr(w, "snap_kind", None) or ("osm_node" if has_snap else "unconnected")
            report.append({
                "warehouse_id": w.id,
                "name": w.name,
                "latitude": w.latitude,
                "longitude": w.longitude,
                "nearest_osm_node": w.nearest_osm_node,
                "osm_node_lat": w.osm_node_lat,
                "osm_node_lon": w.osm_node_lon,
                "snap_distance_m": w.snap_distance_m,
                "snap_kind": kind,
                "access_nodes": list(w.access_nodes),
                "options_count": len(w.access_nodes),
                "is_isolated": w.is_isolated,
                "isolation_reason": w.isolation_reason or ("" if has_snap else "Точка не найдена"),
            })
        return report

    @staticmethod
    def get_snap_summary(warehouses: List[LogisticsNode]) -> Dict[str, Any]:
        """
        Формирует агрегированную статистику по привязке складов (#64).
        """
        total = len(warehouses)
        connected = [w for w in warehouses if not w.is_isolated and w.nearest_osm_node is not None]
        isolated = [w for w in warehouses if w.is_isolated or w.nearest_osm_node is None]

        from collections import Counter
        primary_counts = Counter(w.nearest_osm_node for w in connected if w.nearest_osm_node is not None)
        shared_directions = sum(count * (count - 1) for count in primary_counts.values())

        distances = [w.snap_distance_m for w in connected if w.snap_distance_m is not None]
        avg_dist = round(sum(distances) / len(distances), 1) if distances else 0.0
        max_dist = round(max(distances), 1) if distances else 0.0

        kinds = Counter(getattr(w, "snap_kind", "unknown") for w in warehouses)

        return {
            "total_warehouses": total,
            "connected_count": len(connected),
            "isolated_count": len(isolated),
            "unique_primary_nodes": len(primary_counts),
            "shared_primary_node_directions": shared_directions,
            "avg_snap_distance_m": avg_dist,
            "max_snap_distance_m": max_dist,
            "snap_kinds": dict(kinds),
        }

