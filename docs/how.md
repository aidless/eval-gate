# 怎么用：5 个真实评测场景

这 5 个场景都来自实际评测流水线里常见的形态：数学题的 pass@k、代码题的隐藏用例、RAG 的硬负例、
多轮工具调用的升级路径、LLM-as-judge 换版本。每个场景都随包提供可跑数据，并冻结了期望输出。

先跑一遍：

```bash
python3 -m pip install .
eval-gate demo          # 10 个场景，10/10 符合预期
```

下面每个场景都可以单独重跑。命令里 `D=eval_gate/demo_data/scenarios/<name>` 是场景目录，
`eval-gate` 与 `python3 -m eval_gate.cli` 等价。

## 全部 10 个场景的期望输出

`eval-gate demo` 会逐条核对下表的数字（`scenario.json` 里的 `expected`），任何一条不符就打印
`MISMATCH` 并以 1 退出。

| 场景 | 判决 | pass_rate | delta |
|---|---|---|---|
| `p1_pass` | `PASS` | 0.8917 | +0.0125 |
| `p2_regression` | `BLOCK` | 0.8063 | −0.0729 |
| `p3_false_green` | `FAIL` | 0.7917 | +0.0000 |
| `p4_tool_drift` | `BLOCK` | 0.8917 | +0.0125 |
| `p5_missing_evidence` | `INCOMPLETE` | 0.0000 | +0.0000 |
| `p6_math_passk` | 拒绝运行 | — | — |
| `p7_code_hidden` | `REVIEW` | 0.8000 | +0.0500 |
| `p8_rag_hard` | `FAIL` | 0.7458 | +0.0063 |
| `p9_tool_multiturn` | `BLOCK` | 0.9000 | +0.0187 |
| `p10_judge_calibration` | `REVIEW` | 0.8396 | −0.0500 |

`p5_missing_evidence` 是 `verify` 路径：先正常跑出 `PASS`，再删掉 `evidence/per_item.jsonl`，
重算应为 `INCOMPLETE`（`pass_rate` 因证据缺失显示为 0）。

下面展开的是 5 个真实评测场景（p6–p10）。

## 场景 1：数学题，候选 pass@1 vs 基线 pass@5（p6）

**旧比较会怎么骗人**：候选 59.5%（25/42）、基线 83.3%（35/42），按通过率看是“掉了 23.8 个点”，
实际是两边口径不同（pass@1 与 pass@5 不可比）。旧流程会直接判回退，把一个统计口径问题变成一次错误的回滚。

```bash
D=eval_gate/demo_data/scenarios/p6_math_passk
eval-gate run --dataset $D/dataset.jsonl --predictions $D/predictions.jsonl \
  --baseline-predictions $D/baseline_predictions.jsonl --out runs/p6
```

期望输出（exit 2）：

```
error: 候选 pass@1 与基线 pass@5 不能直接比较
next:  pass@k 随 k 单调上升；把两边都用同一个 k 重新聚合后再跑
```

**读法**：这不是“判决失败”，而是**拒绝开始比较**。把两边都聚合到同一个 `k`（或都写 `k: 1`）再跑，
才能得到可解释的 delta。

## 场景 2：代码题，隐藏用例变严（p7）

**旧比较会怎么骗人**：候选 96/120（80.0%）、基线 90/120（75.0%），点估计是 `+5.0pp`，
看起来“显著提升”。但 `n=120` 的 delta 95% CI 是 `[+1.67pp, +9.17pp]`；同时 80% 的 Wilson
下限是 71.96%，低于 80% 绝对门禁。旧流程要么因为“涨了就合”，要么因为“没过 80% 就拒”，
两种结论都建立在不足的证据上。

```bash
D=eval_gate/demo_data/scenarios/p7_code_hidden
eval-gate run --dataset $D/dataset.jsonl --predictions $D/predictions.jsonl \
  --baseline-predictions $D/baseline_predictions.jsonl \
  --changed-files evals/hidden_tests.json --out runs/p7
```

期望输出（exit 0）：

```
verdict=REVIEW pass_rate=0.8000 ci=[0.7196, 0.8618] delta=+0.0500 delta_ci=[0.0167, 0.0917] n=120
```

**读法**：`REVIEW` 不是“通过”，是“数据不足以放行或阻断”。`flags` 里的
`mde_exceeds_tolerance` 说明这点：在 `n=120` 下，这个检验能可靠检测的最小效应是
`5.55pp`，已经大于 3pp 的容差——要判“回退没超过 3pp”，样本不够。

