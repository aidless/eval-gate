#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v eval-gate >/dev/null || { echo "先安装：python3 -m pip install ../.."; exit 2; }
set +e
eval-gate run \
  --dataset ../../eval_gate/demo_data/dataset.jsonl \
  --predictions predictions.jsonl \
  --baseline-predictions baseline_predictions.jsonl \
  --tools tools.candidate.json \
  --tool-snapshot tools.snapshot.json \
  --changed-files tools/lookup_order.json \
  --out runs/tool-drift
code=$?
set -e
echo "exit=$code（1 表示 BLOCK，符合预期）"
