import os
import json
from typing import List, Dict, Any
import networkx as nx
from shapely.geometry import Point, LineString, MultiLineString, mapping
from shapely.ops import linemerge
from shapely import wkt


class LogisticsGraphService:
    """
    Сервис маршрутизации, синтеза логистического графа связей и его экспорта (GraphML / GeoJSON).
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

    def build_logistics_graph(
        self, 
        road_graph: nx.MultiDiGraph, 
        snapped_points: List[Dict[str, Any]]
    ) -> nx.DiGraph:
        """
        Формирует логистический граф (OD-граф):
        - Вершины: логистические объекты со свойствами.
        - Рёбра: рассчитанные автомобильные маршруты между ними (длина, число узлов, геометрия).
        """
        log_graph = nx.DiGraph()

        # 1. Добавляем вершины (логистические хабы)
        for point in snapped_points:
            log_graph.add_node(
                str(point["id"]),
                name=str(point["name"]),
                lat=float(point["lat"]),
                lon=float(point["lon"]),
                type=str(point.get("type", "facility")),
                osm_node=int(point["nearest_osm_node"])
            )

        print(f"[*] Расчет кратчайших автомобильных маршрутов между {len(snapped_points)} объектами...")
        routes_found = 0

        # 2. Ищем пути между всеми парами объектов
        for i, src in enumerate(snapped_points):
            for j, dst in enumerate(snapped_points):
                if i == j:
                    continue

                u_osm = int(src["nearest_osm_node"])
                v_osm = int(dst["nearest_osm_node"])

                if not nx.has_path(road_graph, u_osm, v_osm):
                    print(f"  [!] Нет пути: '{src['name']}' -> '{dst['name']}'")
                    continue

                length_m = nx.shortest_path_length(road_graph, source=u_osm, target=v_osm, weight="length")
                path_nodes = [int(n) for n in nx.shortest_path(road_graph, source=u_osm, target=v_osm, weight="length")]
                route_geom = self._extract_route_geometry(road_graph, path_nodes)

                log_graph.add_edge(
                    str(src["id"]),
                    str(dst["id"]),
                    source_name=str(src["name"]),
                    target_name=str(dst["name"]),
                    distance_m=round(float(length_m), 2),
                    osm_nodes_count=len(path_nodes),
                    path_osm_nodes=json.dumps(path_nodes),
                    geometry=route_geom.wkt
                )
                routes_found += 1

        print(f"[+] Логистический граф сформирован: Вершин: {len(log_graph.nodes)}, Рёбер (маршрутов): {len(log_graph.edges)}")
        return log_graph

    def save_graphml(self, log_graph: nx.DiGraph, filename: str) -> str:
        """
        Сохраняет логистический граф в GraphML (для ML-модуля и повторной загрузки).
        """
        filepath = os.path.join(self.storage_dir, f"{filename}.graphml")
        nx.write_graphml(log_graph, filepath)
        print(f"[+] Логистический граф сохранен в GraphML: {filepath}")
        return filepath

    def load_graphml(self, filename: str) -> nx.DiGraph:
        """
        Загружает логистический граф из файла GraphML.
        """
        filepath = os.path.join(self.storage_dir, f"{filename}.graphml")
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Файл {filepath} не найден!")

        graph = nx.read_graphml(filepath)
        print(f"[+] Логистический граф загружен из GraphML: {len(graph.nodes)} узлов, {len(graph.edges)} ребер.")
        return graph

    def export_to_geojson(self, log_graph: nx.DiGraph, filename: str) -> str:
        """
        Экспортирует логистический граф в GeoJSON (точки объектов + линии маршрутов).
        Готов для прямой визуализации на фронтенде (Leaflet, Mapbox, geojson.io).
        """
        filepath = os.path.join(self.storage_dir, f"{filename}.geojson")
        features = []

        # 1. Добавляем точки (логистические объекты)
        for node_id, data in log_graph.nodes(data=True):
            point_geom = Point(float(data["lon"]), float(data["lat"]))
            feature = {
                "type": "Feature",
                "geometry": mapping(point_geom),
                "properties": {
                    "feature_type": "logistics_hub",
                    "id": node_id,
                    "name": data.get("name", node_id),
                    "hub_type": data.get("type", "unknown"),
                    "osm_node": data.get("osm_node")
                }
            }
            features.append(feature)

        # 2. Добавляем ребра (маршруты между объектами)
        for u, v, data in log_graph.edges(data=True):
            geom_val = data.get("geometry")
            if isinstance(geom_val, str):
                line_geom = wkt.loads(geom_val)
            else:
                line_geom = geom_val

            feature = {
                "type": "Feature",
                "geometry": mapping(line_geom),
                "properties": {
                    "feature_type": "transport_route",
                    "source_id": u,
                    "target_id": v,
                    "source_name": data.get("source_name", u),
                    "target_name": data.get("target_name", v),
                    "distance_m": data.get("distance_m"),
                    "osm_nodes_count": data.get("osm_nodes_count"),
                    "title": f"{data.get('source_name', u)} → {data.get('target_name', v)}"
                }
            }
            features.append(feature)

        geojson_doc = {
            "type": "FeatureCollection",
            "features": features
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(geojson_doc, f, ensure_ascii=False, indent=2)

        print(f"[+] GeoJSON логистического графа (объекты + маршруты) сохранен в: {filepath}")
        return filepath

    def get_summary(self, log_graph: nx.DiGraph) -> Dict[str, Any]:
        """
        Формирует аналитическую сводку по построенному логистическому графу.
        """
        nodes_list = [
            {"id": n, "name": d.get("name"), "type": d.get("type"), "coords": (d.get("lat"), d.get("lon"))}
            for n, d in log_graph.nodes(data=True)
        ]
        
        edges_summary = []
        for u, v, d in log_graph.edges(data=True):
            edges_summary.append({
                "from": d.get("source_name", u),
                "to": d.get("target_name", v),
                "distance_km": round(float(d.get("distance_m", 0)) / 1000, 2),
                "osm_nodes_count": d.get("osm_nodes_count")
            })

        distances = [float(d.get("distance_m", 0)) for _, _, d in log_graph.edges(data=True)]
        avg_distance_km = round(sum(distances) / len(distances) / 1000, 2) if distances else 0.0

        # Разнообразная выборка: берем по 1 маршруту от разных пунктов отправления
        seen_sources = set()
        diverse_routes = []
        for route in edges_summary:
            src = route["from"]
            if src not in seen_sources:
                diverse_routes.append(route)
                seen_sources.add(src)
                if len(diverse_routes) >= 6:
                    break

        # Если уникальных отправных пунктов меньше 5, дополняем любыми доступными
        if len(diverse_routes) < 5 and edges_summary:
            for route in edges_summary:
                if route not in diverse_routes:
                    diverse_routes.append(route)
                    if len(diverse_routes) >= 5:
                        break

        # Находим самый короткий и самый длинный маршруты в сети
        sorted_routes = sorted(edges_summary, key=lambda x: x["distance_km"]) if edges_summary else []
        min_route = sorted_routes[0] if sorted_routes else None
        max_route = sorted_routes[-1] if sorted_routes else None

        return {
            "total_hubs": len(log_graph.nodes),
            "total_routes": len(log_graph.edges),
            "avg_route_distance_km": avg_distance_km,
            "min_route": min_route,
            "max_route": max_route,
            "hubs": nodes_list,
            "sample_routes": diverse_routes
        }
