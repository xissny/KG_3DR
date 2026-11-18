"""阶段4：导入人工审核表或导出候选，校验后形成正式快照。"""
import argparse
from pathlib import Path
from _bootstrap import finish
from src.common.models import ReviewUpdate
from src.common.storage import read_json, write_json
from src.review.service import all_candidates, update_review, validate_facts

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--export-review', type=Path, help='导出审核JSON，编辑status/reviewer/note/candidate后用--review-file导入')
parser.add_argument('--review-file', type=Path)
args = parser.parse_args()
if args.export_review:
    write_json(args.export_review, all_candidates())
    print('已导出审核表；人工核对后再导入。')
elif args.review_file:
    for row in read_json(args.review_file, []):
        update_review(row['id'], ReviewUpdate.model_validate({k: row[k] for k in ['status','reviewer','note','candidate']}))
    finish(validate_facts)
else:
    finish(validate_facts)
