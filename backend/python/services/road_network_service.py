import sys
import os

_src_dir = os.path.join(os.path.dirname(__file__), "..", "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from graph_service.algorithms.road_network_service import RoadNetworkService

__all__ = ["RoadNetworkService"]
