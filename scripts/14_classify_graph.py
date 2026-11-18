"""图谱自动分类：无需人工标签，可选按论文运行或更新类别体系。"""
import argparse
from _bootstrap import finish
from src.classification.automatic import run_automatic_classification, update_taxonomy

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--paper-id', action='append', help='可重复指定；省略则分类全部已纳入图谱的论文')
parser.add_argument('--force', action='store_true', help='重新请求模型，不复用已有结果')
parser.add_argument('--update-taxonomy', action='store_true', help='显式重新整理类别体系')
args = parser.parse_args()
if args.update_taxonomy:
    finish(update_taxonomy)
else:
    finish(run_automatic_classification, paper_ids=args.paper_id, force=args.force)
