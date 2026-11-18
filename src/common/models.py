"""本体与结构校验。合法三元组仍需人工判断是否被原文支持。"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from src.common.storage import stable_id

EntityType = Literal['Paper', 'Method', 'Component', 'Task', 'Representation', 'Dataset', 'Metric']
Relation = Literal['PROPOSES', 'USES_COMPONENT', 'SOLVES', 'OUTPUTS', 'TRAINED_ON', 'EVALUATED_ON', 'USES_METRIC', 'CITES']
# 用类型约束区分合法关系，特别是训练/测试数据，不把所有关联都记为 RELATED_TO。
RELATION_TYPES = {
    'PROPOSES': ({'Paper'}, {'Method'}),
    'USES_COMPONENT': ({'Method'}, {'Component'}),
    'SOLVES': ({'Paper', 'Method'}, {'Task'}),
    'OUTPUTS': ({'Method'}, {'Representation'}),
    'TRAINED_ON': ({'Method'}, {'Dataset'}),
    'EVALUATED_ON': ({'Paper', 'Method'}, {'Dataset'}),
    'USES_METRIC': ({'Paper', 'Method'}, {'Metric'}),
    'CITES': ({'Paper'}, {'Paper'}),
}

class Entity(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: EntityType
    name: str = Field(min_length=1, max_length=300)

    @property
    def id(self) -> str:
        return stable_id(self.type, self.name)

class Candidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    subject: Entity
    relation: Relation
    object: Entity
    quote: str = Field(min_length=12)
    page: int = Field(ge=1)

    @model_validator(mode='after')
    def check_relation_types(self):
        source_types, target_types = RELATION_TYPES[self.relation]
        if self.subject.type not in source_types or self.object.type not in target_types:
            raise ValueError('实体类型不符合关系定义')
        return self

class ExtractionResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    facts: list[Candidate]

class ReviewUpdate(BaseModel):
    status: Literal['approved', 'rejected', 'pending']
    reviewer: str = Field(min_length=1)
    note: str = ''
    candidate: Candidate | None = None
