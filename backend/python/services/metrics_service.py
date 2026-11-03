import networkx as nx
import math


def calculate_basic_metrics(graph: nx.Graph) -> dict:
    """
    Рассчитывает базовые характеристики логистического графа.

    На данном этапе направления маршрутов не учитываются.
    """

    return {
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "component_count": nx.number_connected_components(graph),
    }

def to_directed_graph(graph: nx.Graph) -> nx.DiGraph:
    """
    Преобразует логистический граф в направленный.

    Учитывает:
    - направления маршрутов;
    - корректность расстояний;
    - несколько связей между объектами.
    """

    directed = nx.DiGraph()
    directed.add_nodes_from(graph.nodes(data=True))

    for u, v, data in graph.edges(data=True):

        a = data.get("node_a", u)
        b = data.get("node_b", v)

        directions = [
            (a, b, "route_status_ab", "total_distance_ab_m"),
            (b, a, "route_status_ba", "total_distance_ba_m"),
        ]

        for source, target, status_key, distance_key in directions:

            if data.get(status_key) != "found":
                continue

            try:
                distance = float(data.get(distance_key))
            except (TypeError, ValueError, OverflowError):
                continue

            if not math.isfinite(distance) or distance <= 0:
                continue

            if source not in directed or target not in directed:
                continue

            if (
                not directed.has_edge(source, target)
                or distance < directed[source][target]["weight"]
            ):
                directed.add_edge(
                    source,
                    target,
                    weight=distance
                )

    return directed

def calculate_reachability(graph: nx.DiGraph) -> dict:
    """
    Рассчитывает количество достижимых объектов
    для каждой вершины направленного графа.
    """

    reachability = {}

    for node in graph.nodes:
        reachable_nodes = nx.descendants(graph, node)
        reachability[node] = len(reachable_nodes)

    return reachability

def calculate_average_distance(graph: nx.DiGraph) -> dict:
    """
    Рассчитывает среднюю длину кратчайшего пути
    от каждого логистического объекта до достижимых объектов.

    Расстояния измеряются в метрах.
    Если другие объекты недостижимы, возвращает None.
    """

    average_distances = {}

    for node in graph.nodes:

        # Кратчайшие расстояния до всех достижимых объектов
        distances = nx.single_source_dijkstra_path_length(
            graph,
            source=node,
            weight="weight"
        )

        # Исключаем расстояние от вершины до самой себя
        distances.pop(node, None)

        if distances:
            average_distances[node] = sum(distances.values()) / len(distances)
        else:
            average_distances[node] = None

    return average_distances

def calculate_weighted_closeness(graph: nx.DiGraph) -> dict:
    """
    Рассчитывает взвешенную Closeness Centrality
    по исходящим маршрутам.

    Учитывает:
    - длину кратчайших путей;
    - направления движения;
    - недостижимые объекты.

    Вес маршрута измеряется в метрах.
    Для удобства расстояния переводятся в километры.
    """

    closeness = {}
    n = graph.number_of_nodes()

    for node in graph.nodes:

        distances = nx.single_source_dijkstra_path_length(
            graph,
            source=node,
            weight="weight"
        )

        distances.pop(node, None)

        reachable = len(distances)

        if reachable == 0 or n <= 1:
            closeness[node] = 0.0
            continue

        total_distance_km = sum(distances.values()) / 1000

        if total_distance_km <= 0:
            closeness[node] = 0.0
            continue

        # Поправка на недостижимые вершины
        value = (
            reachable / total_distance_km
        ) * (
            reachable / (n - 1)
        )

        closeness[node] = round(value, 4)

    return closeness

def calculate_metrics_report(graph: nx.Graph) -> dict:
    """
    Формирует общий отчёт по логистическому графу
    и метрики каждого логистического объекта.
    """

    directed = to_directed_graph(graph)

    reachability = calculate_reachability(directed)
    average_distances = calculate_average_distance(directed)
    closeness = calculate_weighted_closeness(directed)

    # Уникальные пары объектов с корректным маршрутом
    connected_pairs = {
        frozenset((u, v))
        for u, v in directed.edges()
    }

    graph_metrics = {
        "node_count": directed.number_of_nodes(),
        "edge_count": len(connected_pairs),
        "directed_route_count": directed.number_of_edges(),
        "component_count": nx.number_weakly_connected_components(directed),
    }

    node_metrics = {}

    for node in directed.nodes:
        node_metrics[str(node)] = {
            "reachable_count": reachability[node],
            "average_distance_m": average_distances[node],
            "weighted_closeness": closeness[node],
        }

    return {
        "graph_metrics": graph_metrics,
        "node_metrics": node_metrics,
    }