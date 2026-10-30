"""
Entry point for the Graph Service.
Supports running via CLI or as a background service.
"""
import sys
import os

# Ensure src is in python path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from graph_service.application.build_graph import BuildGraphUseCase
from graph_service.domain.models import AnalysisRequest


def main():
    print("[*] Graph Service starting...")
    # Reserved for Kafka consumer startup when running in service mode
    print("[+] Graph Service initialized.")


if __name__ == "__main__":
    main()
