# 统计设计（STATS_DESIGN）

这份文档回答三个问题：每个判决**依据什么统计量**、这些统计量**在什么条件下会给出错误结论**、
以及**为什么默认值可能不适合你的评测集**。如果你只想知道怎么用，看 [docs/how.md](docs/how.md)。

一句话口径：**所有判决都是「区间 vs 阈值」的比较，不是「点估计 vs 阈值」的比较。**
点估计只用于展示，不参与放行。

---

## 1. 三个统计量

| 量 | 定义 | 实现 |
|---|---|---|
| 绝对通过率 | `passes / n` | 内置 rubric 的 `pass` 字段，或外部判分器给的严格布尔 `pass` |
| 绝对区间 | Wilson score 95% 双侧区间 | `stats.wilson_interval(passes, n, z)`，零依赖 |
| 配对差值 | 同一 `id` 上 `candidate_pass - baseline_pass` 的均值 | `stats.paired_delta_ci(...)` |
| 差值区间 | 按 `family` 分层的 paired bootstrap 百分位区间 | 迭代 `bootstrap_iters` 次，seed 固定 |
| MDE | 在给定方差、α=0.05、power=0.8 下能检出的最小真实差值 | `(z_{α/2}+z_{0.8})·sqrt(var)` |

大样本退化路径：当 `iterations × n > 20,000,000`（默认 10,000 次 × 2,000 题）时，
`ci_method="auto"` 改用**分层正态近似**：

```
var(delta) = Σ_h n_h · var_h(diff) / n²
CI = delta ± z_{α/2} · sqrt(var)
```

这条路径把 10 万样本的判决时间压到约 1 秒（实测见 §8），代价是区间从百分位法变成正态近似。
两种方法在 n≥400 时差异通常小于 1pp；`method` 字段会写进 `verdict.json`，不会偷偷切换。

---

## 2. 判决定义与统计依据

优先级：`BLOCK > INCOMPLETE > FAIL > REVIEW > PASS`（`VERDICT_ORDER`）。

| 判决 | 统计依据 | 含义 | 默认退出码 |
|---|---|---|---|
| `PASS` | Wilson 下限 ≥ `min_pass`；G2 未触发；无安全/工具告警 | 绝对达标且没有显著回退 | 0 |
| `REVIEW` | `n < min_n`，或绝对/差值区间宽 > `max_ci_width`，或数据集/评分器不可比 | **拒绝在没有证据时给结论** | 0（警告） |
| `FAIL` | Wilson 下限 < `min_pass`，且 G2 通过 | 本身不达标，不是这次改坏的 | 1 |
| `BLOCK` | G2 差值区间上限 ≤ `−max_regression`；或 G3/G4 确定性规则触发 | 相对基线显著回退，或安全面回退 | 1 |
| `INCOMPLETE` | 必需证据缺失/哈希不符/版本不一致 | 证据链不成立，不能采信 | 1 |

关键细节：

- **G1 是单侧判断，但用的是双侧 95% 区间下限。** 也就是实际证据强度是单侧 2.5%，
  比「单侧 5%」保守。想提高灵敏度只能增大 n，不能把 z 换成 1.645 而不改文档。
- **G2 的容差语义**（v0.2.0 修正）：
  `delta_ci_high <= −max_regression`。旧写法 `delta_ci_high <= +max_regression`
  会把「−4pp 的回退，区间上限 −2pp」判成 BLOCK，等于宣称「确定超过 3pp 容差」，
  而数据只支持「可能回退 2–4pp」。锁定这条语义的测试是
  `tests/test_gates.py::RegressionToleranceTests::test_small_regression_inside_tolerance_does_not_block`。
- **G5 只压制统计类判决。** 样本不足时 `PASS/FAIL/BLOCK` 全部降为 `REVIEW`，
  但 G3 安全回退、G4 工具漂移、G6 证据缺失不受压制：这些不依赖样本量。
  测试：`test_g5_caps_statistical_block`、`test_g5_does_not_cap_safety_block`。

---

## 3. 重采样单位：按题，不是按预测条数

配对比较的正确单位是**题**，因为候选与基线在同一道题上的结果相关。
`stats._strata` 只保留两边都存在的 `id`，按 `family` 分组；bootstrap 在每组内
**有放回地重抽题**（`k = n_h`），再计算 `Σ_h mean_h / n`。

如果按「预测条数」重采样、或把候选/基线各自独立重采样，会破坏配对相关性，
差值区间的方差会被高估（更保守、更多 REVIEW），极端情况下会把真实回退漏掉。
`paired_delta_ci` 返回的 `n` 是交集大小，`discordant` 是候选与基线结果不同的题数，
两者都会写进 `verdict.json`，便于核对。

