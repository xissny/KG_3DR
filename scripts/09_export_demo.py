"""阶段9：导出可双击的HTML快照和图谱JSON/CSV/GraphML。"""
import argparse
from _bootstrap import finish
from src.graph.export import export_demo
parser = argparse.ArgumentParser(description=__doc__)
parser.parse_args()
finish(export_demo)
