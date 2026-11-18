"""三元组身份与引文身份分离：同一事实可以有多篇论文、多页证据。"""
from __future__ import annotations
import unicodedata
from src.common.storage import digest


def normalized_name(name: str) -> str:
    """只统一字符宽度、大小写和空白；不做可能误合并实体的模糊匹配。"""
    return ' '.join(unicodedata.normalize('NFKC', name).split()).casefold()


def canonical_name(kind: str, name: str, aliases: dict[str, str]) -> str:
    """按类型解析人工别名，可处理别名链，循环或冲突映射明确报错。"""
    lookup = {}
    for key, value in aliases.items():
        entity_type, separator, alias = key.partition(':')
        if separator and entity_type == kind:
            key_normalized = normalized_name(alias)
            previous = lookup.get(key_normalized)
            if previous is not None and normalized_name(previous) != normalized_name(value):
                raise ValueError(f'别名存在冲突：{kind}:{alias}')
            lookup[key_normalized] = value
    current = ' '.join(unicodedata.normalize('NFKC', name).split())
    seen = set()
    while normalized_name(current) in lookup:
        identity = normalized_name(current)
        if identity in seen:
            raise ValueError(f'别名存在循环：{kind}:{name}')
        seen.add(identity)
        target = ' '.join(unicodedata.normalize('NFKC', lookup[identity]).split())
        if normalized_name(target) == identity:
            return target
        current = target
    return current


def triple_key(candidate: dict, aliases: dict[str, str]) -> tuple[str, str, str, str, str]:
    """主体类型/标准名、关系、客体类型/标准名共同决定事实身份。"""
    subject, obj = candidate['subject'], candidate['object']
    return (subject['type'], normalized_name(canonical_name(subject['type'], subject['name'], aliases)),
            candidate['relation'], obj['type'], normalized_name(canonical_name(obj['type'], obj['name'], aliases)))


def evidence_key(pdf_sha256: str, candidate: dict, aliases: dict[str, str]) -> str:
    """同页、同引文才是重复证据；不同页或不同原文仍独立保留、独立审核。"""
    quote = ''.join(unicodedata.normalize('NFKC', candidate['quote']).split()).casefold()
    return digest([pdf_sha256, triple_key(candidate, aliases), candidate['page'], quote])