## 场景 3：RAG，硬负例让朴素检查器假绿（p8）

**旧比较会怎么骗人**：候选的“非空且长度 ≥20”检查是 461/480（96.0%），基线 427/480（89.0%），
旧流程会说“提升 7.1pp”。但带引用、可溯源的权威评分只有 358/480（74.58%），基线 355/480（73.96%）：
真实 delta 只有 `+0.63pp`，而且绝对通过率仍低于 80% 下限。欺骗落差 `deception_gap=21.46pp`。

```bash
D=eval_gate/demo_data/scenarios/p8_rag_hard
eval-gate run --dataset $D/dataset.jsonl --predictions $D/predictions.jsonl \
  --baseline-predictions $D/baseline_predictions.jsonl \
  --changed-files prompts/grounding.md --out runs/p8
```

期望输出（exit 1）：

```
verdict=FAIL pass_rate=0.7458 ci=[0.7050, 0.7827] delta=+0.0063 delta_ci=[0.0000, 0.0146] n=480
```

**读法**：`FAIL`（自身不达标）而不是 `BLOCK`（相对基线坏了）。归因表会同时打印
naive 通过率与权威通过率，让“检查器被表面特征骗过”这件事可见。

## 场景 4：多轮工具调用，整体更好但升级路径越权（p9）

**旧比较会怎么骗人**：整体通过率 90.0% vs 88.1%，是 `+1.87pp`，旧流程会放行。但这 6 个新增
硬失败全部落在“升级到人工”的工具路径上（`l1_failures_candidate=6`，基线 0）。
安全面的回退不会被总分上升抵消。

```bash
D=eval_gate/demo_data/scenarios/p9_tool_multiturn
eval-gate run --dataset $D/dataset.jsonl --predictions $D/predictions.jsonl \
  --baseline-predictions $D/baseline_predictions.jsonl \
  --changed-files tools/escalate.json --out runs/p9
```

期望输出（exit 1）：

```
verdict=BLOCK pass_rate=0.9000 ci=[0.8699, 0.9237] delta=+0.0187 delta_ci=[0.0083, 0.0312] n=480
```

**读法**：`BLOCK` 来自 G3 安全门禁（L1 硬失败数增加），与 G1/G2 的统计结论无关。
总分提升不能赎回安全回退。

## 场景 5：判分器从 v1 换到 v2（p10）

**旧比较会怎么骗人**：候选 83.96%、基线 88.96%，`delta=-5.00pp`，CI `[-7.08pp, -3.12pp]`
整段在容差外。旧流程会直接 `BLOCK`，把“判分器变严”误判成“模型变差”。

```bash
D=eval_gate/demo_data/scenarios/p10_judge_calibration
eval-gate run --dataset $D/dataset.jsonl --predictions $D/predictions.jsonl \
  --baseline-predictions $D/baseline_predictions.jsonl \
  --changed-files scoring/judge_v2.md --out runs/p10
```

期望输出（exit 0）：

```
verdict=REVIEW pass_rate=0.8396 ci=[0.8041, 0.8697] delta=-0.0500 delta_ci=[-0.0708, -0.0312] n=480
```

**读法**：`flags` 含 `scorer_changed`，G2 是 `not_comparable`、G10 把判决压成 `REVIEW`。
`delta` 仍然打印，但它的含义是“不同判分口径下的差值”，不能归因给模型。修法是先用同一判分器
重跑基线，或做判分器校准集。

## 换成自己的数据

| 场景 | dataset 需要的字段 | prediction 需要的字段 |
|---|---|---|
| 内置客服 rubric | `id / family / input / answerable / must_include / forbidden_promises` | `id / output / claims / spans` |
| 外部判分器（上面 5 个场景） | `id / family / input` | `id / pass`（严格布尔），可加 `k`、`scorer_version`、`l1_failures`、`naive_pass` |

候选与基线必须覆盖同一批 `id`（重叠 ≥ `min_overlap`，默认 0.80），否则 G2 直接
`not_comparable`、判决 `REVIEW`。

每个场景的期望数字都写在 `eval_gate/demo_data/scenarios/<name>/scenario.json` 的 `expected` 里，
改代码后先跑 `eval-gate demo`，数字对不上会以 `MISMATCH` 退出。
