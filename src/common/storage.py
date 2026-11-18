"""阶段文件存取：原子写入防止长任务中断时留下半个 JSON。"""
from __future__ import annotations
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env', override=False)
DATA = Path(os.getenv('KG3DR_DATA_DIR', str(ROOT / 'data'))).resolve()
EXP = Path(os.getenv('KG3DR_EXPERIMENT_DIR', str(ROOT / 'experiments'))).resolve()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: Any) -> str:
    """对结构化数据生成稳定版本；不依赖字典插入顺序。"""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read_json(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def stable_id(kind: str, name: str) -> str:
    normalized = ' '.join(name.casefold().split())
    return kind.lower() + '_' + hashlib.sha256(normalized.encode()).hexdigest()[:16]


def manifest(stage: str, inputs: Any, outputs: Any) -> None:
    write_json(DATA / 'manifests' / f'{stage}.json', {
        'stage': stage, 'time': now(), 'input_version': digest(inputs), 'outputs': outputs,
    })
