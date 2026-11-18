"""删除指定论文及关联记录；先备份，保留其他论文共享事实。不会自动选中任何论文。"""
import argparse
from _bootstrap import finish
from src.papers.deletion import delete_paper
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--paper-id', required=True, help='要删除的论文ID，例如P001')
parser.add_argument('--yes', action='store_true', help='明确执行删除；不加时只显示说明')
args = parser.parse_args()
if args.yes:
    finish(delete_paper,paper_id=args.paper_id)
else:
    print(f'将删除 {args.paper_id} 的项目记录和关联证据；先建立本地备份。确认后加 --yes 运行。')
