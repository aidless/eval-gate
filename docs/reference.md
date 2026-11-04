# 参考手册

## 命令

### `eval-gate run`

```bash
eval-gate run \
  --dataset dataset.jsonl \
  --predictions candidate.jsonl \
  --baseline-predictions baseline.jsonl \
  --out runs/pr-1
```

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--dataset` | 必填 | 评测集，JSONL，每题一行 |
| `--predictions` | 必填 | 候选逐题结果，JSONL |
| `--baseline-predictions` | 必填 | 基线逐题结果，JSONL，必须与候选同 id |
| `--out` | 必填 | 输出目录（`run.json` / `verdict.json` / `attribution.md` / `evidence/`） |
| `--tools` | 无 | 当前 MCP 工具清单；提供才启用 `input_guard` |
| `--tool-snapshot` | 无 | 上一次的工具 digest + 定义；没有快照只能报 `new` |
| `--changed-files` | `[]` | 写进归因表的改动文件列表 |
| `--head-sha` | `unknown` | 上游 commit，写进 `run.json` 与 run_id |
| `--run-id` | 自动 | 默认 `pr-<head7>-<dataset8>-<pred8>` |
| `--min-pass` | `0.80` | G1 绝对下限（比例，不是百分点） |
| `--max-regression` | `0.03` | G2 容差：回退要**置信地超过**它才 BLOCK |
| `--min-n` | `400` | G5 最小样本量 |
| `--alpha` | `0.05` | 显著性水平（只支持双侧） |
| `--iterations` | `10000` | bootstrap 次数，最低 100 |
| `--seed` | `20261103` | 固定 seed，保证跨机可复现 |
| `--max-ci-width` | `0.12` | G5 区间宽度上限（绝对 CI 与 delta CI 都要满足） |
| `--min-overlap` | `0.80` | 候选/基线 id 重叠下限，低于则 G2 不可比 |
| `--ci-method` | `auto` | `auto` / `bootstrap` / `normal`；`auto` 在 `iterations × n > 20,000,000` 时改用分层正态近似 |
| `--alpha-adjust` | `none` | `none`：逐检验 95%；`bonferroni`：两个统计 gate 分摊 α（0.05 → 0.025） |
| `--fail-on` | `block` | `block` / `review` / `never` |
| `--github-output` | 无 | 追加 GitHub Actions 变量（`verdict`、`pass-rate`、`delta` 等） |
| `--json` | 关 | 额外打印完整 verdict JSON |
| `--rubric` | 无 | 预留；MVP 只支持内置 rubric，传了会 warning |

### `eval-gate verify`

```bash
eval-gate verify --run-dir runs/pr-1
```

只读 `run.json + evidence/` 重算，不重新读取原始 dataset/predictions。以下任一情况都不会给 `PASS`：

- 必需证据缺失（`INCOMPLETE`）
- sha256 与 `evidence_manifest` 不符（`INCOMPLETE`）
- 存储的 `verdict.json` 与重算结果不一致（`INCOMPLETE`）
- `rules_version` / `schema_version` 不一致（`INCOMPLETE`）
- 上一次判决是 `BLOCK` 时，删证据不会把结论降级（G9）

### `eval-gate demo` / `eval-gate quickstart`

```bash
eval-gate demo        # 10 个场景，核对 scenario.json 里的 expected
eval-gate quickstart  # 4 个核心场景，约 1–2 秒
```

`demo` 在任何一个场景与 `expected` 不符时退出码为 1，并打印 `MISMATCH`。

## 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 判决为 `PASS`，或 `REVIEW` 且未启用 `--fail-on review` |
| `1` | 判决为 `BLOCK` / `FAIL` / `INCOMPLETE`（`--fail-on block`，默认）；`--fail-on review` 下 `REVIEW` 也返回 1 |
| `2` | 输入错误（`EvalGateError`）：缺文件、坏 JSON、字段类型错、config 非法、pass@k 不一致等 |

`--fail-on never` 恒返回 0，只用于观察模式。

错误一律打印两行，而不是 traceback：

```
error: <哪里错了>
next:  <下一步做什么>
```

## 判决语义

优先级：`BLOCK > INCOMPLETE > FAIL > REVIEW > PASS`。

| 判决 | 统计/规则依据 | 典型触发 |
|---|---|---|
| `PASS` | G1 Wilson 下限 ≥ `min_pass`；G2 无显著回退；G3/G4 无告警 | 全部达标且有足够功效 |
| `REVIEW` | G5 功效不足，或 G8/G10 可比性不足 | `n < min_n`、CI 宽 > `max_ci_width`、重叠 < `min_overlap`、`scorer_version` 不一致 |
| `FAIL` | G1 下限 < `min_pass`，但相对基线没变差 | 绝对水平不达标 |
| `INCOMPLETE` | G6 证据缺失/损坏/版本不一致 | `verify` 发现删证据、改字节、schema 版本不符 |
| `BLOCK` | G2 回退置信超过容差，或 G3 安全回退，或 G4 工具漂移 | 相对基线坏了 |

`FAIL` 与 `BLOCK` 刻意分开：前者修“本身不达标”，后者修“这次改动弄坏了它”。

### Gate 一览

| Gate | 规则 |
|---|---|
| `G1-absolute` | Wilson 下限 ≥ `min_pass`，否则 FAIL |
| `G2-regression` | delta CI **上限** ≤ `-max_regression` 才 BLOCK（置信地超过容差） |
| `G3-safety` | 候选 L1 硬失败数 > 基线 → BLOCK |
| `G4-tool-drift` | 工具 digest/定义漂移且命中内容变化 → BLOCK |
| `G5-power` | `n ≥ min_n` 且绝对 CI 宽、delta CI 宽 ≤ `max_ci_width`；不满足时把统计类 `PASS/FAIL/BLOCK` 压成 `REVIEW` |
| `G6-evidence` | 必需证据层缺失 → INCOMPLETE |
| `G7-stability` | 离线模式不抽样重跑，标记 `skipped`（见 FAILURE_MODES FM-07） |
| `G8-comparable` | 数据集重叠 ≥ `min_overlap`，否则 REVIEW 且 G2 不可比 |
| `G9-no-downgrade` | 上一次判决更严重时，删证据不得降级 |
| `G10-scorer` | `scorer_version` 不一致 → G2 不可比、REVIEW |

### `flags`

`flags` 只做边界披露，**不改变判决**：

| flag | 含义 |
|---|---|
| `mde_exceeds_tolerance` | 当前样本量能可靠检测的最小效应 > `max_regression`：检验对“小回退”没有功效 |
| `ci_method:normal` | 实际用了正态近似而非 bootstrap |
| `single_family_no_stratification` | 只有一个 family，分层 bootstrap 退化为整体重采样 |
| `scorer_changed` | 候选与基线的 `scorer_version` 不一致 |
| `alpha_adjust:bonferroni` | 已启用多重比较校正 |
| `threshold_edge:G1` / `threshold_edge:G2` | 结论成立，但离阈值 < 0.2pp |

## 输入契约

### dataset.jsonl

```json
{"id": "q-001", "family": "billing", "input": "怎么退款？", "reference": "……",
 "answerable": true, "must_include": ["退款"], "forbidden_promises": ["立即到账"]}
