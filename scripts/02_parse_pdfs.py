"""阶段2：读取清单并分页解析，保存data/parsed，不调用API。"""
import argparse
import csv
from pathlib import Path
from _bootstrap import finish
from src.common.storage import DATA, read_json
from src.papers.pipeline import parse_pdfs, save_papers

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--paper-id', help='仅解析指定论文')
parser.add_argument('--paper-list', type=Path, help='导入经人工编辑的CSV元数据，按paper_id匹配现有记录')
parser.add_argument('--force', action='store_true')
args = parser.parse_args()
if args.paper_list:
    updates = {row['paper_id']: row for row in csv.DictReader(args.paper_list.open(encoding='utf-8-sig'))}
    papers = read_json(DATA / 'papers.json', [])
    for paper in papers:
        for key, value in updates.get(paper['paper_id'], {}).items():
            if key in {'title','authors','year','venue','doi_or_arxiv','url','topic_tags','inclusion_reason','status'}:
                paper[key] = value
    save_papers(papers)
finish(parse_pdfs, paper_id=args.paper_id, force=args.force)
