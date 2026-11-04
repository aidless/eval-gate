# 常见失败与解法

所有可预期错误都是两行：`error: 哪里错了` + `next: 下一步做什么`，退出码 `2`。
下面按出现频率排序。

## 1. `error: 文件不存在：...`

**原因**：路径拼错，或相对路径不是从当前工作目录算起。

**解法**：用绝对路径；确认三个输入都存在：

```bash
ls dataset.jsonl candidate.jsonl baseline.jsonl
```

## 2. `error: 第 N 行不是合法 JSON`

**原因**：尾逗号、中文引号、字符串未转义，或一行里放了多行 JSON。

**解法**：每行必须是一个完整对象。快速定位：

```bash
python3 -c "import json,sys; [json.loads(l) for l in open('candidate.jsonl')]"
```

## 3. `error: dataset 里 id 重复：q-001`

**原因**：同一题出现两次。

**解法**：去重。重复题会被当成独立样本，虚增 `n` 并压低 CI 宽度。

## 4. `error: dataset 里 q-001 与 q-002 的 input 完全相同`

**原因**：同一题面换了 id（去空白、转小写后相同）。

**解法**：合并成一条；如果确实是不同题（例如同一题面的不同问法），改写题面让它们可区分。

## 5. `error: prediction id 不在 dataset 中：q-999`

**原因**：预测的 id 与数据集不一致（大小写、前后空格、旧版本题号）。

**解法**：这些行会被丢弃并低估 `n`，所以直接拒绝。对齐 id，或把新题加进 dataset。

## 6. `error: prediction q-001 的 pass 字段是 str，不是布尔`

**原因**：外部判分器把 `pass` 写成 `"true"` / `"false"`，或写了 `1` / `0`。

**解法**：写 JSON 布尔 `true/false`。若想用内置 rubric，删掉 `pass` 字段。

## 7. `error: 候选 pass@1 与基线 pass@5 不能直接比较`

**原因**：pass@k 的口径不同。`pass@k` 随 k 单调上升，直接比会得出虚假的“提升/回退”。

**解法**：两边用同一个 `k` 重新聚合；或两边都不写 `k`（只比聚合后的单点结果）。
一边写 `k`、另一边没写也会被拒绝。

## 8. `error: 未知配置项：max_regresion`

**原因**：配置键拼写错误。`run` 会拒绝未知键，避免静默忽略。

**解法**：可用键见 [reference.md](reference.md) 的参数表；常见是 `max_regression`。

## 9. `error: 配置 max_regression=3 越界`

**原因**：阈值写成了百分点。

**解法**：用比例：3% 写 `0.03`，不是 `3`。

## 10. 判决是 `REVIEW`，不是 `PASS` / `BLOCK`

**原因**：功效不足或可比性不足。看 `flags` 与 `gates`：

| 现象 | 含义 | 解法 |
|---|---|---|
| `G5-power` fail | `n < min_n` 或 CI 宽 > `max_ci_width` | 扩样本，或明确接受更低功效后调 `min_n` |
| `mde_exceeds_tolerance` | 当前样本能检测的最小效应 > 3pp | 扩样本到 STATS_DESIGN §4 的建议值 |
| `G8-comparable` fail | id 重叠 < `min_overlap` | 候选与基线用同一批题重跑 |
| `G10-scorer` / `scorer_changed` | 判分器版本不同 | 用同一判分器重跑基线，或做校准集 |
| `single_family_no_stratification` | 只有一个 family | 补 family 标签，或接受整体重采样 |

`REVIEW` 默认退出码是 0；CI 里想阻断就加 `--fail-on review`。

## 11. `verify` 给出 `INCOMPLETE`

看 stderr 的 `problem:` 行：

| problem | 原因 | 解法 |
|---|---|---|
| `缺少必需证据 evidence/per_item.jsonl` | 文件被删/没写全 | 从 `--out` 重跑；不要手工补 |
| `... (sha256 不匹配)` | 证据被改过一个字节 | 重跑；证据不可编辑 |
| `rules_version ... ≠ 当前 ...` | 规则版本变了 | 用当前版本重跑，旧证据只能作历史记录 |
| `run.json 不符合契约` | schema 版本不符或字段被改 | 不要手改 `run.json`；从源头重跑 |
| `存储判决与重算不一致` | 手改了 `verdict.json` | 重跑；判决由证据决定 |

已有 `BLOCK` 时删证据不会降级成 `PASS`（G9），这是有意的。

## 12. `error: 找不到内置 schema ...`

**原因**：安装不完整，`eval_gate/schemas/` 没被打进 wheel。

**解法**：

```bash
python3 -m pip install --force-reinstall .
```

源码运行时确认 `eval_gate/schemas/` 存在。

## 13. `error: 工具清单顶层既不是数组，也没有 tools 数组`

**原因**：`--tools` 指向的 JSON 结构不对。

**解法**：写成数组 `[{"name": "search", "description": "...", "input_schema": {...}}]`，
或 `{"tools": [...]}`。

## 14. `error: dataset 是空的`

**原因**：文件只有空行，或路径指向了错误文件。

**解法**：至少一条 `{id, family, input, reference}`。空集会得到 `n=0`，没有任何统计意义。

## 15. bootstrap 很慢 / 想跑大样本

- 480 题 × 10,000 次约 1–1.2 秒（含进程启动）；10 万题会自动切到 `ci_method=normal`（见 `flags: ci_method:normal`）。
- 想强制 bootstrap：`--ci-method bootstrap`；想更快：`--iterations 2000`（判决通常不变，但区间略抖）。
- 复现问题请带上 `seed`、`iterations`、`ci_method`，三者写在 `verdict.json` 的 `delta` 里。

## 还解决不了

带上三样东西开 issue：`run.json`、`verdict.json`、完整命令。
如果涉及错判决，请附上 `evidence/per_item.jsonl`（可以脱敏 `output_excerpt`）。
