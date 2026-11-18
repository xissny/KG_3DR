"""阶段5：将已审核图谱幂等导入Neo4j，事务成功后保存实验快照。"""
import argparse
from _bootstrap import finish
from src.graph.store import import_graph

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--approved-only', action='store_true', help='始终仅导入审核通过的事实；此参数用于显式说明')
parser.parse_args()
finish(import_graph)
