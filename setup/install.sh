#!/usr/bin/env bash
# 使用服务器已有Conda创建项目独立环境；不依赖当前激活的Python。
set -euo pipefail
project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"
if command -v conda >/dev/null 2>&1; then
  conda_base="$(conda info --base)"
else
  conda_base=/root/miniconda3
fi
"$conda_base/bin/python" setup/install.py "$@"
