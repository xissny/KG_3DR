"""只读检查重复三元组；不同证据保留，网页候选视图自动聚合，不改写审核数据。"""
import argparse
from _bootstrap import finish
from src.review.service import grouped_candidates


def inspect():
    groups = grouped_candidates()
    duplicates = [group for group in groups if len(group['rows']) > 1]
    return {
        'unique_triples': len(groups),
        'evidence_records': sum(len(group['rows']) for group in groups),
        'multi_evidence_groups': len(duplicates),
        'groups': [{'subject': group['subject']['name'], 'relation': group['relation'],
                    'object': group['object']['name'], 'evidence_count': len(group['rows']),
                    'evidence_ids': [row['id'] for row in group['rows']]} for group in duplicates],
        'note': '多条引文不是多个事实。候选列表和候选图聚合显示，底层证据与审核历史不删除。',
    }

parser = argparse.ArgumentParser(description=__doc__)
parser.parse_args()
finish(inspect)
