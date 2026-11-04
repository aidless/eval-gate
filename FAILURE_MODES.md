# 失效模式清单（对抗性自审）

这份文档回答一个问题：**eval-gate 在什么情况下会给出错误判决？**

每一条都有可复现的测试。测试文件是 [tests/test_failure_modes.py](tests/test_failure_modes.py)
（少数跨模块条目来自 [tests/test_gates.py](tests/test_gates.py) 与 [tests/test_tamper.py](tests/test_tamper.py)），
编号 `FM-NN` 与用例名一一对应。

复现全部：

```bash
python3 -m pytest tests/test_failure_modes.py -v
```

## 汇总

| 编号 | 失效模式 | 触发条件 | 后果 | 现有防护 | 测试用例 |
|---|---|---|---|---|---|
| FM-01 | 样本量极小 | `n < min_n`（默认 400），或区间宽到无法区分 | 点估计的结论不可用 | G5 功效门禁把统计类 `PASS/FAIL/BLOCK` 压成 `REVIEW` | `test_fm01_tiny_sample_reviews` |
| FM-02 | 标签噪声 | 人工/模型标注本身有错（对称噪声 10%） | 通过率系统性偏移；配对后 delta 可能仍是 0，判决 `PASS` | **已知未防护**（见下文） | `test_fm02_label_noise_is_invisible` |
| FM-03 | 评测集泄漏（精确重复题面） | 数据集里两题 `input` 完全相同（去空白、转小写后） | 同题被算两次，`n` 虚增、CI 变窄 | `_validate_dataset` 硬拒绝，报错说明“会虚增 n、压低 CI 宽度” | `test_fm03_duplicate_input_rejected` |
| FM-04 | 题目难度漂移 / 旧数据集 | 基线来自更早、更容易（或更难）的题集，但 id 相同 | 难度差异被算成模型差异，delta 失真 | **已知未防护**（见下文） | `test_fm04_difficulty_drift_is_invisible` |
| FM-05 | pass@k 的 k 不一致 | 候选声明 `k=1`、基线 `k=5`（或一边声明一边没有） | `pass@1` 与 `pass@5` 直接比，结论必然虚高 | `_check_k` 拒绝运行，报错点名 `pass@1`/`pass@5` | `test_fm05_k_mismatch_rejected`、`test_fm05_same_k_accepted` |
| FM-06 | 重复题当独立样本（id 重复） | 同一 id 在数据集或预测里出现两次 | 一题被计两次，`n` 与 delta 都错 | 数据集 id 唯一性校验；预测 id 重复同样报错 | `test_fm06_duplicate_id_rejected` |
| FM-07 | 判分器本身不稳定 | 同一答案两次调用 judge 得到不同 `pass` | 判分噪声被算进模型 delta；`PASS/FAIL` 可能是判分器抖动 | **已知未防护**：G7 只标 `skipped`，不做重判（见下文） | `test_fm07_external_scorer_instability_is_not_detected` |
| FM-08 | 分布极端偏斜 | 479/480 通过（或 1/480 通过） | 点估计看起来“稳”，实际区间不对称，尾部风险被低估 | Wilson 区间（不是正态近似）保证宽度非 0，且在 `metrics` 里披露 | `test_fm08_extreme_skew_still_has_interval` |
| FM-09 | 零方差 | 候选与基线逐题完全相同 | delta 区间退化为 `[0.0, 0.0]`，误以为“绝对没变化” | 不崩、明确输出 `[0,0]` 与 `mde=0`；语义在 STATS_DESIGN §7 写清 | `test_fm09_identical_candidate_and_baseline` |
| FM-10 | 单侧 vs 双侧 | 用点估计比阈值，或把 95% 区间误当单侧 | 阈值附近本该 `FAIL` 的被放行 | G1 用 Wilson 区间**下限**（双侧 2.5% 尾）与 `min_pass` 比较 | `test_fm10_g1_uses_wilson_lower_bound` |
| FM-11 | 阈值贴边 | 区间下限离 `min_pass` 或 delta 上限离 `-max_regression` < 0.2pp | 结论成立但换一批题就翻 | 挂 `threshold_edge:G1` / `threshold_edge:G2` flag，不改变判决 | `test_fm11_threshold_edge_is_flagged` |
| FM-12 | 多处同时改动（多重比较） | 一次比多个指标/多个 family，仍按逐检验 α=0.05 | 至少一次假阳性的概率上升（本包两个统计检验约 10%） | `alpha_adjust="bonferroni"` 把 α 分摊到检验数；flag 披露 | `test_fm12_bonferroni_widens_interval` |
| FM-13 | 跨版本不可比（规则版本） | `run.json` 里 `rules_version` 与当前代码不一致 | 旧规则下算出的证据被当成本版本结论 | `verify` 判 `INCOMPLETE`，并列出 `rules_version` 问题 | `test_fm13_rules_version_mismatch_is_incomplete` |
| FM-14 | 缺字段 / 字段类型错 | 数据集缺 `id`、`input` 非字符串；`run.json` 缺 `inputs.config` | 原生实现会抛 `KeyError`/`TypeError`，用户无从下手 | 统一转 `EvalGateError`，带 `next:` 下一步；`verify` 报 `problems` | `test_fm14_missing_dataset_id_is_actionable`、`test_fm14_missing_inputs_config_is_reported` |
| FM-15 | schema 版本不匹配 | `run.json` 的 `schema_version` 不是当前版本 | 字段语义可能已变，静默重算会给出错结论 | 校验失败 → `INCOMPLETE`；版本不一致 → `INCOMPLETE` | `test_fm15_schema_version_mismatch_is_incomplete` |
| FM-16 | 候选/基线不是同一批题 | 两次评测抽样不同，id 重叠 < `min_overlap`（默认 0.80） | 配对样本被稀释，delta 失去意义 | G2 标 `not_comparable`、G8 触发 `REVIEW`；`metrics.overlap` 披露 | `test_overlap_below_threshold_reviews`、`test_g2_not_comparable_with_disjoint_ids` |
| FM-17 | 空数据集 | `dataset.jsonl` 为空或全空行 | 除零、`n=0` 的假 `PASS` | 明确拒绝，报错含“空”与下一步 | `test_fm17_empty_dataset_is_actionable` |
| FM-18 | 证据被删 / 被改 | 删除 `evidence/`、追加一个字节、手改 `verdict.json` | 无证据的 `PASS` 可被伪造 | `verify` 只读重算 + sha256；删证据 → `INCOMPLETE`；已有 `BLOCK` 不被降级 | `test_deleting_evidence_does_not_downgrade_block`、`test_tampered_evidence_hash_is_incomplete`、`test_tampered_verdict_json_is_detected` |
| FM-19 | 外部判分器类型错 | prediction 里 `pass` 写成 `"false"` 字符串 | 字符串真值判断把失败当通过 | 只接受严格布尔，报错含“布尔”与下一步 | `test_fm19_external_pass_must_be_bool` |
| FM-20 | 评分器版本变化（scorer_version） | 候选 `judge-v2`、基线 `judge-v1` | 分数变化归因给模型，实际是判分器变了 | G10 + G2 `not_comparable` → `REVIEW`，flag `scorer_changed` | `test_fm20_scorer_change_is_review` |

