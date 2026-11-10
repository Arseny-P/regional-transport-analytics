from typing import Dict, Any, List, Optional
import networkx as nx
from shapely import wkt
from shapely.geometry.base import BaseGeometry

from graph_service.kafka.schemas import GraphPayload, NodePayload, EdgePayload


class GraphSerializer:
    """
    Преобразует внутренний MultiGraph логистической сети в DTO GraphPayload
    в строгом соответствии с контрактом Kafka (п. 7).
    """

    @classmethod
    def serialize(cls, log_graph: nx.MultiGraph) -> GraphPayload:
        """
        Преобразует nx.MultiGraph в GraphPayload.
        """
        nodes: List[NodePayload] = []
        edges: List[EdgePayload] = []

        # 1. Сериализация вершин
        for node_id, data in log_graph.nodes(data=True):
            lon = data.get("x") or data.get("lon") or data.get("longitude")
            lat = data.get("y") or data.get("lat") or data.get("latitude")

            if lon is None or lat is None:
                continue

            node_attrs = {
                "name": data.get("name", str(node_id)),
                "object_type": data.get("object_type", "logistics_hub"),
            }
            for extra_key in ("original_lat", "original_lon", "snap_distance_m", "snapped_road_node"):
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
            edge_id = f"e_{u}_{v}_{k}_{edge_idx}"

            # Извлечение геометрии из WKT (приоритет: road_geometry_ab_wkt -> geometry_ab_wkt)
            geom_coords: Optional[List[List[float]]] = None
            wkt_str = (
                data.get("road_geometry_ab_wkt")
                or data.get("geometry_ab_wkt")
                or data.get("road_geom_wkt")
            )

            if wkt_str:
                geom_coords = cls._parse_wkt_to_coords(wkt_str)

            # Если геометрии пути нет, используем прямую линию между позициями узлов (минимум 2 точки по контракту)
            if not geom_coords or len(geom_coords) < 2:
                node_u_data = log_graph.nodes.get(u, {})
                node_v_data = log_graph.nodes.get(v, {})
                u_lon = node_u_data.get("x") or node_u_data.get("lon")
                u_lat = node_u_data.get("y") or node_u_data.get("lat")
                v_lon = node_v_data.get("x") or node_v_data.get("lon")
                v_lat = node_v_data.get("y") or node_v_data.get("lat")
                if u_lon is not None and u_lat is not None and v_lon is not None and v_lat is not None:
                    geom_coords = [
                        [round(float(u_lon), 6), round(float(u_lat), 6)],
                        [round(float(v_lon), 6), round(float(v_lat), 6)],
                    ]

            edge_attrs: Dict[str, Any] = {
                "transport_mode": data.get("transport_mode", "road"),
                "route_status_ab": data.get("route_status_ab"),
                "route_status_ba": data.get("route_status_ba"),
            }

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

