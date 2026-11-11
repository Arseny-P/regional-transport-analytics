from typing import Dict, Any, List, Optional, Union
import networkx as nx
from shapely import wkt
from shapely.geometry.base import BaseGeometry
from shapely.geometry import LineString, MultiLineString

from graph_service.kafka.schemas import GraphPayload, NodePayload, EdgePayload


class GraphSerializer:
    """
    Преобразует внутренний граф (дорожный граф маршрутов MultiDiGraph или логистический MultiGraph)
    в DTO GraphPayload в строгом соответствии с контрактом Kafka и Go-оркестратора.
    """

    @classmethod
    def serialize(cls, log_graph: Union[nx.MultiGraph, nx.MultiDiGraph, nx.Graph]) -> GraphPayload:
        """
        Преобразует граф сети в GraphPayload:
        - Координаты вершин position: строго [lon, lat] с округлением до 6 знаков.
        - Атрибуты вершин: object_type ("warehouse", "intersection", "road_node"), name, etc.
        - Геометрия рёбер: [[lon, lat], ...] вдоль фактической геометрии дорожных сегментов/коннекторов.
        - Атрибуты рёбер: edge_type ("road" / "access_connector"), length_m, routes_count, etc.
        """
        nodes: List[NodePayload] = []
        edges: List[EdgePayload] = []

        # 1. Сериализация вершин
        for node_id, data in log_graph.nodes(data=True):
            lon = data.get("x") or data.get("lon") or data.get("longitude")
            lat = data.get("y") or data.get("lat") or data.get("latitude")

            if lon is None or lat is None:
                continue

            node_attrs: Dict[str, Any] = {
                "name": str(data.get("name", str(node_id))),
                "object_type": str(data.get("object_type", "road_node")),
            }

            for extra_key in (
                "is_isolated",
                "isolation_reason",
                "snap_kind",
                "snap_distance_m",
                "nearest_osm_node",
                "street_count",
                "highway",
                "original_lat",
                "original_lon",
                "snapped_road_node",
            ):
                if extra_key in data and data[extra_key] is not None:
                    node_attrs[extra_key] = data[extra_key]

            nodes.append(
                NodePayload(
                    id=str(node_id),
                    position=[round(float(lon), 6), round(float(lat), 6)],
                    attributes=node_attrs,
                )
            )

        # 2. Сериализация рёбер
        edge_idx = 0
        for u, v, k, data in log_graph.edges(keys=True, data=True):
            edge_idx += 1
            edge_id = str(data.get("id") or f"e_{u}_{v}_{k}_{edge_idx}")

            # Извлечение геометрии
            geom_coords: Optional[List[List[float]]] = None

            raw_geom = data.get("geometry")
            if raw_geom is not None and isinstance(raw_geom, (LineString, MultiLineString)):
                if isinstance(raw_geom, LineString):
                    geom_coords = [[round(pt[0], 6), round(pt[1], 6)] for pt in raw_geom.coords]
                elif isinstance(raw_geom, MultiLineString):
                    geom_coords = []
                    for line in raw_geom.geoms:
                        geom_coords.extend([[round(pt[0], 6), round(pt[1], 6)] for pt in line.coords])
            else:
                wkt_str = (
                    data.get("geometry_wkt")
                    or data.get("road_geometry_ab_wkt")
                    or data.get("geometry_ab_wkt")
                    or data.get("road_geom_wkt")
                )
                if wkt_str:
                    geom_coords = cls._parse_wkt_to_coords(wkt_str)

            # Если геометрии нет или менее 2 точек, используем отрезок между координатами узлов
            if not geom_coords or len(geom_coords) < 2:
                node_u_data = log_graph.nodes.get(u, {})
                node_v_data = log_graph.nodes.get(v, {})
                u_lon = node_u_data.get("x") or node_u_data.get("lon") or node_u_data.get("longitude")
                u_lat = node_u_data.get("y") or node_u_data.get("lat") or node_u_data.get("latitude")
                v_lon = node_v_data.get("x") or node_v_data.get("lon") or node_v_data.get("longitude")
                v_lat = node_v_data.get("y") or node_v_data.get("lat") or node_v_data.get("latitude")
                if u_lon is not None and u_lat is not None and v_lon is not None and v_lat is not None:
                    geom_coords = [
                        [round(float(u_lon), 6), round(float(u_lat), 6)],
                        [round(float(v_lon), 6), round(float(v_lat), 6)],
                    ]

            # Формирование атрибутов ребра
            edge_attrs: Dict[str, Any] = {
                "transport_mode": data.get("transport_mode", "road"),
            }

            if "edge_type" in data:
                edge_attrs["edge_type"] = data["edge_type"]
                if "length_m" in data and data["length_m"] is not None:
                    try:
                        edge_attrs["length_m"] = round(float(data["length_m"]), 2)
                    except (ValueError, TypeError):
                        pass
                if "routes_count" in data and data["routes_count"] is not None:
                    try:
                        edge_attrs["routes_count"] = int(data["routes_count"])
                    except (ValueError, TypeError):
                        pass
                for opt_key in ("highway", "name", "oneway", "maxspeed", "warehouse_id", "road_node_id", "direction"):
                    if opt_key in data and data[opt_key] is not None and data[opt_key] != "":
                        edge_attrs[opt_key] = data[opt_key]
                if "route_ids" in data and data["route_ids"]:
                    edge_attrs["route_ids"] = list(data["route_ids"])
            else:
                # Обратная совместимость с логистическим графом склад-склад
                for st_key in ("route_status_ab", "route_status_ba"):
                    if st_key in data and data[st_key]:
                        edge_attrs[st_key] = data[st_key]
                for num_attr in ("total_distance_ab_m", "total_distance_ba_m", "distance_ab_m", "distance_ba_m"):
                    val = data.get(num_attr)
                    if val is not None:
                        try:
                            edge_attrs[num_attr] = round(float(val), 2)
                        except (ValueError, TypeError):
                            pass
                for str_attr in ("node_a_name", "node_b_name"):
                    if str_attr in data and data[str_attr]:
                        edge_attrs[str_attr] = data[str_attr]

            edges.append(
                EdgePayload(
                    id=edge_id,
                    source=str(u),
                    target=str(v),
                    geometry=geom_coords,
                    attributes=edge_attrs,
                )
            )

        return GraphPayload(nodes=nodes, edges=edges)

    @staticmethod
    def _parse_wkt_to_coords(wkt_str: str) -> Optional[List[List[float]]]:
        """
        Преобразует WKT строку геометрии в список координат [[lon, lat], ...].
        """
        try:
            geom: BaseGeometry = wkt.loads(wkt_str)
            coords: List[List[float]] = []
            if geom.geom_type == "LineString":
                coords = [[round(pt[0], 6), round(pt[1], 6)] for pt in geom.coords]
            elif geom.geom_type == "MultiLineString":
                for line in geom.geoms:
                    coords.extend([[round(pt[0], 6), round(pt[1], 6)] for pt in line.coords])
            return coords if len(coords) >= 2 else None
        except Exception:
            return None

