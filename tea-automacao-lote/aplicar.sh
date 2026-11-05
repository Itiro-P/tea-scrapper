#!/usr/bin/env bash
set -euo pipefail
tea_package_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
python3 "$tea_package_dir/aplicar.py" --package "$tea_package_dir"