```

- `id` 必须唯一；`input` 去空白、转小写后不得与其他题完全相同（防重复题虚增 `n`）。
- `answerable=false` 的题要求答案含拒答标记，否则 `L1.must_refuse` 失败。

### predictions.jsonl（两种模式）

内置 rubric 模式（候选缺 `pass` 字段）：

```json
{"id": "q-001", "output": "……", "claims": [{"text": "…", "supported": true}], "spans": ["doc-1"]}
```

外部判分器模式（预测含严格布尔 `pass`）：

```json
{"id": "M-01-001", "pass": true, "k": 1, "scorer_version": "judge-v2",
 "l1_failures": [], "naive_pass": true, "dimensions": {"complete": 2}, "output": "答案正确"}
```

- `pass` 必须是 `true/false`，字符串 `"false"` 会被拒绝。
- `k` 用于 pass@k；候选与基线必须同 `k`（或都不写）。
- `scorer_version` 两边都写时必须相同，否则 G10 → REVIEW。

## 产物

| 文件 | 内容 |
|---|---|
| `verdict.json` | 判决、`flags`、主指标与 delta 的 95% CI、MDE、逐 gate 结果、`metrics` |
| `run.json` | 输入 sha256、证据清单、`rules_version`、`scorer_version`、工具 digest、layers、config |
| `attribution.md` | 回退题 Top、失败层、naive/权威落差、疑似原因、改动文件 |
| `evidence/per_item.jsonl` | 候选逐题评分（判决重算的唯一依据） |
| `evidence/baseline_per_item.jsonl` | 基线逐题评分 |
| `evidence/summary.json` | 通过数/naive 通过数/多余预测数 |
| `evidence/tools.json` | 工具扫描结果（提供 `--tools` 时） |

## Public API（冻结）

`v0.2.0` 起冻结以下接口。破坏性改动会升 minor 并在 CHANGELOG 说明；
标为 internal 的不保证兼容。

### 稳定接口

| 接口 | 说明 |
|---|---|
| CLI：`run` / `verify` / `demo` / `quickstart` 及上表参数 | 参数名、默认值、退出码 |
| `eval_gate.runner.run_gate(...)` | 见下 |
| `eval_gate.runner.verify_run(run_dir, *, prior_config=None)` | 返回 `{"problems": list[str], "verdict": dict}` |
| `eval_gate.errors.EvalGateError` | 字段 `problem` / `hint` / `where`，方法 `render()` |
| `verdict.json` / `run.json` / `evidence/*` 的字段 | `schema_version: "1.0.0"` |

`run_gate` 的稳定签名：

```python
run_gate(
    *,
    dataset_path: str | Path,
    predictions_path: str | Path,
    baseline_predictions_path: str | Path,
    out_dir: str | Path,
    tools_path: str | Path | None = None,
    tool_snapshot_path: str | Path | None = None,
    changed_files: list[str] | None = None,
    head_sha: str = "unknown",
    config: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]   # {"run_dir": str, "run_id": str, "verdict": dict}
```

```python
from eval_gate.runner import run_gate, verify_run

result = run_gate(dataset_path="dataset.jsonl",
                  predictions_path="candidate.jsonl",
                  baseline_predictions_path="baseline.jsonl",
                  out_dir="runs/pr-1")
print(result["verdict"]["verdict"])

print(verify_run("runs/pr-1")["verdict"]["verdict"])
```

### 内部实现（不保证兼容）

- `eval_gate.gate`（`evaluate`、`DEFAULT_CONFIG`、`GATE_RULES`）
- `eval_gate.stats`（`paired_bootstrap_delta`、`wilson_interval` 等）
- `eval_gate.rubric`（`score_records`、`score_item`、`RUBRIC`）
- `eval_gate.contract` / `eval_gate.schema` / `eval_gate.tools` / `eval_gate.attribution`
- 所有以下划线开头的函数与字段

这些模块供测试与本仓库内部使用；外部调用请以 CLI 或 `run_gate` / `verify_run` 为入口。
`py.typed` 已随包分发，public API 通过 mypy strict。

## 复现与性能

- 默认 `seed=20261103`，MT19937 + 固定浮点累加顺序，3.9–3.12 的 golden 值逐位一致。
- 10 万题、默认配置：`scripts/bench_100k.py` 两次实测 `0.95s` / `1.02s`（`ci_method=normal`，`iterations=0`）。
- 480 题、10,000 次 bootstrap：单次 `run` 约 `1.2s`（含进程启动）；`quickstart` 4 场景（2,000 次）本机 `1.1–2.4s`。
