import networkx as nx

graph = nx.MultiGraph()

# Логистические объекты
graph.add_node("A", name="Склад A", object_type="warehouse")
graph.add_node("B", name="Терминал B", object_type="terminal")
graph.add_node("C", name="Порт C", object_type="port")
graph.add_node("D", name="Склад D", object_type="warehouse")

# Двусторонняя связь A <-> B
graph.add_edge(
    "A", "B",
    key="road",
    node_a="A",
    node_b="B",
    transport_mode="road",
    route_status_ab="found",
    route_status_ba="found",
    total_distance_ab_m=1500.0,
    total_distance_ba_m=1700.0,
)

# Односторонняя связь B -> C
graph.add_edge(
    "B", "C",
    key="road",
    node_a="B",
    node_b="C",
    transport_mode="road",
    route_status_ab="found",
    route_status_ba="not_found_in_data",
    total_distance_ab_m=2300.0,
    total_distance_ba_m="",
)

# Сохраняем граф в GraphML
nx.write_graphml(graph, "data/test_metrics.graphml")

print("Тестовый граф успешно сохранён!")
print("Вершин:", graph.number_of_nodes())
print("Рёбер:", graph.number_of_edges())