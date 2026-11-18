"""使直接运行 scripts/xx.py 时也能导入项目模块。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json


def finish(function, **kwargs):
    try:
        result = function(**kwargs)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f'阶段失败：{exc}', file=sys.stderr)
        sys.exit(1)
