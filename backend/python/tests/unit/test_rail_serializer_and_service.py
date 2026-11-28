import pytest
from unittest.mock import patch
import networkx as nx

from graph_service.config import config
from shapely.geometry import LineString

from graph_service.domain.models import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    TerritoryBounds,
    TerritorySourceType,
    TransportMode,
    RailObjectType,
    RailNodeKind,
    RailConnectionStatus,
)
from graph_service.application.build_graph import TerritoryAnalysisService
from graph_service.application.graph_serializer import GraphSerializer
from graph_service.application.rail_metrics_service import RailMetricsService
from graph_service.application.cancellation import CancellationToken, TaskCancelledException
from graph_service.kafka.schemas import GraphPayload


def test_rail_graph_serializer_nodes_and_edges():
    """
    Проверяет корректность сериализации ЖД-графа в GraphPayload:
    - У вершин присутствуют object_type, node_kind, is_switch, coordinates [lon, lat].
    - У рёбер присутствуют segment_id, length_m, transport_mode='rail'.
    - СТРОГО: поле 'edge_type' отсутствует у ЖД-рёбер.
    """
    g = nx.MultiDiGraph()
    g.graph["transport_mode"] = "rail"

    g.add_node(
        "station_1",
        x=30.40,
        y=59.80,
        object_type=RailObjectType.RAIL_FACILITY.value,
        node_kind=RailNodeKind.STATION.value,
        name="Шушары",
        facility_id="station:123",
        connection_status=RailConnectionStatus.CONNECTED.value,
    )
    g.add_node(
        "switch_1",
        x=30.41,
        y=59.81,
        object_type=RailObjectType.RAIL_NODE.value,
        node_kind=RailNodeKind.SWITCH.value,
        is_switch=True,
    )

    g.add_edge(
        "station_1",
        "switch_1",
        key="seg_0:forward",
        id="rail_0_fwd",
        segment_id="segment:0",
        length_m=1250.5,
        geometry=LineString([(30.40, 59.80), (30.41, 59.81)]),
    )
    g.add_edge(
        "switch_1",
        "station_1",
        key="seg_0:backward",
        id="rail_0_bwd",
        segment_id="segment:0",
        length_m=1250.5,
        geometry=LineString([(30.41, 59.81), (30.40, 59.80)]),
    )

    payload = GraphSerializer.serialize(g)
    assert isinstance(payload, GraphPayload)
    assert len(payload.nodes) == 2
    assert len(payload.edges) == 2

    node_dict = {n.id: n for n in payload.nodes}
    st_node = node_dict["station_1"]
    assert st_node.position == [30.40, 59.80]
    assert st_node.attributes["object_type"] == "rail_facility"
    assert st_node.attributes["node_kind"] == "station"
    assert st_node.attributes["name"] == "Шушары"
    assert st_node.attributes["facility_id"] == "station:123"
    assert st_node.attributes["connection_status"] == "connected"

    sw_node = node_dict["switch_1"]
    assert sw_node.position == [30.41, 59.81]
    assert sw_node.attributes["object_type"] == "rail_node"
    assert sw_node.attributes["node_kind"] == "switch"
    assert sw_node.attributes["is_switch"] is True

    # Проверка рёбер: общий segment_id, длина, transport_mode, отсутствие edge_type
    for edge in payload.edges:
        assert edge.segment_id == "segment:0"
        assert edge.attributes["transport_mode"] == "rail"
        assert edge.attributes["length_m"] == 1250.5
        assert "edge_type" not in edge.attributes
        assert len(edge.geometry) == 2


def test_territory_analysis_service_rail_shushary():
    """
    Проверяет полный прогон анализа ЖД-сети через TerritoryAnalysisService на фикстуре Шушар.
    """
    service = TerritoryAnalysisService(default_storage_dir="data")
    bbox = TerritoryBounds(
        min_lon=30.385,
        min_lat=59.795,
        max_lon=30.441,
        max_lat=59.824,
    )
    req = AnalysisRequest(
        territory_type=TerritorySourceType.BBOX.value,
        bbox=bbox,
        transport_mode=TransportMode.RAIL.value,
        save_artifacts=False,
    )

    with patch.object(config, "osm_offline_mode", True):
        resp = service.run_analysis(req)
    assert resp.status == AnalysisStatus.SUCCESS.value
    assert resp.summary["total_rail_nodes"] == 86
    assert resp.summary["total_physical_segments"] == 90
    assert resp.summary["total_directed_edges"] == 180
    assert resp.summary["station_candidates_count"] == 2
    assert resp.summary["switch_count"] == 36

    # Проверяем сериализацию графа (86 путевых узлов + 2 станции-кандидата = 88 вершин)
    payload = GraphSerializer.serialize(resp.graph_object)
    assert len(payload.nodes) == 88
    assert len([n for n in payload.nodes if not n.id.startswith("station:")]) == 86
    assert len([n for n in payload.nodes if n.id.startswith("station:")]) == 2
    assert len(payload.edges) == 180

    # Проверяем расчет метрик
    metrics = RailMetricsService.calculate_metrics(
        graph=resp.physical_graph,
        facilities=resp.facilities,
        routing_graph=resp.graph_object,
    )
    metrics_map = {m.name: m.value for m in metrics if m.node_id is None}
    assert metrics_map["total_rail_length_km"] == pytest.approx(25.750071, abs=1e-4)
    assert metrics_map["switch_count"] == 36.0
    assert metrics_map["station_count"] == 0.0  # без подтвержденных якорей


def test_territory_analysis_service_rail_cancellation():
    """
    Проверяет отмену ЖД-анализа через CancellationToken.
    """
    service = TerritoryAnalysisService(default_storage_dir="data")
    bbox = TerritoryBounds(
        min_lon=30.385,
        min_lat=59.795,
        max_lon=30.441,
        max_lat=59.824,
    )
    req = AnalysisRequest(
        territory_type=TerritorySourceType.BBOX.value,
        bbox=bbox,
        transport_mode=TransportMode.RAIL.value,
        save_artifacts=False,
    )

    token = CancellationToken()
    token.cancel()

    with pytest.raises(TaskCancelledException):
        service.run_analysis(req, cancellation_token=token)
