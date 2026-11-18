"""阶段6：标签草稿、分类留一评测或单篇演示。"""
import argparse
from _bootstrap import finish
from src.classification.task import evaluate_classification, classify_paper, label_draft
from src.graph.store import load_snapshot
from src.common.storage import DATA, write_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--mode', choices=['evaluate','predict','label-draft'], default='evaluate')
parser.add_argument('--paper-id')
args = parser.parse_args()
if args.mode == 'label-draft':
    path = DATA / 'labels.json'
    if path.exists():
        parser.error('labels.json已存在，不覆盖人工标签')
    write_json(path, label_draft(load_snapshot()))
    print('已生成标签草稿，请人工核对完整任务集合并填写verified和reviewer。')
elif args.mode == 'predict':
    if not args.paper_id:
        parser.error('predict需要--paper-id')
    finish(classify_paper, paper_id=args.paper_id)
else:
    finish(evaluate_classification)
