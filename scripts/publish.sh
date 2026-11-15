#!/usr/bin/env bash
# 发布 eval-gate 到 PyPI（或 TestPyPI）。token 只从环境变量读，不落盘。
#
#   PYPI_TOKEN=pypi-...            ./scripts/publish.sh            # 正式
#   PYPI_TOKEN=pypi-... REPO=testpypi ./scripts/publish.sh          # TestPyPI 先演练
#   ./scripts/publish.sh --check                                    # 只构建 + 体检，不上传
#
# 退出码：0 成功；2 缺 token；3 体检失败；4 上传失败；5 上传后装不上。
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="${REPO:-pypi}"
MODE="${1:-upload}"

python3 - <<'PY'
import pathlib, shutil
for name in ("dist", "build"):
    p = pathlib.Path(name)
    if p.is_dir():
        shutil.rmtree(p)
PY
python3 -m build --sdist --wheel >/dev/null
python3 -m twine check dist/*

if [ "$MODE" = "--check" ]; then
  echo "体检通过（未上传）。"
  exit 0
fi

if [ -z "${PYPI_TOKEN:-}" ]; then
  echo "缺少 PYPI_TOKEN。到 https://pypi.org/manage/account/token/ 建一个 project-scoped token，" >&2
  echo "然后：PYPI_TOKEN=pypi-... $0${REPO:+ （REPO=testpypi 可先演练）}" >&2
  exit 2
fi

if [ "$REPO" = "testpypi" ]; then
  python3 -m twine upload --repository testpypi \
    --username __token__ --password "$PYPI_TOKEN" dist/*
  INDEX_ARGS="--index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/"
else
  python3 -m twine upload --username __token__ --password "$PYPI_TOKEN" dist/*
  INDEX_ARGS="--index-url https://pypi.org/simple/"
fi

# 上传不是成功判据：新环境里真装一次、真跑一次才算。
VERSION=$(python3 -c "import tomllib,pathlib;print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])")
TMP=$(mktemp -d)
python3 -m venv "$TMP/venv"
# PyPI 索引有传播延迟：刚上传完立刻装可能 404，重试三次再看。
for attempt in 1 2 3; do
  if "$TMP/venv/bin/pip" -q install $INDEX_ARGS "eval-verdict==$VERSION"; then break; fi
  if [ "$attempt" = 3 ]; then echo "装不上 eval-verdict==$VERSION（三次重试；本机 pip 走清华镜像时刚发的包可能还没同步）" >&2; exit 5; fi
  sleep 10
done
( cd "$TMP" && "$TMP/venv/bin/eval-gate" quickstart | tail -3 )
echo "已发布 eval-verdict $VERSION 到 $REPO，且在新 venv 里跑通 quickstart。"
echo "接着改三处文案：eval-gate/README.md（PyPI 段）、aidless/README.md（not on PyPI 列表）、发布包 §2 正文。"
