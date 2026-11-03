# Vendored / adapted components

所有上游仓均为 MIT。以下文件在 eval-gate 内被复制或改写，文件头保留了原路径。

| eval-gate 文件 | 上游路径 | commit | 方式 |
|---|---|---|---|
| `eval_gate/schema.py` | `/home/liuzewen/gh-publication-audit-20261029/agent-reliability/contracts/jsonschema_mini.py` | `e86a865bb9c41e97faa2dc1fddc2a9cb8ab44420` | 直接复制 + 头注释 |
| `eval_gate/tools.py` | `/home/liuzewen/mcp-guard/guard/rules.py`、`drift.py`、`scan.py` | `17ce95732b2e28af9e98e1ec7c3ddcbd099fb164` | 抽取核心函数，保留 `(rule, anchor)` 漂移语义 |
| `eval_gate/schemas/run.schema.json` | `/home/liuzewen/gh-publication-audit-20261029/agent-reliability/contracts/run.schema.json` | `e86a865bb9c41e97faa2dc1fddc2a9cb8ab44420` | 结构改编：新增 `evidence_manifest / layers / inputs.config` |
| `eval_gate/gate.py` | `/home/liuzewen/gh-publication-audit-20261029/agent-reliability/rules/engine.py` + `joint_verdict.json` | `e86a865bb9c41e97faa2dc1fddc2a9cb8ab44420` | 复用「全规则求值 + precedence」与 R10 不变量；判据重写 |
| `eval_gate/runner.py` | `/home/liuzewen/gh-publication-audit-20261029/agent-reliability/contracts/validate.py` | `e86a865bb9c41e97faa2dc1fddc2a9cb8ab44420` | 复用「重算并与存储比对」；加 sha256 证据清单 |
| 评分思路 | `/home/liuzewen/auditable-llm-eval/copilot/score_copilot_run_v2.py` | `d4fcdcd31de1945ef39ba0c5952f62cc3f559d8a` | 复用「权威评分 vs naive」对照；实现改为确定性规则 |

`run.json.repos` 会记录上述 commit，便于从任意一次判决追溯到 vendored 版本。
