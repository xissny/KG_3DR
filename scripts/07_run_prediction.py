"""阶段7：分组遮蔽关系评测，或生成待审核组件建议。"""
import argparse
from _bootstrap import finish
from src.prediction.task import evaluate_prediction, predict_method

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--mode', choices=['evaluate','predict'], default='evaluate')
parser.add_argument('--method-id')
args = parser.parse_args()
if args.mode == 'predict':
    if not args.method_id:
        parser.error('predict需要--method-id')
    finish(predict_method, method_id=args.method_id)
else:
    finish(evaluate_prediction)