分层的作用：不同 `family` 的方差差异很大（如数学题与拒答题）。按 family 分层后，
方差不均不会让某一组主导区间。只有一个 family 时会挂
`single_family_no_stratification` flag——这不是错误，但说明分层没有起作用。

---

## 4. 阈值与 MDE：默认 `min_n=400` 不是万能的

MDE（最小可检测效应）回答：**如果真实回退是 3pp，这个样本量有多大把握检出来？**

```
var(delta) ≈ d / n            d = 不一致率（discordant / n）
MDE        ≈ (1.96 + 0.84) · sqrt(d / n) = 2.80 · sqrt(d / n)
n          ≥ d · (2.80 / 容差)²
```

若容差是 3pp：

| 不一致率 d | 达到 80% 功效所需 n |
|---|---|
| 2% | ≈ 175 |
| 5% | ≈ 436 |
| 10% | ≈ 872 |
| 20% | ≈ 1,744 |

默认 `min_n=400` 只在 d ≤ 4.6% 时对 3pp 容差有 80% 功效。
**所以「n=480 且判 PASS/BLOCK」不等于「3pp 的回退一定被抓住」。**

本包的处理是**披露而不是偷偷加严**：

- `delta.mde` 写进 `verdict.json`；
- 当 `MDE > max_regression` 时挂 `mde_exceeds_tolerance` flag；
- flag 不改判决，因为把 MDE 写死会把大量可用场景变成永远 `REVIEW`。

实测样例（默认 3pp 容差）：

| 场景 | n | MDE | 是否披露 |
|---|---|---|---|
| p1 正常提升 | 480 | 0.0136 | 否 |
| p2 prompt 回退 | 480 | 0.0215 | 否 |
| p7 代码隐藏用例 | 120 | 0.0555 | **是**（`mde_exceeds_tolerance`） |
| p9 多轮工具 | 480 | 0.0171 | 否 |
| p10 判分器校准 | 480 | 0.0275 | 否 |

如果你的真实不一致率很高（比如 20%），把 `min_n` 提到 1700 以上，
否则请把 `max_regression` 放宽到与真实功效匹配的水平，并在 PR 描述里写明。

---

## 5. 多重比较：默认不校正，可选 Bonferroni

一次判决里有**两个**统计检验同时进行：

1. G1：绝对通过率是否低于 `min_pass`（Wilson 下限）；
2. G2：差值是否显著超过 `max_regression`（配对区间）。

默认 `alpha=0.05` 是**逐检验**的。两个检验的族错误率上界是 `2 × 0.05 = 10%`
（独立时约 9.75%）。这意味着：**当两个检验都恰好处于边界时，整体误判概率约为单次的两倍。**

需要严格控制 FWER 时，设 `alpha_adjust="bonferroni"`：

```
alpha_used = alpha / 2 = 0.025
```

区间会变宽，贴边的 BLOCK 可能退回 PASS。这是保守方向的选择，不是 bug。
`metrics.alpha_used` 与 flag `alpha_adjust:bonferroni` 都会写进判决。
测试：`tests/test_failure_modes.py::MultipleComparisonTests::test_fm12_bonferroni_widens_interval`。

**不校正的适用前提**：你更怕漏掉回退（假阴性），而不是偶尔多一次 REVIEW/BLOCK；
且你在 PR 流程里会把 `threshold_edge` flag 视为「需要人工看一眼」。

---

## 6. seed 与可复现性

- 随机源：`random.Random(seed)`，CPython 的 Mersenne Twister，**不用 numpy**。
- 抽样：`choices(values, k=len(values))` 无权重路径是 `floor(random() * n)`，
  不依赖字典顺序（`values` 是列表，顺序来自输入文件顺序）。
- 种子默认 `20261103`，可在 `run` 配置里改；`verdict.json` 记录 `delta.seed`。
- 浮点：bootstrap 内层逐元素累加（`total += value`），百分位用线性插值；
  不使用 `math.fsum` 或平台相关的并行归约。

**实测**：同一 fixture 在 CPython 3.9.25 / 3.10.22 / 3.11.16 / 3.12.3 上，
`paired_bootstrap_delta(seed=20261103, iterations=500)` 得到逐位相同的
`delta=0.2`、`ci95=[0.13333333333333333, 0.2710416666666665]`。
测试：`tests/test_stats.py::GoldenReproducibilityTests`。

**边界（诚实说明）**：上述验证在同一台 x86_64 Linux 上完成，未在 ARM/Windows 实测。
理论上 MT19937 与 IEEE-754 双精度是跨平台一致的；若某平台的 `sqrt` 在 MDE 上差 1 ulp，
四舍五入到 6 位小数后通常看不出来。真跨架构复现时，以 golden 测试失败为准，不要假设。

---

## 7. 每个判决在什么条件下会给出错误结论

这是这份文档最重要的一节。**能说清「我什么时候会错」的包，才有人信。**

