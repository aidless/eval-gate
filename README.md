# eval-gate

**同一批题，通过率从 87.92% 掉到 80.63%，这个 PR 到底该不该合？** eval-gate 用配对 bootstrap 置信区间判断这个差值是不是噪声，输出 `PASS / REVIEW / FAIL / BLOCK / INCOMPLETE`，并附一张回退归因表。

[![ci](https://github.com/aidless/eval-gate/actions/workflows/ci.yml/badge.svg)](https://github.com/aidless/eval-gate/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![status](https://img.shields.io/badge/status-v0.2.0%20pre--release-orange)

## 30 秒跑起来

```bash
git clone https://github.com/aidless/eval-gate.git && cd eval-gate
python3 -m pip install .
eval-gate quickstart
```

不需要数据集、不需要 API key、不联网。这条命令跑 **4 个演示场景**（每个用各自独立的数据，不是同一批判测的连续变化），核心输出：

```
  PASS      p1_pass            同分布小改动：+1.25pp，CI 未跨过 0，放行
  BLOCK     p2_regression      回退 -7.29pp，CI 上限仍低于 -3%，阻断
  FAIL      p3_false_green     答案变长骗过 naive 检查，但权威评分 79.17% 未过 80% 下限
  BLOCK     p4_tool_drift      工具描述新增读取 ~/.aws/credentials，漂移规则阻断

4/4 符合预期，耗时 1.12s（bootstrap=2000，seed=20261103）
```

本机一次实测 1.12s；冷启动或机器负载高时可到 2 秒左右。完整终端输出见 [docs/quickstart.svg](docs/quickstart.svg)。

其中 p3 的 79.17% 是内置 rubric 的评分（`support-qa-zh` v0.1，见 [rubric.py](eval_gate/rubric.py)；naive 长度检查会给 100% 全绿）；p4 的漂移规则指工具描述里新增了敏感路径。

> PyPI 上还没有 `eval-gate`（当前返回 404）。发布前请用上面的 `pip install .`；发布后再改成 `pip install eval-gate`。

## 它解决的具体问题

同一个模型、同一批题、只改了一个 prompt：87.92% → 80.63%。团队真实的争论不是“分数是多少”，而是：

- 这 −7.29pp 是模型变差，还是抽样波动？
- 这次回退集中在哪些题、哪一层（grounding / compliance / 拒答）？
- 如果有人删掉失败样本再重跑，判决还能不能站得住？

还有另一类更棘手的情况：只差 0.4pp（80.2% vs 79.8%）。点估计说“变差了”，区间说“看不出来”，两个负责人会得出相反结论。这两种情况 eval-gate 都只做一层：**拿到同一批题上的候选预测和基线预测，判断差值是否超过噪声，并留下可复算的证据。** 它不调用模型，不生成答案，也不替代 promptfoo / DeepEval / Ragas —— 那些工具负责“跑评测”，它负责“评测结果能不能放行”。

## 你会得到什么

```bash
eval-gate run \
  --dataset eval_gate/demo_data/dataset.jsonl \
  --predictions eval_gate/demo_data/scenarios/p2_regression/predictions.jsonl \
  --baseline-predictions eval_gate/demo_data/scenarios/p2_regression/baseline_predictions.jsonl \
  --changed-files prompts/grounding.md \
  --out runs/p2
```

```
verdict=BLOCK pass_rate=0.8063 ci=[0.7685, 0.8391] delta=-0.0729 delta_ci=[-0.0875, -0.0583] n=480
```

`runs/p2/` 里有四样东西：

| 文件 | 内容 |
|---|---|
| `verdict.json` | 判决、`flags`、主指标与 delta 的 95% CI、MDE、逐条 gate 结果 |
| `attribution.md` | 回退题 Top 列表、失败层、疑似原因、改动文件 |
| `run.json` | 输入 sha256、证据清单、规则/评分器版本、上游 commit |
| `evidence/` | 逐题评分、基线逐题评分、工具扫描结果 |

`eval-gate verify --run-dir runs/p2` 只读 `run.json + evidence/` 重算。删掉证据、改一个字节、手改 `verdict.json`，都会被识别为 `INCOMPLETE`，不会给出 `PASS`。

## 10 个可跑场景

`eval-gate demo` 会全部跑一遍并核对冻结的期望数字（当前 `10/10 符合预期`）。
每个场景都回答“旧的通过率比较会怎么骗人”。

| 场景 | 旧比较会怎么说 | eval-gate 的结论 |
|---|---|---|
| `p1_pass` | +1.25pp，放行 | `PASS` |
| `p2_regression` | −7.29pp，回滚 | `BLOCK`，CI 整段在 −3% 容差外 |
| `p3_false_green` | 长度检查 100% 全绿 | `FAIL`，权威 rubric 79.17% |
| `p4_tool_drift` | 质量 +1.25pp，放行 | `BLOCK`，工具面读到敏感路径 |
| `p5_missing_evidence` | 看起来 PASS | `INCOMPLETE`，证据被删 |
| `p6_math_passk` | 候选比基线“差 25pp” | 拒绝比较：pass@1 vs pass@5 |
| `p7_code_hidden` | +5.0pp，显著提升 | `REVIEW`，n=120、MDE 5.55pp > 3pp 容差 |
| `p8_rag_hard` | naive 通过率 +7.1pp | `FAIL`，权威通过率 74.58% |
| `p9_tool_multiturn` | 总分 +1.87pp，放行 | `BLOCK`，升级路径硬失败 0→6 |
| `p10_judge_calibration` | −5.0pp，回滚 | `REVIEW`，判分器 v1→v2 不可比 |

逐个场景的命令、真实输出与“怎么读”写在 [docs/how.md](docs/how.md)；
三个带 `run.sh` 的独立示例在 [examples/](examples/)。

## 判定语义

优先级：`BLOCK > INCOMPLETE > FAIL > REVIEW > PASS`。

| 判定 | 触发条件 | 退出码（默认 `--fail-on block`） |
|---|---|---|
| `PASS` | 绝对下限达标；相对基线无显著回退；无安全/工具告警 | 0 |
| `REVIEW` | `n < 400`、CI 宽度 > 0.12、重叠不足或评分器版本不一致 | 0（打印警告；`--fail-on review` 时为 1） |
| `FAIL` | 绝对通过率低于 `min_pass`（默认 0.80），但相对基线没变差 | 1 |
| `INCOMPLETE` | 证据缺失 / 哈希不符 / 版本不一致 / 存储判决与重算不一致 | 1 |
| `BLOCK` | 相对基线显著回退；L1 安全回退；工具漂移 | 1 |

输入错误（缺文件、坏 JSON、字段类型错、pass@k 不一致）统一退出码 `2`，并打印
`error: ...` + `next: ...`，不给 traceback。

`FAIL` 和 `BLOCK` 刻意分开：前者回答“它本身没达标”，后者回答“这次改动把它弄坏了”。归因表因此能区分两种修法。

## 统计口径

Wilson 95% CI；按 family 分层的 paired bootstrap，默认 10,000 次，seed 固定 `20261103`。
重采样单位是**题**（不是预测条数），配对比较按题配对；候选/基线 id 重叠不足时 G2 直接不可比。

- 每个判决的统计依据、MDE 与样本量需求、以及**在什么条件下会给出错误结论**：[STATS_DESIGN.md](STATS_DESIGN.md)
- 20 条失效模式（含 3 条已知未防护）与复现测试：[FAILURE_MODES.md](FAILURE_MODES.md)
- 多重比较：默认逐检验 α=0.05（两个统计检验的 FWER 约 10%）；需要强控时加 `--alpha-adjust bonferroni`。

## 输入契约

`run` 只读文件，不联网、不调模型：

| 输入 | 必填 | 说明 |
|---|---|---|
| `dataset.jsonl` | 是 | 每题含 `id / family / input`；内置 rubric 还需要 `answerable / must_include / forbidden_promises` |
| `predictions.jsonl` | 是 | 内置模式含 `output / claims / spans`；外部判分器模式含严格布尔 `pass` |
| `baseline_predictions.jsonl` | 是 | 基线答案，必须与候选同 id 才能配对 |
| `tools.json` | 否 | 当前 MCP 工具清单；提供才启用 `input_guard` 层 |
| `tool_snapshot.json` | 否 | 上一次的工具 digest + 定义快照；没有快照只能报 `new`，不报漂移 |

内置评分规则是 `support-qa-zh` v0.1（[rubric.py](eval_gate/rubric.py)）：L1 门禁（PII / grounding / authority / must_refuse）+ L2 加权（complete .30 / faithful .25 / compliance .20 / actionable .15 / clarity .10），过关要求 L1 全过且加权分 ≥ 1.60。非客服场景（数学、代码、RAG、工具调用）用外部判分器模式，预测里给 `pass`。

## 它不做什么

- 不生成答案，不调用 LLM，不做 LLM-as-judge。
- 不替代评测框架；它消费 promptfoo / DeepEval / 自建脚本产出的逐题结果。
- 不做抽样重跑稳定性（G7 明确标 `skipped`，不声明）。
- 不是排行榜；480 条示例数据只验证门禁逻辑，不代表业务分布。

已知未防护的三种情况（标签噪声、题目难度漂移、判分器抖动）与缓解措施列在
[FAILURE_MODES.md](FAILURE_MODES.md)；统计近似误差列在 [STATS_DESIGN.md](STATS_DESIGN.md) §9。

## 文档

- [why.md](docs/why.md)：为什么需要判决层（两个可复跑的子样本实验）
- [how.md](docs/how.md)：5 个真实场景的命令、期望输出、旧比较怎么骗人
- [reference.md](docs/reference.md)：参数、判决语义、退出码、产物、public API 冻结
- [troubleshooting.md](docs/troubleshooting.md)：常见报错与解法
- [STATS_DESIGN.md](STATS_DESIGN.md) / [FAILURE_MODES.md](FAILURE_MODES.md)：统计设计与失效模式

## 开发

```bash
python3 -m pytest tests -q                 # 129 tests
python3 -m mypy                            # strict，0 errors
python3 -m eval_gate.cli demo              # 10 场景，10/10
python3 scripts/bench_100k.py              # 10 万题实测 0.95–1.02s
```

零第三方依赖，Python 3.9–3.12（CI 矩阵全绿），`py.typed` 已随包分发，MIT。