共 20 条；**已知未防护 3 条**：FM-02、FM-04、FM-07。

## 已知未防护（3 条）

### FM-02 标签噪声

**为什么会错**：eval-gate 消费的是“每题过/不过”，不校验标签本身。若标注者把 10% 的题标反，
通过率会整体偏移；如果候选和基线用的是**同一份**错误标签，delta 甚至会是 0，判决给出 `PASS`。

**缓解**（三层，均在本包之外）：

1. 抽样人工复核：每次判决前抽 20–50 条逐题核对，记录一致率；低于 90% 先停判。
2. 双人标注 + 分歧仲裁：分歧题不计入 `n`，并在报告里单列。
3. 用 `--predictions` 携带外部 `pass` 时，写明判分器版本（`scorer_version`），让标签来源可追溯。

**为什么不做进包里**：没有第二份独立标签，就无法从单次结果里识别噪声；假装能检测会给出虚假的安全感。

### FM-04 题目难度漂移

**为什么会错**：只要 id 相同就会被配对。若基线是一年前的题集（或候选换了更难的题），
难度变化会被算成模型变化。`overlap=1.0` 只证明“id 对得上”，不证明“题一样难”。

**缓解**：

1. 冻结评测集：`dataset.jsonl` 进版本控制，改动走 review；`run.json` 已记录数据集 sha256。
2. 换题时同时重跑基线（candidate 与 baseline 必须同一 commit 的同一份数据）。
3. 看 `metrics.overlap` 与 `n`：两者都正常也不代表可比，需人工确认数据版本。

**为什么不做进包里**：难度是语义属性，没有题目难度参数就无法量化；本包只能保证“同一文件内可比”。

### FM-07 判分器不稳定

**为什么会错**：LLM-as-judge 有采样温度，同一答案两次可能给出不同 `pass`。G7 在 MVP 里是
`skipped`（明确不声明），所以抖动会直接进入 delta，`PASS/FAIL` 可能来自判分噪声而非模型。

**缓解**：

1. 判分器 `temperature=0`、固定 `scorer_version`，并在评分层做 2–3 次重复判分取多数。
2. 抽 30 条同一答案重复判分，统计自一致率；低于 95% 时把 `min_n` 调大或改用确定性规则。
3. 判决前看 `flags`：出现 `scorer_changed` 时先解决版本问题，不要直接读 delta。

**为什么不做进包里**：重判需要调用外部判分器，违反“零依赖、不联网、不调模型”的边界。

## 边界说明

- 以上“防护”指的是**判决层能识别并显式拒绝/降级**，不代表统计结论绝对正确。
- 统计量本身的近似误差（百分位 bootstrap 非 BCa、Wilson 非 Clopper-Pearson、未做聚类校正）
  写在 [STATS_DESIGN.md](STATS_DESIGN.md) §9。
- 新增失效模式时：先在 `tests/test_failure_modes.py` 写一个能复现的用例，再在本表加一行。
