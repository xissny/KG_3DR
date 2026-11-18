"""阶段3：使用DeepSeek抽取候选事实，完成块被缓存，失败可重跑。"""
import argparse
from _bootstrap import finish
from src.extraction.pipeline import extract_papers

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--paper-id', help='仅抽取指定论文，建议先选3篇试抽取')
parser.add_argument('--force', action='store_true', help='忽略API缓存，可能产生额外费用')
args = parser.parse_args()
finish(extract_papers, paper_id=args.paper_id, force=args.force,
       progress=lambda message,*_: print(message, flush=True))
