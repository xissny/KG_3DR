#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"
exec "$project_root/.conda/kg3dr/bin/python" setup/services.py start
