import sys
import os

_src_dir = os.path.join(os.path.dirname(__file__), "..", "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from graph_service.adapters.osm_client import execute_with_overpass_fallback, OVERPASS_MIRRORS

__all__ = ["execute_with_overpass_fallback", "OVERPASS_MIRRORS"]
