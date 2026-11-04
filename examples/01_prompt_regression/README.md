# 用例 1：prompt 改动导致真实回退

**你会得到什么结论**：`BLOCK`。候选比基线少过 35 题，配对 delta 是 −7.29pp，95% CI `[-8.75pp, -5.83pp]`；整段区间都在 −3% 容差之外，不是抽样噪声。

```bash
./run.sh
```

真实输出：

```
verdict=BLOCK pass_rate=0.8063 ci=[0.7685, 0.8391] delta=-0.0729 delta_ci=[-0.0875, -0.0583] n=480
exit=1
```

打开 `runs/regression/attribution.md`，可以看到：

- 回退集中在 `grounding` family：候选答案引用了不存在的 doc_id。
- 基线通过率 87.92%，候选 80.63%；`n=480`，CI 宽度约 7pp，满足功效门禁。
- 改动文件 `prompts/grounding.md` 被写进归因表的“疑似原因”。

这个用例回答的问题是：**分数降了 7 个点，是模型真的变差，还是题抽得不好？** 这里两者都不是：是 prompt 让 grounding 层掉了。

数据为合成（480 题、20 family），但回退模式与真实 support QA prompt 改动一致。
