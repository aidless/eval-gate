"""20 次重跑示例仓，断言 5 个场景判决完全一致（零 flake）。

只比较判决签名，不比较 created_utc——时间戳本来就应该变。
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNS = 20


def main() -> int:
    signatures = []
    with tempfile.TemporaryDirectory() as tmp:
        for index in range(1, RUNS + 1):
            out = pathlib.Path(tmp) / f"run-{index:02d}"
            proc = subprocess.run(
                [sys.executable, "-m", "eval_gate.cli", "demo",
                 "--fixtures", str(ROOT / "fixtures"), "--out", str(out),
                 "--iterations", "10000"],
                cwd=ROOT, capture_output=True, text=True)
            if proc.returncode != 0:
                print(proc.stdout)
                print(proc.stderr, file=sys.stderr)
                print(f"第 {index} 次重跑失败（退出码 {proc.returncode}）")
                return 1
            rows = re.findall(r"^\[(.+?)\] expected=(\w+) actual=(\w+)", proc.stdout, re.M)
            if len(rows) != 5:
                print(f"第 {index} 次重跑只解析到 {len(rows)} 个场景")
                return 1
            signatures.append(tuple((name, actual) for name, _, actual in rows))
            print(f"run {index:02d}: " + " ".join(
                f"{name}={actual}" for name, _, actual in rows))

    unique = set(signatures)
    print(f"\n{RUNS} 次重跑，{len(unique)} 种判决签名")
    if len(unique) != 1:
        print("FLake：判决不一致", unique)
        return 1
    print("零 flake：5/5 场景每次判决一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
