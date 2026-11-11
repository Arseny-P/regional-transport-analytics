import os
import json
import heapq
from itertools import count
from typing import List, Dict, Any, Union, Optional, Tuple, Set
import networkx as nx
from shapely.geometry import Point, LineString, MultiLineString, mapping
from shapely.ops import linemerge
from shapely import wkt

from graph_service.domain.models import LogisticsNode, LogisticsEdge, TransportMode, RouteStatus, GraphRole, RouteDetail


class LogisticsGraphService:
    """
    Сервис маршрутизации, синтеза логистического MultiGraph и его экспорта (GraphML / GeoJSON).
    """

    def __init__(self, storage_dir: str = "data"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)

    @staticmethod
    def _get_best_edge(road_graph: nx.MultiDiGraph, u: int, v: int) -> Tuple[Any, Dict[str, Any]]:
        """
        Возвращает (key, edge_data) для ребра с минимальным весом 'length'
        между узлами u и v в MultiDiGraph (решение проблемы выбора конкретного ребра, а не всегда key=0).
        """
        edges = road_graph[u][v]
        if not edges:
            return 0, {}
        best_key = min(edges.keys(), key=lambda k: edges[k].get("length", float("inf")))
        return best_key, edges[best_key]

    def _extract_route_geometry_and_keys(
        self, road_graph: nx.MultiDiGraph, path: List[int]
    ) -> Tuple[LineString, List[Tuple[int, int, Any]]]:
        """
        Склеивает последовательные сегменты ребер пути в единую непрерывную геометрию LineString
        и извлекает конкретные ключи параллельных рёбер (u, v, key).
        """
        if not path:
            return LineString(), []
        if len(path) == 1:
            pt = (float(road_graph.nodes[path[0]]["x"]), float(road_graph.nodes[path[0]]["y"]))
            return LineString([pt, pt]), []

        lines = []
        edge_keys: List[Tuple[int, int, Any]] = []

        for u, v in zip(path[:-1], path[1:]):
            k, edge_data = self._get_best_edge(road_graph, u, v)
            edge_keys.append((u, v, k))
            if "geometry" in edge_data and isinstance(edge_data["geometry"], LineString):
                lines.append(edge_data["geometry"])
            else:
                p1 = (float(road_graph.nodes[u]["x"]), float(road_graph.nodes[u]["y"]))
                p2 = (float(road_graph.nodes[v]["x"]), float(road_graph.nodes[v]["y"]))
                lines.append(LineString([p1, p2]))

        if not lines:
            pt = (float(road_graph.nodes[path[0]]["x"]), float(road_graph.nodes[path[0]]["y"]))
            return LineString([pt, pt]), edge_keys

        merged = linemerge(lines)
        if isinstance(merged, MultiLineString):
            coords = []
            for ls in merged.geoms:
                coords.extend(ls.coords)
            geom = LineString(coords)
        elif isinstance(merged, LineString):
            geom = merged
        else:
            coords = []
            for u in path:
                coords.append((float(road_graph.nodes[u]["x"]), float(road_graph.nodes[u]["y"])))
            geom = LineString(coords)

        return geom, edge_keys

    def _extract_route_geometry(self, road_graph: nx.MultiDiGraph, path: List[int]) -> LineString:
        """
        Склеивает последовательные сегменты ребер пути в единую непрерывную геометрию LineString.
        Обеспечивает обратную совместимость с использованием _extract_route_geometry_and_keys.
        """
        geom, _ = self._extract_route_geometry_and_keys(road_graph, path)
        return geom

    @classmethod
    def _dijkstra_to_targets(
        cls,
        road_graph: nx.MultiDiGraph,
        source: int,
        targets: Optional[Set[int]] = None,
        weight: str = "length",
    ) -> Tuple[Dict[int, float], Dict[int, List[int]]]:
        """
        Вычисляет кратчайшие пути от source до набора целевых вершин targets.
        Прекращает поиск (early stopping), как только все достижимые вершины из targets найдены.
        В отличие от стандартного single_source_dijkstra(G, source), НЕ сохраняет в памяти
        пути ко всей остальной дорожной сети (тысячам/десяткам тысяч узлов региона),
        что предотвращает исчерпание RAM.
        """
        if source not in road_graph:
            return {}, {}

        if targets is None:
            try:
                return nx.single_source_dijkstra(road_graph, source=source, weight=weight)
            except (nx.NodeNotFound, KeyError):
                return {}, {}

        unvisited_targets = set(targets)
        dist: Dict[int, float] = {}
        paths: Dict[int, List[int]] = {}

        if source in unvisited_targets:
            dist[source] = 0.0
            paths[source] = [source]
            unvisited_targets.remove(source)

        if not unvisited_targets:
            return dist, paths

        c = count()
        fringe = [(0.0, next(c), source)]
        seen: Dict[int, float] = {source: 0.0}
        pred: Dict[int, int] = {}
        all_dists: Dict[int, float] = {}

        adj = road_graph._adj

        while fringe and unvisited_targets:
            d, _, u = heapq.heappop(fringe)
            if u in all_dists:
                continue
            all_dists[u] = d

            if u in unvisited_targets:
                unvisited_targets.remove(u)
                if not unvisited_targets:
                    break

            for v, edges in adj[u].items():
                min_len = float("inf")
                for e_data in edges.values():
                    w = e_data.get(weight, 1.0)
                    if w is not None and w < min_len:
                        min_len = float(w)
                if min_len == float("inf"):
                    continue

                vu_dist = d + min_len
                if v not in seen or vu_dist < seen[v]:
                    seen[v] = vu_dist
                    pred[v] = u
                    heapq.heappush(fringe, (vu_dist, next(c), v))

        for t in targets:
            if t in all_dists:
                path = [t]
                curr = t
                seen_path = {t}
                while curr != source and curr in pred:
                    curr = pred[curr]
                    if curr in seen_path:
                        break
                    seen_path.add(curr)
                    path.append(curr)
                if curr == source:
                    path.reverse()
                    paths[t] = path
                    dist[t] = all_dists[t]

        return dist, paths

    def _calculate_best_route(
        self, 
        road_graph: nx.MultiDiGraph, 
        start_nodes: List[int], 
        end_nodes: List[int],
        origin_coords: Optional[Tuple[float, float]] = None,
        dest_coords: Optional[Tuple[float, float]] = None,
        dijkstra_cache: Optional[Dict[int, Tuple[Dict[int, float], Dict[int, List[int]]]]] = None,
        target_nodes: Optional[Set[int]] = None,
    ) -> Dict[str, Any]:
        """
        Находит наилучший (кратчайший) маршрут среди пула кандидатов точек подключения.
        Реализует сквозную минимизацию полной дистанции Door-to-Door (плечо_A + дорога + плечо_B).
        Использует кэш Dijkstra по начальным дорожным точкам для повторного использования вычислений.
        Корректно обрабатывает параллельные ребра MultiDiGraph.
        """
        import osmnx as ox

        best_total_distance = float("inf")
        best_distance = float("inf")
        best_snap_u = 0.0
        best_snap_v = 0.0
        best_u = None
        best_v = None
        best_path: List[int] = []

        query_targets = target_nodes if target_nodes is not None else set(end_nodes)

        for u in start_nodes:
            if u not in road_graph:
                continue
            u_lat = float(road_graph.nodes[u]["y"])
            u_lon = float(road_graph.nodes[u]["x"])
            snap_u = (
                ox.distance.great_circle(origin_coords[1], origin_coords[0], u_lat, u_lon)
                if origin_coords
                else 0.0
            )

            # Получаем или кэшируем дерево кратчайших путей из точки u только до целевых вершин
            lengths: Dict[int, float] = {}
            paths: Dict[int, List[int]] = {}
            if dijkstra_cache is not None:
                if u not in dijkstra_cache:
                    lengths, paths = self._dijkstra_to_targets(
                        road_graph, source=u, targets=query_targets, weight="length"
                    )
                    dijkstra_cache[u] = (lengths, paths)
                else:
                    lengths, paths = dijkstra_cache[u]
                    missing = set(end_nodes) - set(lengths.keys())
                    if missing and any(v in road_graph for v in missing):
                        add_lengths, add_paths = self._dijkstra_to_targets(
                            road_graph, source=u, targets=missing, weight="length"
                        )
                        lengths.update(add_lengths)
                        paths.update(add_paths)
            else:
                lengths, paths = self._dijkstra_to_targets(
                    road_graph, source=u, targets=query_targets, weight="length"
                )

            for v in end_nodes:
                if v not in road_graph:
                    continue

                v_lat = float(road_graph.nodes[v]["y"])
                v_lon = float(road_graph.nodes[v]["x"])
                snap_v = (
                    ox.distance.great_circle(dest_coords[1], dest_coords[0], v_lat, v_lon)
                    if dest_coords
                    else 0.0
                )

                if u == v:
                    d = 0.0
                    candidate_path = [u]
                elif v in lengths:
                    d = lengths[v]
                    candidate_path = paths[v]
                else:
                    continue

                total_candidate = d + snap_u + snap_v
                if total_candidate < best_total_distance:
                    best_total_distance = total_candidate
                    best_distance = d
                    best_snap_u = snap_u
                    best_snap_v = snap_v
                    best_u = u
                    best_v = v
                    best_path = candidate_path

        if best_u is None or best_v is None or best_distance == float("inf"):
            return {
                "status": RouteStatus.NOT_FOUND_IN_DATA.value,
                "distance_m": None,
                "total_distance_m": None,
                "snap_origin_m": None,
                "snap_dest_m": None,
                "nodes_count": 0,
                "path": [],
                "edge_keys": [],
                "geom_wkt": None,
                "road_geom_wkt": None,
                "access_u": None,
                "access_v": None,
                "origin_conn_wkt": None,
                "dest_conn_wkt": None,
            }

        path_nodes = [int(n) for n in best_path]
        route_geom, edge_keys = self._extract_route_geometry_and_keys(road_graph, path_nodes)

        u_lon = float(road_graph.nodes[best_u]["x"])
        u_lat = float(road_graph.nodes[best_u]["y"])
        v_lon = float(road_graph.nodes[best_v]["x"])
        v_lat = float(road_graph.nodes[best_v]["y"])

        snap_origin_m = best_snap_u
        snap_dest_m = best_snap_v
        door_to_door_coords = []
        origin_conn_wkt = None
        dest_conn_wkt = None

        if origin_coords:
            door_to_door_coords.append(origin_coords)
            origin_conn_wkt = LineString([origin_coords, (u_lon, u_lat)]).wkt

        if len(route_geom.coords) > 0:
            door_to_door_coords.extend(list(route_geom.coords))
        else:
            door_to_door_coords.extend([(u_lon, u_lat), (v_lon, v_lat)])

        if dest_coords:
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
            "edge_keys": edge_keys,
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
                        access_nodes=n.get("access_nodes", [n.get("nearest_osm_node")] if n.get("nearest_osm_node") else []),
                        is_isolated=bool(n.get("is_isolated", False)),
                        isolation_reason=n.get("isolation_reason"),
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
                access_nodes=json.dumps(node.access_nodes),
                is_isolated=node.is_isolated,
                isolation_reason=node.isolation_reason or "",
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
        dijkstra_cache: Dict[int, Tuple[Dict[int, float], Dict[int, List[int]]]] = {}
        all_access_nodes: Set[int] = {
            acc
            for n in nodes
            for acc in (n.access_nodes or ([n.nearest_osm_node] if n.nearest_osm_node else []))
        }

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
                origin_coords=coords_a, dest_coords=coords_b,
                dijkstra_cache=dijkstra_cache,
                target_nodes=all_access_nodes,
            )
            route_ba = self._calculate_best_route(
                road_graph, access_b, access_a, 
                origin_coords=coords_b, dest_coords=coords_a,
                dijkstra_cache=dijkstra_cache,
                target_nodes=all_access_nodes,
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
                edge_keys_ab=route_ab.get("edge_keys", []),
                geometry_ab_wkt=route_ab["geom_wkt"],
                road_geometry_ab_wkt=route_ab["road_geom_wkt"],
                distance_ba_m=route_ba["distance_m"],
                total_distance_ba_m=route_ba["total_distance_m"],
                snap_origin_ba_m=route_ba["snap_origin_m"],
                snap_dest_ba_m=route_ba["snap_dest_m"],
                route_status_ba=route_ba["status"],
                osm_nodes_count_ba=route_ba["nodes_count"],
                path_osm_nodes_ba=route_ba["path"],
                edge_keys_ba=route_ba.get("edge_keys", []),
                geometry_ba_wkt=route_ba["geom_wkt"],
                road_geometry_ba_wkt=route_ba["road_geom_wkt"],
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

    def calculate_all_routes(
        self,
        road_graph: nx.MultiDiGraph,
        nodes: List[Union[LogisticsNode, Dict[str, Any]]],
        k_neighbors: Optional[int] = None,
    ) -> List[RouteDetail]:
        """
        Вычисляет направленные маршруты между всеми парами складов
        с кэшированием вычислений по общим точкам привязки на дорожной сети.
        """
        parsed_nodes: List[LogisticsNode] = []
        for n in nodes:
            if isinstance(n, LogisticsNode):
                parsed_nodes.append(n)
            else:
                parsed_nodes.append(
                    LogisticsNode(
                        id=str(n["id"]),
                        name=str(n.get("name") or n["id"]),
                        object_type=str(n.get("object_type") or n.get("type", "facility")),
                        latitude=float(n.get("latitude") or n.get("lat")),
                        longitude=float(n.get("longitude") or n.get("lon")),
                        nearest_osm_node=n.get("nearest_osm_node"),
                        access_nodes=n.get("access_nodes", []),
                        is_isolated=bool(n.get("is_isolated", False)),
                    )
                )

        pairs_to_check = set()
        if k_neighbors is not None and k_neighbors > 0 and len(parsed_nodes) > 1:
            import osmnx as ox
            for i, src in enumerate(parsed_nodes):
                dists = []
                for j, dst in enumerate(parsed_nodes):
                    if i != j:
                        d = ox.distance.great_circle(src.latitude, src.longitude, dst.latitude, dst.longitude)
                        dists.append((j, d))
                dists.sort(key=lambda x: x[1])
                for j, _ in dists[:k_neighbors]:
                    pair = tuple(sorted([i, j]))
                    pairs_to_check.add(pair)
        else:
            for i in range(len(parsed_nodes)):
                for j in range(i + 1, len(parsed_nodes)):
                    pairs_to_check.add((i, j))

        all_access_nodes: Set[int] = {
            acc
            for n in parsed_nodes
            for acc in (n.access_nodes or ([n.nearest_osm_node] if n.nearest_osm_node else []))
        }

        dijkstra_cache: Dict[int, Tuple[Dict[int, float], Dict[int, List[int]]]] = {}
        routes: List[RouteDetail] = []

        for i, j in sorted(pairs_to_check):
            node_a = parsed_nodes[i]
            node_b = parsed_nodes[j]

            access_a = node_a.access_nodes or ([node_a.nearest_osm_node] if node_a.nearest_osm_node else [])
            access_b = node_b.access_nodes or ([node_b.nearest_osm_node] if node_b.nearest_osm_node else [])

            if not access_a or not access_b:
                routes.append(
                    RouteDetail(
                        origin_id=node_a.id,
                        destination_id=node_b.id,
                        status=RouteStatus.NOT_FOUND_IN_DATA.value,
                    )
                )
                routes.append(
                    RouteDetail(
                        origin_id=node_b.id,
                        destination_id=node_a.id,
                        status=RouteStatus.NOT_FOUND_IN_DATA.value,
                    )
                )
                continue

            coords_a = (node_a.longitude, node_a.latitude)
            coords_b = (node_b.longitude, node_b.latitude)

            # Направление A -> B
            res_ab = self._calculate_best_route(
                road_graph, access_a, access_b,
                origin_coords=coords_a, dest_coords=coords_b,
                dijkstra_cache=dijkstra_cache,
                target_nodes=all_access_nodes,
            )
            routes.append(
                RouteDetail(
                    origin_id=node_a.id,
                    destination_id=node_b.id,
                    status=res_ab["status"],
                    road_length_m=res_ab["distance_m"],
                    total_length_m=res_ab["total_distance_m"],
                    snap_origin_m=res_ab["snap_origin_m"],
                    snap_dest_m=res_ab["snap_dest_m"],
                    node_path=res_ab["path"],
                    edge_keys=res_ab["edge_keys"],
                    road_geometry_wkt=res_ab["road_geom_wkt"],
                    full_geometry_wkt=res_ab["geom_wkt"],
                    access_u=res_ab["access_u"],
                    access_v=res_ab["access_v"],
                )
            )

            # Направление B -> A
            res_ba = self._calculate_best_route(
                road_graph, access_b, access_a,
                origin_coords=coords_b, dest_coords=coords_a,
                dijkstra_cache=dijkstra_cache,
                target_nodes=all_access_nodes,
            )
            routes.append(
                RouteDetail(
                    origin_id=node_b.id,
                    destination_id=node_a.id,
                    status=res_ba["status"],
                    road_length_m=res_ba["distance_m"],
                    total_length_m=res_ba["total_distance_m"],
                    snap_origin_m=res_ba["snap_origin_m"],
                    snap_dest_m=res_ba["snap_dest_m"],
                    node_path=res_ba["path"],
                    edge_keys=res_ba["edge_keys"],
                    road_geometry_wkt=res_ba["road_geom_wkt"],
                    full_geometry_wkt=res_ba["geom_wkt"],
                    access_u=res_ba["access_u"],
                    access_v=res_ba["access_v"],
                )
            )

        return routes

    def build_route_road_graph(
        self,
        road_graph: nx.MultiDiGraph,
        nodes: List[Union[LogisticsNode, Dict[str, Any]]],
        routes: Optional[List[RouteDetail]] = None,
        k_neighbors: Optional[int] = None,
    ) -> nx.MultiDiGraph:
        """
        Формирует единый дорожный граф маршрутов:
        1. Вершины:
           - Все склады (facility / warehouse), включая изолированные без найденных маршрутов.
           - Дорожные узлы (перекрёстки 'intersection' и промежуточные 'road_node'),
             входящие хотя бы в один найденный маршрут или являющиеся точками привязки.
        2. Рёбра:
           - Дорожные сегменты ('road'): уникальные направленные сегменты (u, v, key),
             попавшие хотя бы в один найденный маршрут (с дедупликацией и счетчиком routes_count).
           - Подъездные коннекторы ('access_connector'): связи склад -> дорожный узел и дорожный узел -> склад.
        3. Метаданные:
           - Сведения о найденных маршрутах сохраняются в атрибуте graph["routes"].
        """
        import osmnx as ox

        # 1. Нормализация списка складов
        warehouses: Dict[str, LogisticsNode] = {}
        for n in nodes:
            if isinstance(n, LogisticsNode):
                warehouses[n.id] = n
            else:
                w_id = str(n["id"])
                warehouses[w_id] = LogisticsNode(
                    id=w_id,
                    name=str(n.get("name") or w_id),
                    object_type=str(n.get("object_type") or n.get("type", "facility")),
                    latitude=float(n.get("latitude") or n.get("lat")),
                    longitude=float(n.get("longitude") or n.get("lon")),
                    nearest_osm_node=n.get("nearest_osm_node"),
                    snap_distance_m=n.get("snap_distance_m"),
                    access_nodes=n.get("access_nodes", []),
                    is_isolated=bool(n.get("is_isolated", False)),
                )

        # 2. Если маршруты не переданы извне, рассчитываем их
        if routes is None:
            routes = self.calculate_all_routes(
                road_graph=road_graph,
                nodes=list(warehouses.values()),
                k_neighbors=k_neighbors,
            )

        route_graph = nx.MultiDiGraph()
        route_graph.graph["crs"] = "epsg:4326"
        route_graph.graph["routes"] = [r.to_dict() for r in routes]
        route_graph.graph["total_routes"] = len(routes)
        route_graph.graph["found_routes"] = sum(1 for r in routes if r.status == RouteStatus.FOUND.value)

        # 3. Сбор статистики использования дорожных узлов и сегментов
        connected_warehouses = set()
        used_road_nodes = set()
        road_segment_usage: Dict[Tuple[int, int, Any], Dict[str, Any]] = {}
        connectors_to_add: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

        for r in routes:
            if r.status != RouteStatus.FOUND.value:
                continue

            connected_warehouses.add(r.origin_id)
            connected_warehouses.add(r.destination_id)

            for n in r.node_path:
                used_road_nodes.add(n)
            if r.access_u is not None:
                used_road_nodes.add(r.access_u)
            if r.access_v is not None:
                used_road_nodes.add(r.access_v)

            # Направленные дорожные сегменты (u, v, key)
            for u, v, k in r.edge_keys:
                seg_key = (u, v, k)
                if seg_key not in road_segment_usage:
                    road_segment_usage[seg_key] = {
                        "routes": [],
                        "count": 0,
                    }
                road_segment_usage[seg_key]["count"] += 1
                road_segment_usage[seg_key]["routes"].append(f"{r.origin_id}->{r.destination_id}")

            # Подъездные коннекторы (access_connector)
            # Отправление: склад -> дорожный узел
            if r.access_u is not None:
                c_out_key = (r.origin_id, str(r.access_u), "access_out")
                if c_out_key not in connectors_to_add:
                    connectors_to_add[c_out_key] = {
                        "source": r.origin_id,
                        "target": str(r.access_u),
                        "key": "access_out",
                        "edge_type": "access_connector",
                        "length_m": r.snap_origin_m,
                        "warehouse_id": r.origin_id,
                        "road_node_id": str(r.access_u),
                        "direction": "origin_to_road",
                        "routes_count": 0,
                    }
                connectors_to_add[c_out_key]["routes_count"] += 1

            # Прибытие: дорожный узел -> склад
            if r.access_v is not None:
                c_in_key = (str(r.access_v), r.destination_id, "access_in")
                if c_in_key not in connectors_to_add:
                    connectors_to_add[c_in_key] = {
                        "source": str(r.access_v),
                        "target": r.destination_id,
                        "key": "access_in",
                        "edge_type": "access_connector",
                        "length_m": r.snap_dest_m,
                        "warehouse_id": r.destination_id,
                        "road_node_id": str(r.access_v),
                        "direction": "road_to_dest",
                        "routes_count": 0,
                    }
                connectors_to_add[c_in_key]["routes_count"] += 1

        # 4. Добавляем склады в граф (включая изолированные с фиксацией причины)
        for w_id, w in warehouses.items():
            is_isolated = (w_id not in connected_warehouses) or bool(w.is_isolated)
            isolation_reason = w.isolation_reason
            if is_isolated and not isolation_reason:
                isolation_reason = "Кратчайшие маршруты к другим объектам не найдены"
            obj_type = w.object_type if w.object_type in ("warehouse", "terminal", "port", "facility") else "warehouse"
            route_graph.add_node(
                str(w_id),
                name=w.name,
                object_type=obj_type,
                latitude=w.latitude,
                longitude=w.longitude,
                x=w.longitude,
                y=w.latitude,
                is_isolated=is_isolated,
                isolation_reason=isolation_reason if is_isolated else None,
                snap_distance_m=w.snap_distance_m if w.snap_distance_m is not None else 0.0,
                snap_kind=getattr(w, "snap_kind", None) or ("unconnected" if is_isolated else "osm_node"),
                nearest_osm_node=w.nearest_osm_node,
                region_ids=",".join(w.region_ids) if isinstance(w.region_ids, list) else str(w.region_ids),
            )

        # 5. Добавляем дорожные узлы в граф
        for n in used_road_nodes:
            if n not in road_graph.nodes:
                continue
            data = road_graph.nodes[n]
            x = float(data.get("x", 0.0))
            y = float(data.get("y", 0.0))

            street_count = data.get("street_count")
            if street_count is not None:
                is_intersection = (street_count >= 3)
            else:
                deg = road_graph.in_degree(n) + road_graph.out_degree(n)
                is_intersection = (deg >= 3)

            # Виртуальные врезанные узлы (is_virtual=True) классифицируются как road_node.
            # Не используем эвристику по ID >= 9_000_000_000, так как реальные узлы OSM могут иметь ID > 10 млрд.
            if bool(data.get("is_virtual", False)):
                is_intersection = False

            node_type = "intersection" if is_intersection else "road_node"

            route_graph.add_node(
                str(n),
                name=f"{node_type}_{n}",
                object_type=node_type,
                latitude=y,
                longitude=x,
                x=x,
                y=y,
                street_count=street_count if street_count is not None else (road_graph.in_degree(n) + road_graph.out_degree(n)),
                highway=data.get("highway", ""),
            )

        # 6. Добавляем дорожные рёбра (уникальные направленные сегменты)
        for (u, v, k), usage in road_segment_usage.items():
            if not road_graph.has_edge(u, v, k):
                continue
            edge_data = road_graph[u][v][k]
            geom = edge_data.get("geometry")
            if geom is None or not isinstance(geom, LineString):
                p1 = (float(road_graph.nodes[u]["x"]), float(road_graph.nodes[u]["y"]))
                p2 = (float(road_graph.nodes[v]["x"]), float(road_graph.nodes[v]["y"]))
                geom = LineString([p1, p2])

            length_m = float(edge_data.get("length", 0.0))
            if length_m <= 0.0 and len(geom.coords) >= 2:
                length_m = ox.distance.great_circle(
                    geom.coords[0][1], geom.coords[0][0], geom.coords[-1][1], geom.coords[-1][0]
                )

            edge_id = f"road_{u}_{v}_{k}"

            route_graph.add_edge(
                str(u),
                str(v),
                key=k,
                id=edge_id,
                edge_type="road",
                length_m=round(length_m, 2),
                geometry=geom,
                geometry_wkt=geom.wkt,
                routes_count=usage["count"],
                route_ids=usage["routes"],
                highway=str(edge_data.get("highway", "road")),
                name=str(edge_data.get("name", "")),
                maxspeed=str(edge_data.get("maxspeed", "")),
                oneway=bool(edge_data.get("oneway", False)),
                transport_mode="road",
            )

        # 7. Добавляем коннекторы последней мили (access_connector)
        for (src, dst, c_key), c_info in connectors_to_add.items():
            if src not in route_graph.nodes or dst not in route_graph.nodes:
                continue
            src_node = route_graph.nodes[src]
            dst_node = route_graph.nodes[dst]
            geom = LineString([
                (float(src_node["x"]), float(src_node["y"])),
                (float(dst_node["x"]), float(dst_node["y"])),
            ])
            conn_id = f"conn_{src}_{dst}_{c_key}"

            route_graph.add_edge(
                src,
                dst,
                key=c_key,
                id=conn_id,
                edge_type="access_connector",
                length_m=round(float(c_info.get("length_m") or 0.0), 2),
                geometry=geom,
                geometry_wkt=geom.wkt,
                routes_count=c_info["routes_count"],
                warehouse_id=c_info["warehouse_id"],
                road_node_id=c_info["road_node_id"],
                direction=c_info["direction"],
                transport_mode="road",
            )

        print(
            f"[+] Итоговый дорожный граф маршрутов сформирован: "
            f"{len(route_graph.nodes)} вершин ({sum(1 for _, d in route_graph.nodes(data=True) if d.get('object_type') in ('warehouse', 'facility'))} складов, "
            f"{sum(1 for _, d in route_graph.nodes(data=True) if d.get('object_type') == 'intersection')} перекрёстков, "
            f"{sum(1 for _, d in route_graph.nodes(data=True) if d.get('object_type') == 'road_node')} узлов дорог), "
            f"{len(route_graph.edges)} рёбер ({sum(1 for _, _, _, d in route_graph.edges(keys=True, data=True) if d.get('edge_type') == 'road')} дорожных, "
            f"{sum(1 for _, _, _, d in route_graph.edges(keys=True, data=True) if d.get('edge_type') == 'access_connector')} коннекторов)."
        )
        return route_graph

    def get_route_road_graph_summary(self, route_graph: nx.MultiDiGraph) -> Dict[str, Any]:
        """
        Возвращает детальную статистику по дорожному графу маршрутов.
        """
        warehouses = 0
        intersections = 0
        road_nodes = 0
        isolated_warehouses = 0

        for _, d in route_graph.nodes(data=True):
            obj_type = d.get("object_type")
            if obj_type in ("warehouse", "facility", "terminal", "port"):
                warehouses += 1
                if d.get("is_isolated"):
                    isolated_warehouses += 1
            elif obj_type == "intersection":
                intersections += 1
            else:
                road_nodes += 1

        road_edges = 0
        connectors = 0
        total_road_length_m = 0.0

        for _, _, _, d in route_graph.edges(keys=True, data=True):
            e_type = d.get("edge_type")
            if e_type == "access_connector":
                connectors += 1
            else:
                road_edges += 1
                total_road_length_m += float(d.get("length_m") or 0.0)

        return {
            "total_nodes": len(route_graph.nodes),
            "total_edges": len(route_graph.edges),
            "warehouses_count": warehouses,
            "intersections_count": intersections,
            "road_nodes_count": road_nodes,
            "isolated_warehouses_count": isolated_warehouses,
            "road_segments_count": road_edges,
            "access_connectors_count": connectors,
            "total_road_length_km": round(total_road_length_m / 1000.0, 3),
            "total_routes": route_graph.graph.get("total_routes", 0),
            "found_routes": route_graph.graph.get("found_routes", 0),
        }

    def export_route_road_graph_to_geojson(self, route_graph: nx.MultiDiGraph, filename: str) -> str:
        """
        Экспортирует дорожный граф маршрутов в GeoJSON для Frontend:
        - Склады, перекрёстки, промежуточные узлы (точки)
        - Дорожные сегменты и подъездные коннекторы (линии)
        """
        filepath = os.path.join(self.storage_dir, f"{filename}.geojson")
        features = []

        # Вершины
        for node_id, data in route_graph.nodes(data=True):
            x = float(data.get("x") or data.get("lon") or 0.0)
            y = float(data.get("y") or data.get("lat") or 0.0)
            pt_geom = Point(x, y)

            obj_type = data.get("object_type", "road_node")
            feature_type = "logistics_hub" if obj_type in ("warehouse", "facility", "terminal", "port") else obj_type

            props = {
                "id": str(node_id),
                "name": data.get("name", str(node_id)),
                "object_type": obj_type,
                "feature_type": feature_type,
            }
            for k in ("is_isolated", "isolation_reason", "snap_kind", "snap_distance_m", "street_count", "highway"):
                if k in data and data[k] is not None:
                    props[k] = data[k]

            features.append({
                "type": "Feature",
                "geometry": mapping(pt_geom),
                "properties": props,
            })

        # Рёбра
        for u, v, k, data in route_graph.edges(keys=True, data=True):
            geom = data.get("geometry")
            if geom is None or not isinstance(geom, LineString):
                u_node = route_graph.nodes[u]
                v_node = route_graph.nodes[v]
                geom = LineString([
                    (float(u_node.get("x", 0.0)), float(u_node.get("y", 0.0))),
                    (float(v_node.get("x", 0.0)), float(v_node.get("y", 0.0))),
                ])

            edge_type = data.get("edge_type", "road")
            feature_type = "transport_route" if edge_type == "road" else "access_connector"

            props = {
                "id": data.get("id", f"e_{u}_{v}_{k}"),
                "source": str(u),
                "target": str(v),
                "key": str(k),
                "edge_type": edge_type,
                "feature_type": feature_type,
                "is_strictly_road": (edge_type == "road"),
                "road_distance_m": data.get("length_m", 0.0),
                "length_m": data.get("length_m"),
                "routes_count": data.get("routes_count", 1),
            }
            for attr in ("highway", "name", "oneway", "maxspeed", "warehouse_id", "road_node_id", "direction"):
                if attr in data and data[attr] is not None:
                    props[attr] = data[attr]

            features.append({
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": props,
            })

        fc = {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "total_nodes": len(route_graph.nodes),
                "total_edges": len(route_graph.edges),
                "total_routes": route_graph.graph.get("total_routes", 0),
                "found_routes": route_graph.graph.get("found_routes", 0),
            }
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False, indent=2)

        print(f"[+] Дорожный граф маршрутов экспортирован в GeoJSON: {filepath} ({len(features)} фичей)")
        return filepath

    def save_graphml(self, log_graph: Union[nx.MultiGraph, nx.MultiDiGraph], filename: str) -> str:
        """
        Сохраняет граф (MultiGraph или MultiDiGraph) в GraphML.
        Конвертирует None в пустые строки и объекты в JSON/WKT для совместимости со схемой GraphML.
        """
        clean_graph = nx.MultiDiGraph() if isinstance(log_graph, (nx.MultiDiGraph, nx.DiGraph)) else nx.MultiGraph()
        clean_graph.graph.update({
            k: ("" if v is None else json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v) if not isinstance(v, (int, float, str, bool)) else v)
            for k, v in log_graph.graph.items()
        })

        for n, data in log_graph.nodes(data=True):
            clean_attrs = {}
            for k, v in data.items():
                if v is None:
                    clean_attrs[k] = ""
                elif isinstance(v, (list, dict)):
                    clean_attrs[k] = json.dumps(v, ensure_ascii=False)
                elif hasattr(v, "wkt"):
                    clean_attrs[k] = v.wkt
                elif not isinstance(v, (int, float, str, bool)):
                    clean_attrs[k] = str(v)
                else:
                    clean_attrs[k] = v
            clean_graph.add_node(n, **clean_attrs)

        for u, v, k, data in log_graph.edges(keys=True, data=True):
            clean_attrs = {}
            for attr, val in data.items():
                if val is None:
                    clean_attrs[attr] = ""
                elif isinstance(val, (list, dict)):
                    clean_attrs[attr] = json.dumps(val, ensure_ascii=False)
                elif hasattr(val, "wkt"):
                    clean_attrs[attr] = val.wkt
                elif attr == "geometry":
                    continue
                elif not isinstance(val, (int, float, str, bool)):
                    clean_attrs[attr] = str(val)
                else:
                    clean_attrs[attr] = val
            clean_graph.add_edge(u, v, key=k, **clean_attrs)

        filepath = os.path.join(self.storage_dir, f"{filename}.graphml")
        nx.write_graphml(clean_graph, filepath)
        print(f"[+] Граф сохранен в GraphML: {filepath}")
        return filepath

    def load_graphml(self, filename: str) -> Union[nx.MultiGraph, nx.MultiDiGraph]:
        """
        Загружает граф из файла GraphML.
        """
        filepath = os.path.join(self.storage_dir, f"{filename}.graphml")
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Файл {filepath} не найден!")

        graph = nx.read_graphml(filepath)
        print(f"[+] Граф загружен из GraphML: {len(graph.nodes)} узлов, {len(graph.edges)} связей.")
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
            is_isolated = bool(data.get("is_isolated", False))

            hub_props = {
                "feature_type": "logistics_hub",
                "id": node_id,
                "name": data.get("name", node_id),
                "object_type": data.get("object_type", "facility"),
                "verification_status": data.get("verification_status", "candidate"),
                "graph_role": data.get("graph_role", "node_candidate"),
                "parent_site_id": data.get("parent_site_id") or None,
                "snap_distance_m": data.get("snap_distance_m", 0.0),
                "nearest_osm_node": data.get("nearest_osm_node", 0),
                "region_ids": data.get("region_ids", "ru-spb"),
                "is_isolated": is_isolated,
                "isolation_reason": data.get("isolation_reason", ""),
            }
            if is_isolated:
                hub_props["marker-color"] = "#ef4444"
                hub_props["status_label"] = "Изолирован (нет дорожного подъезда)"

            features.append({
                "type": "Feature",
                "geometry": mapping(point_geom),
                "properties": hub_props
            })

        # Множество добавленных коннекторов доступа (для исключения дубликатов на карте)
        added_connectors = set()

        for u, v, key, data in log_graph.edges(keys=True, data=True):
            # Линия A -> B (строго по дорожному полотну)
            geom_ab = data.get("road_geometry_ab_wkt") or data.get("geometry_ab_wkt")
            if geom_ab and data.get("route_status_ab") == RouteStatus.FOUND.value:
                line_geom = wkt.loads(geom_ab) if isinstance(geom_ab, str) else geom_ab
                if not line_geom.is_empty and line_geom.length > 0:
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
                            "distance_m": data.get("distance_ab_m"),
                            "snap_origin_m": data.get("snap_origin_ab_m", 0.0),
                            "snap_dest_m": data.get("snap_dest_ab_m", 0.0),
                            "osm_nodes_count": data.get("osm_nodes_count_ab"),
                            "is_strictly_road": True,
                            "title": f"{data.get('node_a_name', u)} → {data.get('node_b_name', v)}"
                        }
                    })

            # Линия B -> A (строго по дорожному полотну)
            geom_ba = data.get("road_geometry_ba_wkt") or data.get("geometry_ba_wkt")
            if geom_ba and data.get("route_status_ba") == RouteStatus.FOUND.value:
                line_geom = wkt.loads(geom_ba) if isinstance(geom_ba, str) else geom_ba
                if not line_geom.is_empty and line_geom.length > 0:
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
                            "distance_m": data.get("distance_ba_m"),
                            "snap_origin_m": data.get("snap_origin_ba_m", 0.0),
                            "snap_dest_m": data.get("snap_dest_ba_m", 0.0),
                            "osm_nodes_count": data.get("osm_nodes_count_ba"),
                            "is_strictly_road": True,
                            "title": f"{data.get('node_b_name', v)} → {data.get('node_a_name', u)}"
                        }
                    })

            # Пунктирные коннекторы подъезда к дорожной сети (Access Legs / First-Last Mile)
            # Направление A -> B
            conn_origin_ab = data.get("conn_origin_ab_wkt")
            if conn_origin_ab and conn_origin_ab not in added_connectors:
                added_connectors.add(conn_origin_ab)
                features.append({
                    "type": "Feature",
                    "geometry": mapping(wkt.loads(conn_origin_ab)),
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

            conn_dest_ab = data.get("conn_dest_ab_wkt")
            if conn_dest_ab and conn_dest_ab not in added_connectors:
                added_connectors.add(conn_dest_ab)
                features.append({
                    "type": "Feature",
                    "geometry": mapping(wkt.loads(conn_dest_ab)),
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

            # Направление B -> A
            conn_origin_ba = data.get("conn_origin_ba_wkt")
            if conn_origin_ba and conn_origin_ba not in added_connectors:
                added_connectors.add(conn_origin_ba)
                features.append({
                    "type": "Feature",
                    "geometry": mapping(wkt.loads(conn_origin_ba)),
                    "properties": {
                        "feature_type": "access_connector",
                        "connector_type": "entry_leg",
                        "hub_id": v,
                        "hub_name": data.get("node_b_name", v),
                        "distance_m": data.get("snap_origin_ba_m", 0.0),
                        "stroke": "#f59e0b",
                        "stroke-width": 2,
                        "stroke-dasharray": "4 4",
                        "is_dashed": True,
                        "title": f"Подъезд: {data.get('node_b_name', v)} → Дорога"
                    }
                })

            conn_dest_ba = data.get("conn_dest_ba_wkt")
            if conn_dest_ba and conn_dest_ba not in added_connectors:
                added_connectors.add(conn_dest_ba)
                features.append({
                    "type": "Feature",
                    "geometry": mapping(wkt.loads(conn_dest_ba)),
                    "properties": {
                        "feature_type": "access_connector",
                        "connector_type": "exit_leg",
                        "hub_id": u,
                        "hub_name": data.get("node_a_name", u),
                        "distance_m": data.get("snap_dest_ba_m", 0.0),
                        "stroke": "#f59e0b",
                        "stroke-width": 2,
                        "stroke-dasharray": "4 4",
                        "is_dashed": True,
                        "title": f"Подъезд: Дорога → {data.get('node_a_name', u)}"
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
