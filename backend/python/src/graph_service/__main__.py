"""
Standard Python package entrypoint (PEP 338).
Invoked when executing: python -m graph_service
"""
import sys
import os

# Ensure src is in python path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from graph_service.kafka.worker import run_worker_cli


if __name__ == "__main__":
    run_worker_cli()

