# eval-gate Benchmark Report (v0.2.0)

Citable anchor for the frozen demo suite. Every number below is reproducible from a
clean clone with one command — no API key, no network, no model calls.

## Reproduce

```bash
git clone https://github.com/aidless/eval-gate.git && cd eval-gate
python3 -m pip install .
eval-gate demo        # all 10 scenarios, frozen expectations checked
eval-gate quickstart  # 4-scenario core subset
```

Verified locally on 2026-11-10: Python 3.12.3, eval-gate 0.2.0,
`10/10 符合预期`, quickstart `4/4 符合预期` (0.49s).

## Frozen suite results (demo, 10 scenarios)

| scenario | frozen verdict | measured verdict | pass_rate | delta vs baseline |
|---|---|---|---|---|
| p1_pass | PASS | PASS | 0.8917 | +0.0125 |
| p2_regression | BLOCK | BLOCK | 0.8063 | -0.0729 |
| p3_false_green | FAIL | FAIL | 0.7917 | +0.0000 |
| p4_tool_drift | BLOCK | BLOCK | 0.8917 | +0.0125 |
| p5_missing_evidence | INCOMPLETE | INCOMPLETE | — (evidence deleted by design) | — |
| p6_math_passk | error[pass@1] | ERROR | — (pass@1 vs pass@5 incomparable) | — |
| p7_code_hidden | REVIEW | REVIEW | 0.8000 | +0.0500 (n=120, MDE 5.55pp) |
| p8_rag_hard | FAIL | FAIL | 0.7458 | +0.0063 |
| p9_tool_multiturn | BLOCK | BLOCK | 0.9000 | +0.0187 |
| p10_judge_calibration | REVIEW | REVIEW | 0.8396 | -0.0500 (judge v1→v2 incomparable) |

Headline numbers for citation: the `p2_regression` pair 87.92% → 80.63%
(delta −7.29pp, 95% CI of delta [−0.0875, −0.0583], n=480) is the demo input for
"regression or noise?" — verdict `BLOCK`.

## Statistical parameters

- Wilson 95% CI; family-stratified paired bootstrap
- quickstart: 2,000 resamples, seed 20261103; `run`/`demo`: 10,000 resamples by default
- resampling unit: **questions**, not prediction rows
- verdict priority: `BLOCK > INCOMPLETE > FAIL > REVIEW > PASS`
- default tolerance: `--fail-on block`, `min_pass 0.80`

## Scope statement

These are frozen synthetic scenarios that exercise the decision rules, not a
benchmark of any published model. eval-gate consumes existing predictions; it does
not generate answers or replace eval frameworks (promptfoo / DeepEval / Ragas run
evals; eval-gate decides whether the delta exceeds noise and whether the change may
ship). Known limits and 20 failure modes (3 unguarded by design) are documented in
[FAILURE_MODES.md](../FAILURE_MODES.md); the statistical model, MDE and the
conditions under which verdicts are wrong are in [STATS_DESIGN.md](../STATS_DESIGN.md).
