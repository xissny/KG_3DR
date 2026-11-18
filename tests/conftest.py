"""每例使用独立目录，测试绝不覆盖正式data与experiments。"""
import os
from pathlib import Path
import shutil
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

@pytest.fixture
def workspace(tmp_path,monkeypatch):
    from src.common import storage
    import src.papers.pipeline
    import src.extraction.pipeline
    import src.extraction.client
    import src.review.service
    import src.graph.store
    import src.classification.task
    import src.prediction.task
    import src.generation.task
    import backend.jobs
    import backend.app
    data=tmp_path/'data';exp=tmp_path/'experiments'
    source=ROOT/'examples/workspace/data'
    if source.exists():shutil.copytree(source,data)
    else:data.mkdir()
    exp.mkdir()
    for module_name,module in list(sys.modules.items()):
        if module_name.startswith(('src.','backend.')):
            if hasattr(module,'DATA'):monkeypatch.setattr(module,'DATA',data)
            if hasattr(module,'EXP'):monkeypatch.setattr(module,'EXP',exp)
    import src.papers.deletion
    monkeypatch.setattr(src.papers.deletion, 'OUTPUTS', tmp_path/'outputs')
    return data,exp
