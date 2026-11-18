"""阶段8：图谱问答或固定题目评测；需Neo4j和DeepSeek密钥。"""
import argparse
from _bootstrap import finish
from src.generation.task import answer_question, evaluate_generation

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--question')
parser.add_argument('--evaluate', action='store_true')
parser.add_argument('--force', action='store_true')
parser.add_argument('--task-type', choices=['qa', 'summary', 'review'], default='qa')
parser.add_argument('--entity-ids', nargs='+')
parser.add_argument('--paper-ids', nargs='+')
args = parser.parse_args()
if args.evaluate:
    finish(evaluate_generation)
elif args.question or args.task_type != 'qa':
    finish(answer_question, question=args.question or '', force=args.force, task_type=args.task_type, entity_ids=args.entity_ids, paper_ids=args.paper_ids)
else:
    parser.error('问答需要--question；总结/综述使用--task-type和--paper-ids；批量评测使用--evaluate')
