# 历史结果与关键 Trajectory 索引

本目录只提交对方法审阅、复现或论文比较有价值的结果。大规模实验默认生成在 `analysis_results`，但只有本文件列出的精选内容会进入 Git。

## 结论边界

- `dataevolver_signal_only_latest_20260715_200927` 与 `optimized_dag_v1_20260716_040158` 是完整四股票、完整日期区间结果，可以复算其历史指标；但对应生成代码已经从当前主流程删除，只作为迭代档案。
- `full_llmcompiler_agent_eval_retry` 是旧 LLMCompiler 方法对照，当前项目不再包含该工作流代码。
- `ptc_ablation_smoke_20260716_182138` 只有 AMZN 2023-04-10 一个样本，只验证完整 LLM DAG、静态 PTC 和动态 PTC 能运行，并记录当次延迟；其 `SPR/CR/MDD/AV` 为空，不能用于交易性能结论。
- 不同历史版本的模型调用具有随机性。单日决策不同不代表某种方法在统计上更优。

## 迭代一：LLMCompiler 完整 Agent DAG

目录：`full_llmcompiler_agent_eval_retry`

保留内容：

- `decisions.csv`：旧方法全量决策；
- `decision_results_compact.csv`：精简决策；
- `full_run_stdout.log`：主运行日志；
- `AMZN/debug_runs/AMZN_2023-04-10_debug.json`：一条完整 trajectory；
- `position_pct_performance_final/`：最终 position_pct 回放指标；
- `technical_guard_performance/`：当时技术保护规则的对照指标；
- `buy_and_hold_baseline_final/`：buy-and-hold 指标。

用途：说明项目曾使用 LLMCompiler 生成/执行 Agent DAG，后续才转向 DataEvolver。它不是当前可运行入口。

## 迭代二：DataEvolver Signal-only

目录：`dataevolver_signal_only_latest_20260715_200927`

实验范围：AMZN、MSFT、NFLX、TSLA，2022-10-06 至 2023-04-10，共 508 个成功决策。

代表 trajectory：

| 文件 | 操作 | 用途 |
| --- | --- | --- |
| `debug_runs/AMZN_2022-10-06_debug.json` | HOLD 0% | 等待案例 |
| `debug_runs/AMZN_2022-10-07_debug.json` | SELL -100% | 退出案例 |
| `debug_runs/AMZN_2022-10-17_debug.json` | BUY 100% | 入场案例 |

Next-day-open 历史指标：

| Ticker | SPR | CR | MDD | AV |
| --- | ---: | ---: | ---: | ---: |
| AMZN | 0.252 | 4.618 | -22.530 | 26.536 |
| MSFT | 0.779 | 13.236 | -11.363 | 20.447 |
| NFLX | 0.904 | 19.243 | -13.475 | 27.101 |
| TSLA | 1.174 | 31.823 | -13.144 | 34.247 |
| Average | 0.777 | 17.230 | -15.128 | 27.083 |

注意：这是信号规则 DAG，不是当前四分析师 + 七 LLM Agent 系统。

## 迭代三：人工优化固定规则 DAG

目录：`optimized_dag_v1_20260716_040158`

该版本将 signal-only 规则扩展为：

```text
read_market_data -> trend_confirmation -> risk_gate -> position_sizing -> join
```

代表 trajectory：

| 文件 | 操作 | 用途 |
| --- | --- | --- |
| `debug_runs/AMZN_2022-10-06_debug.json` | HOLD 0% | 等待案例 |
| `debug_runs/AMZN_2022-10-07_debug.json` | SELL -100% | 快速退出案例 |
| `debug_runs/AMZN_2022-10-18_debug.json` | BUY 100% | 反弹入场案例 |

Next-day-open 历史平均指标为 `SPR=1.112`、`CR=21.642`、`MDD=-11.966`、`AV=22.602`。该版本是在 next-day-open 口径上人工调出的候选，不应解读为对其他执行口径普遍占优。详细说明见目录内 `EXPERIMENT_SUMMARY.md`。

注意：当前项目已删除该专用固定规则代码，只保留结果以记录“人工删层/改层”的历史方向。

## 迭代四：完整七 Agent DAG 与 PTC

目录：`ptc_ablation_smoke_20260716_182138`

三条 trajectory 使用相同股票和日期，适合直接比较执行结构：

| 模式 | Trajectory | 当次结果 | 耗时 | 执行层 |
| --- | --- | --- | ---: | ---: |
| baseline | `baseline/debug_runs/AMZN_2023-04-10_debug.json` | HOLD 0% | 170.889 秒 | 7 |
| static_ptc | `static_ptc/debug_runs/AMZN_2023-04-10_debug.json` | BUY 50% | 104.090 秒 | 6 |
| dynamic_ptc | `dynamic_ptc/debug_runs/AMZN_2023-04-10_debug.json` | HOLD 0% | 129.652 秒 | 6 |

该单样本中，static PTC 比 baseline 快约 39.1%，dynamic PTC 快约 24.1%。这是当次延迟观测，不是稳定性能估计。动态 case 选择的是 `mixed_evidence_dual_branch`，因此没有跳过多空 Agent；要验证动态删层收益，需要覆盖 risk-off 和 clean-bullish 日期的完整实验。

重点字段：

- `workflow.workflow_plan`：DataEvolver 计划；
- `workflow.workflow_outputs.dag_execution.program`：编译后的 PTC 程序；
- `workflow.workflow_outputs.dag_execution.execution_layers`：并行层；
- `workflow.workflow_outputs.dag_execution.call_trace`：实际工具调用/常量替换；
- `workflow.workflow_outputs.dag_execution.strategy`：动态路由策略；
- `workflow.final_decision`：最终决策。

## 为什么删除大量历史文件

本次从 Git 中移除了数百个重复逐日 trajectory、多次恢复/质量修复日志、空 stderr 和重复方法输出。保留原则是：

1. 每个关键方法至少有一个可审计 trajectory；
2. 有动作差异的方法尽量保留 BUY、SELL、HOLD 三种案例；
3. 完整实验保留 decisions、metrics、summary 和必要净值/成交数据；
4. smoke test 明确标注样本量和结论限制；
5. 不提交与分股票结果重复的超大 `all_results.json`。

指标复算命令和每个输出文件的详细说明见项目根目录 [README](../README.md)。
