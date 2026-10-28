import os
import json
from typing import List, Dict, Any, Union, Optional, Tuple
import networkx as nx
from shapely.geometry import Point, LineString, MultiLineString, mapping
from shapely.ops import linemerge
from shapely import wkt

from graph_service.domain.models import LogisticsNode, LogisticsEdge, TransportMode, RouteStatus, GraphRole


class LogisticsGraphService:
    """
    Сервис маршрутизации, синтеза логистического MultiGraph и его экспорта (GraphML / GeoJSON).
    """

    def __init__(self, storage_dir: str = "data"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)

    def _extract_route_geometry(self, road_graph: nx.MultiDiGraph, path: List[int]) -> LineString:
        """
        Склеивает последовательные сегменты ребер пути в единую непрерывную геометрию LineString.
        """
        lines = []
        for u, v in zip(path[:-1], path[1:]):
            edge_data = road_graph[u][v][0]
            if "geometry" in edge_data:
                lines.append(edge_data["geometry"])
            else:
                p1 = (float(road_graph.nodes[u]["x"]), float(road_graph.nodes[u]["y"]))
                p2 = (float(road_graph.nodes[v]["x"]), float(road_graph.nodes[v]["y"]))
                lines.append(LineString([p1, p2]))

        merged = linemerge(lines)
        if isinstance(merged, MultiLineString):
            coords = []
            for ls in merged.geoms:
                coords.extend(ls.coords)
            return LineString(coords)
        return merged

    def _calculate_best_route(
        self, 
        road_graph: nx.MultiDiGraph, 
        start_nodes: List[int], 
        end_nodes: List[int],
        origin_coords: Optional[Tuple[float, float]] = None,
        dest_coords: Optional[Tuple[float, float]] = None
    ) -> Dict[str, Any]:
        """
        Находит наилучший (кратчайший) маршрут среди пула кандидатов точек подключения.
        Реализует исследовательский алгоритм find_best_route из ноутбука PM (п. 7.11).
        Дополнительно выполняет сквозное дотягивание маршрута до центроидов объектов (Last-Mile Access).
        """
        best_distance = float("inf")
        best_u = None
        best_v = None

        for u in start_nodes:
            for v in end_nodes:
                if u == v:
                    continue
                try:
                    d = nx.shortest_path_length(road_graph, source=u, target=v, weight="length")
                    if d < best_distance:
                        best_distance = d
                        best_u = u
                        best_v = v
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    continue

        if best_u is None or best_v is None or best_distance == float("inf"):
            return {
                "status": RouteStatus.NOT_FOUND_IN_DATA.value,
                "distance_m": None,
                "total_distance_m": None,
                "snap_origin_m": None,
                "snap_dest_m": None,
                "nodes_count": 0,
                "path": [],
                "geom_wkt": None,
                "road_geom_wkt": None,
                "access_u": None,
                "access_v": None,
                "origin_conn_wkt": None,
                "dest_conn_wkt": None,
            }

        path_nodes = [int(n) for n in nx.shortest_path(road_graph, source=best_u, target=best_v, weight="length")]
        route_geom = self._extract_route_geometry(road_graph, path_nodes)

        import osmnx as ox
        u_lon = float(road_graph.nodes[best_u]["x"])
        u_lat = float(road_graph.nodes[best_u]["y"])
        v_lon = float(road_graph.nodes[best_v]["x"])
        v_lat = float(road_graph.nodes[best_v]["y"])

        snap_origin_m = 0.0
        snap_dest_m = 0.0
        door_to_door_coords = []
        origin_conn_wkt = None
        dest_conn_wkt = None

        if origin_coords:
            snap_origin_m = ox.distance.great_circle(origin_coords[1], origin_coords[0], u_lat, u_lon)
            door_to_door_coords.append(origin_coords)
            origin_conn_wkt = LineString([origin_coords, (u_lon, u_lat)]).wkt

        door_to_door_coords.extend(list(route_geom.coords))

        if dest_coords:
            snap_dest_m = ox.distance.great_circle(v_lat, v_lon, dest_coords[1], dest_coords[0])
            door_to_door_coords.append(dest_coords)
            dest_conn_wkt = LineString([(v_lon, v_lat), dest_coords]).wkt

        door_to_door_geom = LineString(door_to_door_coords)
        total_distance = round(float(best_distance) + snap_origin_m + snap_dest_m, 1)

        return {
            "status": RouteStatus.FOUND.value,
            "distance_m": round(float(best_distance), 1),
            "total_distance_m": total_distance,
            "snap_origin_m": round(float(snap_origin_m), 1),
            "snap_dest_m": round(float(snap_dest_m), 1),
            "nodes_count": len(path_nodes),
            "path": path_nodes,
            "geom_wkt": door_to_door_geom.wkt,
            "road_geom_wkt": route_geom.wkt,
            "access_u": best_u,
            "access_v": best_v,
            "origin_conn_wkt": origin_conn_wkt,
            "dest_conn_wkt": dest_conn_wkt,
        }

    def build_logistics_graph(
        self, 
        road_graph: nx.MultiDiGraph, 
        snapped_nodes: List[Union[LogisticsNode, Dict[str, Any]]],
        k_neighbors: Optional[int] = None
    ) -> nx.MultiGraph:
        """
        Формирует логистический NetworkX MultiGraph:
        - Вершины: логистические объекты со свойствами и access_nodes.
        - Рёбра: по 1 ребру на вид транспорта (road) между парами объектов
          с раздельными характеристиками направлений A -> B и B -> A.
        - При указании k_neighbors: формирует разреженный граф k ближайших соседей (п. 9.2).
        """
        log_graph = nx.MultiGraph()

        nodes: List[LogisticsNode] = []
        for n in snapped_nodes:
            if isinstance(n, LogisticsNode):
                nodes.append(n)
            else:
                nodes.append(
                    LogisticsNode(
                        id=str(n["id"]),
                        name=str(n["name"]),
                        object_type=str(n.get("object_type") or n.get("type", "facility")),
                        latitude=float(n.get("latitude") or n.get("lat")),
                        longitude=float(n.get("longitude") or n.get("lon")),
                        region_ids=n.get("region_ids", ["ru-spb"]),
                        source_osm_ids=n.get("source_osm_ids", []),
                        verification_status=n.get("verification_status", "candidate"),
                        transport_modes=n.get("transport_modes", [TransportMode.ROAD.value]),
                        identification_basis=n.get("identification_basis", {}),
                        parent_site_id=n.get("parent_site_id"),
                        graph_role=n.get("graph_role", GraphRole.NODE_CANDIDATE.value),
                        nearest_osm_node=n.get("nearest_osm_node"),
                        osm_node_lat=n.get("osm_node_lat"),
                        osm_node_lon=n.get("osm_node_lon"),
                        snap_distance_m=n.get("snap_distance_m"),
                        access_nodes=n.get("access_nodes", [n.get("nearest_osm_node")] if n.get("nearest_osm_node") else [])
                    )
                )

        for node in nodes:
            log_graph.add_node(
                node.id,
                name=node.name,
                object_type=node.object_type,
                latitude=node.latitude,
                longitude=node.longitude,
                region_ids=",".join(node.region_ids),
                verification_status=node.verification_status,
                transport_modes=",".join(node.transport_modes),
                parent_site_id=node.parent_site_id or "",
                graph_role=node.graph_role,
                identification_basis=json.dumps(node.identification_basis, ensure_ascii=False),
                nearest_osm_node=node.nearest_osm_node or 0,
                osm_node_lat=node.osm_node_lat or 0.0,
                osm_node_lon=node.osm_node_lon or 0.0,
                snap_distance_m=node.snap_distance_m or 0.0,
                access_nodes=json.dumps(node.access_nodes)
            )

        # Формируем список пар для проверки маршрутов
        pairs_to_check = set()
        if k_neighbors is not None and k_neighbors > 0 and len(nodes) > 1:
            print(f"[*] Отбор пар методом k={k_neighbors} ближайших соседей (k-NN sparsification)...")
            import osmnx as ox
            for i, src in enumerate(nodes):
                # Считаем расстояния до всех остальных объектов
                dists = []
                for j, dst in enumerate(nodes):
                    if i != j:
                        d = ox.distance.great_circle(src.latitude, src.longitude, dst.latitude, dst.longitude)
                        dists.append((j, d))
                dists.sort(key=lambda x: x[1])
                for j, _ in dists[:k_neighbors]:
                    pair = tuple(sorted([i, j]))
                    pairs_to_check.add(pair)
            print(f"[+] Отобрано {len(pairs_to_check)} пар-кандидатов из {len(nodes) * (len(nodes) - 1) // 2} возможных.")
        else:
            print(f"[*] Полный перебор всех пар объектов (всего {len(nodes) * (len(nodes) - 1) // 2} пар)...")
            for i in range(len(nodes)):
                for j in range(i + 1, len(nodes)):
                    pairs_to_check.add((i, j))

        total_connections = 0

        for i, j in sorted(pairs_to_check):
            node_a = nodes[i]
            node_b = nodes[j]

            # Пул точек подключения (или fallback на nearest_osm_node)
            access_a = node_a.access_nodes or ([node_a.nearest_osm_node] if node_a.nearest_osm_node else [])
            access_b = node_b.access_nodes or ([node_b.nearest_osm_node] if node_b.nearest_osm_node else [])

            if not access_a or not access_b:
                continue

            coords_a = (node_a.longitude, node_a.latitude)
            coords_b = (node_b.longitude, node_b.latitude)

            # Находим лучший маршрут туда (A -> B) и обратно (B -> A) среди кандидатов
            route_ab = self._calculate_best_route(
                road_graph, access_a, access_b, 
                origin_coords=coords_a, dest_coords=coords_b
            )
            route_ba = self._calculate_best_route(
                road_graph, access_b, access_a, 
                origin_coords=coords_b, dest_coords=coords_a
            )

            has_route_ab = route_ab["status"] == RouteStatus.FOUND.value
            has_route_ba = route_ba["status"] == RouteStatus.FOUND.value

            if not has_route_ab and not has_route_ba:
                continue

            edge_obj = LogisticsEdge(
                node_a=node_a.id,
                node_b=node_b.id,
                node_a_name=node_a.name,
                node_b_name=node_b.name,
                transport_mode=TransportMode.ROAD.value,
                distance_ab_m=route_ab["distance_m"],
                total_distance_ab_m=route_ab["total_distance_m"],
                snap_origin_ab_m=route_ab["snap_origin_m"],
                snap_dest_ab_m=route_ab["snap_dest_m"],
                route_status_ab=route_ab["status"],
                osm_nodes_count_ab=route_ab["nodes_count"],
                path_osm_nodes_ab=route_ab["path"],
                geometry_ab_wkt=route_ab["geom_wkt"],
                distance_ba_m=route_ba["distance_m"],
                total_distance_ba_m=route_ba["total_distance_m"],
                snap_origin_ba_m=route_ba["snap_origin_m"],
                snap_dest_ba_m=route_ba["snap_dest_m"],
                route_status_ba=route_ba["status"],
                osm_nodes_count_ba=route_ba["nodes_count"],
                path_osm_nodes_ba=route_ba["path"],
                geometry_ba_wkt=route_ba["geom_wkt"],
                connection_status="candidate"
            )

            edge_dict = edge_obj.to_dict()
            # Дополнительно сохраняем геометрию подъездных коннекторов для визуализации
            edge_dict["conn_origin_ab_wkt"] = route_ab.get("origin_conn_wkt") or ""
            edge_dict["conn_dest_ab_wkt"] = route_ab.get("dest_conn_wkt") or ""
            edge_dict["conn_origin_ba_wkt"] = route_ba.get("origin_conn_wkt") or ""
            edge_dict["conn_dest_ba_wkt"] = route_ba.get("dest_conn_wkt") or ""
            clean_attrs = {}
            for k, v in edge_dict.items():
                if isinstance(v, (list, dict)):
                    clean_attrs[k] = json.dumps(v, ensure_ascii=False)
                else:
                    clean_attrs[k] = v

            log_graph.add_edge(
                node_a.id,
                node_b.id,
                key=TransportMode.ROAD.value,
                **clean_attrs
            )
            total_connections += 1

        print(f"[+] Логистический MultiGraph сформирован: {len(log_graph.nodes)} вершин, {len(log_graph.edges)} логистических связей.")
        return log_graph

    def save_graphml(self, log_graph: nx.MultiGraph, filename: str) -> str:
        """
        Сохраняет логистический MultiGraph в GraphML.
        Конвертирует None в пустые строки для совместимости со схемой GraphML.
        """
        clean_graph = nx.MultiGraph()
        clean_graph.graph.update(log_graph.graph)
        for n, data in log_graph.nodes(data=True):
            clean_graph.add_node(n, **{k: ("" if v is None else v) for k, v in data.items()})
        for u, v, k, data in log_graph.edges(keys=True, data=True):
            clean_graph.add_edge(u, v, key=k, **{attr: ("" if val is None else val) for attr, val in data.items()})

        filepath = os.path.join(self.storage_dir, f"{filename}.graphml")
        nx.write_graphml(clean_graph, filepath)
        print(f"[+] Логистический MultiGraph сохранен в GraphML: {filepath}")
        return filepath

    def load_graphml(self, filename: str) -> nx.MultiGraph:
        """
        Загружает логистический MultiGraph из файла GraphML.
        """
        filepath = os.path.join(self.storage_dir, f"{filename}.graphml")
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Файл {filepath} не найден!")

        graph = nx.read_graphml(filepath)
        print(f"[+] Логистический MultiGraph загружен из GraphML: {len(graph.nodes)} узлов, {len(graph.edges)} связей.")
        return graph

    def export_to_geojson(self, log_graph: nx.MultiGraph, filename: str) -> str:
        """
        Экспортирует логистический MultiGraph в GeoJSON для Frontend:
        - Хабы: маркеры с метаданными и snap_distance_m.
        - Маршруты: доступные линии направлений A -> B и B -> A с дистанциями.
        """
        filepath = os.path.join(self.storage_dir, f"{filename}.geojson")
        features = []

        for node_id, data in log_graph.nodes(data=True):
            lat = float(data.get("latitude", 0.0))
            lon = float(data.get("longitude", 0.0))
            point_geom = Point(lon, lat)

            features.append({
                "type": "Feature",
                "geometry": mapping(point_geom),
                "properties": {
                    "feature_type": "logistics_hub",
                    "id": node_id,
                    "name": data.get("name", node_id),
                    "object_type": data.get("object_type", "facility"),
                    "verification_status": data.get("verification_status", "candidate"),
                    "graph_role": data.get("graph_role", "node_candidate"),
                    "parent_site_id": data.get("parent_site_id") or None,
                    "snap_distance_m": data.get("snap_distance_m", 0.0),
                    "nearest_osm_node": data.get("nearest_osm_node", 0),
                    "region_ids": data.get("region_ids", "ru-spb")
                }
            })

        # Множество добавленных коннекторов доступа (для исключения дубликатов на карте)
        added_connectors = set()

        for u, v, key, data in log_graph.edges(keys=True, data=True):
            # Линия A -> B
            geom_ab = data.get("geometry_ab_wkt")
            if geom_ab and data.get("route_status_ab") == RouteStatus.FOUND.value:
                line_geom = wkt.loads(geom_ab) if isinstance(geom_ab, str) else geom_ab
                features.append({
                    "type": "Feature",
                    "geometry": mapping(line_geom),
                    "properties": {
                        "feature_type": "transport_route",
                        "transport_mode": key,
                        "direction": "ab",
                        "source_id": u,
                        "target_id": v,
                        "source_name": data.get("node_a_name", u),
                        "target_name": data.get("node_b_name", v),
                        "road_distance_m": data.get("distance_ab_m"),
                        "total_distance_m": data.get("total_distance_ab_m") or data.get("distance_ab_m"),
                        "distance_m": data.get("total_distance_ab_m") or data.get("distance_ab_m"),
                        "snap_origin_m": data.get("snap_origin_ab_m", 0.0),
                        "snap_dest_m": data.get("snap_dest_ab_m", 0.0),
                        "osm_nodes_count": data.get("osm_nodes_count_ab"),
                        "is_door_to_door": True,
                        "title": f"{data.get('node_a_name', u)} → {data.get('node_b_name', v)}"
                    }
                })

            # Линия B -> A
            geom_ba = data.get("geometry_ba_wkt")
            if geom_ba and data.get("route_status_ba") == RouteStatus.FOUND.value:
                line_geom = wkt.loads(geom_ba) if isinstance(geom_ba, str) else geom_ba
                features.append({
                    "type": "Feature",
                    "geometry": mapping(line_geom),
                    "properties": {
                        "feature_type": "transport_route",
                        "transport_mode": key,
                        "direction": "ba",
                        "source_id": v,
                        "target_id": u,
                        "source_name": data.get("node_b_name", v),
                        "target_name": data.get("node_a_name", u),
                        "road_distance_m": data.get("distance_ba_m"),
                        "total_distance_m": data.get("total_distance_ba_m") or data.get("distance_ba_m"),
                        "distance_m": data.get("total_distance_ba_m") or data.get("distance_ba_m"),
                        "snap_origin_m": data.get("snap_origin_ba_m", 0.0),
                        "snap_dest_m": data.get("snap_dest_ba_m", 0.0),
                        "osm_nodes_count": data.get("osm_nodes_count_ba"),
                        "is_door_to_door": True,
                        "title": f"{data.get('node_b_name', v)} → {data.get('node_a_name', u)}"
                    }
                })

            # Пунктирные коннекторы подъезда к дорожной сети (Access Legs / First-Last Mile)
            conn_origin = data.get("conn_origin_ab_wkt")
            if conn_origin and conn_origin not in added_connectors:
                added_connectors.add(conn_origin)
                features.append({
                    "type": "Feature",
                    "geometry": mapping(wkt.loads(conn_origin)),
                    "properties": {
                        "feature_type": "access_connector",
                        "connector_type": "entry_leg",
                        "hub_id": u,
                        "hub_name": data.get("node_a_name", u),
                        "distance_m": data.get("snap_origin_ab_m", 0.0),
                        "stroke": "#f59e0b",
                        "stroke-width": 2,
                        "stroke-dasharray": "4 4",
                        "is_dashed": True,
                        "title": f"Подъезд: {data.get('node_a_name', u)} → Дорога"
                    }
                })

            conn_dest = data.get("conn_dest_ab_wkt")
            if conn_dest and conn_dest not in added_connectors:
                added_connectors.add(conn_dest)
                features.append({
                    "type": "Feature",
                    "geometry": mapping(wkt.loads(conn_dest)),
                    "properties": {
                        "feature_type": "access_connector",
                        "connector_type": "exit_leg",
                        "hub_id": v,
                        "hub_name": data.get("node_b_name", v),
                        "distance_m": data.get("snap_dest_ab_m", 0.0),
                        "stroke": "#f59e0b",
                        "stroke-width": 2,
                        "stroke-dasharray": "4 4",
                        "is_dashed": True,
                        "title": f"Подъезд: Дорога → {data.get('node_b_name', v)}"
                    }
                })

        geojson_doc = {
            "type": "FeatureCollection",
            "features": features
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(geojson_doc, f, ensure_ascii=False, indent=2)

        print(f"[+] GeoJSON логистического MultiGraph сохранен в: {filepath}")
        return filepath

    def get_summary(self, log_graph: nx.MultiGraph) -> Dict[str, Any]:
        """
        Формирует аналитическую сводку по логистическому MultiGraph.
        """
        nodes_list = [
            {
                "id": n, 
                "name": d.get("name"), 
                "type": d.get("object_type"), 
                "snap_dist_m": d.get("snap_distance_m")
            }
            for n, d in log_graph.nodes(data=True)
        ]

        connections = []
        all_distances_km = []

        for u, v, key, d in log_graph.edges(keys=True, data=True):
            dist_ab = d.get("distance_ab_m")
            dist_ba = d.get("distance_ba_m")

            dist_ab_val: Optional[float] = None
            if dist_ab not in (None, ""):
                try:
                    dist_ab_val = float(dist_ab)
                    all_distances_km.append(round(dist_ab_val / 1000, 2))
                except (ValueError, TypeError):
                    dist_ab_val = None

            dist_ba_val: Optional[float] = None
            if dist_ba not in (None, ""):
                try:
                    dist_ba_val = float(dist_ba)
                    all_distances_km.append(round(dist_ba_val / 1000, 2))
                except (ValueError, TypeError):
                    dist_ba_val = None

            connections.append({
                "pair": f"{d.get('node_a_name', u)} ⟷ {d.get('node_b_name', v)}",
                "mode": key,
                "dist_ab_km": round(dist_ab_val / 1000, 2) if dist_ab_val is not None else None,
                "dist_ba_km": round(dist_ba_val / 1000, 2) if dist_ba_val is not None else None,
                "status_ab": d.get("route_status_ab"),
                "status_ba": d.get("route_status_ba")
            })

        avg_dist = round(sum(all_distances_km) / len(all_distances_km), 2) if all_distances_km else 0.0

        return {
            "total_hubs": len(log_graph.nodes),
            "total_connections": len(log_graph.edges),
            "avg_route_distance_km": avg_dist,
            "hubs": nodes_list,
            "sample_connections": connections[:5]
        }
