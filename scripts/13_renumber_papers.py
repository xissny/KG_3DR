"""修复旧清单中的空号，并同步解析、审核、API缓存与Neo4j；先备份，失败回滚。"""
import argparse
from _bootstrap import finish
from src.common.storage import DATA, read_json
from src.papers.numbering import contiguous_mapping, renumber_papers

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--yes',action='store_true',help='实际迁移；不加此项仅预览映射')
args=parser.parse_args()
if args.yes:
    finish(renumber_papers)
else:
    papers=read_json(DATA/'papers.json',[])
    print({old:new for old,new in contiguous_mapping(papers).items() if old!=new})
    print('仅预览。确认映射后加 --yes；已导入图谱时需Neo4j在线。')