### `PASS` 可能错在

| 条件 | 机制 | 现有防护 |
|---|---|---|
| 标签噪声（人工或 rubric 标错） | 通过率建立在错误标签上；候选/基线同错时 delta=0，区间很窄 | **无**（见 FAILURE_MODES FM-02）；缓解：金标抽查、双人标注、判分器与人工一致性抽样 |
| 评测集泄漏（改写过的重复题） | n 虚增、区间变窄、delta 被少数重复题主导 | 只防精确重复（同题面换 id 直接报错）；改写重复**无防护**（FM-04） |
| 判分器不稳定（LLM judge 抖动） | 每次重跑结果不同，区间只反映抽样误差，不反映判分抖动 | **无**（G7 只标记 `skipped`，FM-07）；缓解：固定 temperature/模型版本、对 5–10% 样本双跑比对 |
| 基线用旧数据集/旧评分器重跑 | 配对 id 完整，但内容不可比 | 评分器版本不同 → G10 REVIEW；数据集漂移**无防护**（FM-04） |
| MDE > 容差 | 真实回退小于可检测下限时仍可能 PASS | flag `mde_exceeds_tolerance`；不改判决，需人看 |
| 通过率接近 1 且 n 大 | Wilson 区间很窄 | 正常行为；但若评测集过易，PASS 不代表泛化 |

### `FAIL` 可能错在

| 条件 | 机制 | 现有防护 |
|---|---|---|
| `min_pass` 设错 | 阈值本身就是产品决策，统计无法纠正 | 无（文档要求写明理由） |
| 候选的评分器比基线更严格 | 相同答案被判更差 | G10（要求两边声明 `scorer_version`） |
| 不可答题目标注错误 | 该拒答的被标成应答，`must_refuse` 误伤 | 无（属于 FM-02 标签噪声） |
| 数据集对候选更难（难度漂移） | 绝对通过率下降与模型能力无关 | 无（FM-04）；缓解：同一数据集上重跑基线 |

### `BLOCK` 可能错在

| 条件 | 机制 | 现有防护 |
|---|---|---|
| 容差过窄（如 1pp）而 n 不足 | 置信区间跨过容差边界时不会 BLOCK，但贴边 BLOCK 很脆弱 | `threshold_edge:G2` flag |
| 重复题占比高 | 区间过窄，放大了少数题的影响 | 精确重复已拦；改写重复无防护 |
| 多重比较（G1+G2 同时贴边） | 族错误率上升 | `alpha_adjust=bonferroni` 可选 |
| 基线与候选不是同一判分器 | 差值来自判分口径 | G10 → REVIEW |
| 安全回退计数受基线缺失影响 | 若基线证据缺失，G3 不比较 | G3 在缺基线时标 `not_comparable`，不会 BLOCK |

### `REVIEW` 可能错在（过度保守）

- n 达标但方差极高（family 内差异大），区间宽度 > 0.12 → 永远 REVIEW。
  缓解：增大评测集，或按 family 分别跑门禁。
- `alpha_adjust="bonferroni"` 会让贴边场景更容易 REVIEW。

### `INCOMPLETE` 可能错在

- 它本身是「无法判断」，不是结论。若上一次判决更严重，G9 保证删证据不能把 `BLOCK/FAIL` 变轻。

---

## 8. 性能实测

命令：`python3 scripts/bench_100k.py`（本机，CPython 3.12，单线程）。

```
n=100000
method=normal
iterations=0
verdict=PASS
pass_rate=0.900000 delta=+0.020000
delta_ci=[0.019132, 0.020868]
mde=0.001241
elapsed=1.0237s
```

10 万样本、默认配置下 `auto` 判定工作量过大，实际走分层正态近似（`iterations=0`），**两次实测 1.0237 秒 / 0.9478 秒**。
4 个 480 题场景的 `quickstart`（2000 次 bootstrap/场景）本机多次实测 **1.1–2.4 秒**（含进程启动，随负载波动）。

---

## 9. 已知统计局限

1. **百分位 bootstrap 不是 BCa。** 分布强偏斜（通过率接近 0 或 1）时覆盖率可能偏低；
   n≥400 时影响通常可忽略，样本更小时请把结论当 REVIEW 看。
2. **Wilson 不是 Clopper-Pearson。** Wilson 在 p 接近 0/1 时略窄；要更保守可自行换精确法，
   但当前实现刻意让区间不随平台变化的简洁。
3. **正态近似与 bootstrap 的方差分母不同**（`n_h` vs `n_h−1`），大样本下差异可忽略；
   `method` 字段会披露用了哪种。
4. **默认不做跨 gate 校正**，见 §5。
5. **不做序列相关/聚类校正。** 同一段落派生出的多道题会被当成独立题；
   若你的数据集有这种结构，应在 `family` 里区分并接受分层只解决一部分问题。
