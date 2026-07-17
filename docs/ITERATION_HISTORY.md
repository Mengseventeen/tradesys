# TradeSys 关键迭代记录

本文记录项目从旧 DAG 生成方法到当前动态 PTC 系统的关键技术轨迹。历史代码已被清理时，本文只描述当时方法，并链接保留下来的结果证据。

## 1. LLMCompiler：程序字符串生成 DAG

早期版本要求模型输出类似 `$id = function(...)` 的动作，通过正则解析变量引用并构造依赖，最终强制 `join`。该方向验证了“让模型生成工具调用程序”的可行性，但程序字符串解析、修复和重试成本较高。

保留证据：

- `analysis_results/full_llmcompiler_agent_eval_retry/full_run_stdout.log`
- `analysis_results/full_llmcompiler_agent_eval_retry/AMZN/debug_runs/AMZN_2023-04-10_debug.json`
- `analysis_results/full_llmcompiler_agent_eval_retry/position_pct_performance_final/`

当前状态：工作流代码已删除，只保留历史结果对照。

## 2. DataEvolver：通过约束搜索构建交易 DAG

DataEvolver 引入数据理解、free fitting、template combination 和 constrained search 阶段。模型不再直接输出任意程序，而是在已注册交易算子和依赖约束中生成 DAG，再经过校验和修复。

这一阶段的全量 signal-only 结果使用简化规则 DAG，产生了完整四股票、508 条决策。它证明了回放与指标链路，但不属于真正的七 LLM Agent 多 Agent系统。

保留证据：

- `analysis_results/dataevolver_signal_only_latest_20260715_200927/RUN_LOG.md`
- BUY、SELL、HOLD 三个 trajectory
- 完整 `decisions.csv` 与 next-day-open 回测文件

## 3. 人工优化固定 DAG：加入趋势、风险和仓位层

为了验证增加或替换 DAG 层的效果，项目曾实现固定规则：

```text
read_market_data -> trend_confirmation -> risk_gate -> position_sizing -> join
```

该版本在当时的 next-day-open 数据上改善了平均 SPR、CR、MDD 和 AV，但属于人工规则优化，并且专用代码后来被删除。它是未来 `manual profile` 消融实验的历史原型，而不是当前核心方法。

保留证据：

- `analysis_results/optimized_dag_v1_20260716_040158/EXPERIMENT_SUMMARY.md`
- `analysis_results/optimized_dag_v1_20260716_040158/RUN_LOG.md`
- BUY、SELL、HOLD 三个 trajectory
- 完整决策与 next-day-open 指标

## 4. 恢复完整多 Agent 系统

项目收敛为四分析师 LangGraph 加完整 DataEvolver 七算子 LLM DAG：

```text
四分析师 -> read_market_data -> bullish/bearish -> disagreement
        -> risk_management -> position_sizing -> join
```

四分析师负责证据整理，七个交易算子各自由 LLM Agent 执行并进行质量评价/修订。这个版本解决了“最好历史结果其实不是多 Agent 系统”的方法错位问题。

## 5. 分析师数据收集 PTC

四分析师原先可能多轮选择小工具，造成重复工具往返。优化后，每个分析师只暴露一个程序化数据收集工具：

- 技术 PTC 批量获取价格和指标；
- 基本面 PTC 批量获取报表、盈利与申报材料；
- 新闻 PTC 合并个股和全局新闻；
- 政策 PTC 合并宏观与政策数据。

每个程序只读本地数据，返回压缩证据和调用 trace。

## 6. 静态 PTC：受限 IR 与依赖就绪并行

完整七算子 DAG 被编译为 `ptc-ir-v1`。运行时只允许 `tool_call` 和 `constant`，并校验算子白名单、依赖、环、输入输出 schema 和最终决策。

静态 PTC 不改变 Agent 集合，只让 `bullish_signal` 和 `bearish_signal` 等依赖就绪节点并行。因此它用于分离“执行并行”与“动态删 Agent”两种收益。

保留证据：

- `analysis_results/ptc_ablation_smoke_20260716_182138/static_ptc/`

## 7. 动态 PTC：根据市场状态选择 Agent

动态编译器根据技术、基本面、新闻和政策 profile 选择：

- risk-off：看跌分支；
- clean bullish：看涨分支；
- mixed evidence：完整多空分支。

被跳过的节点不会完全从 schema 中消失，而是替换为带有 `ptc_skipped=true` 的合法常量输出，使下游 risk、position 和 join 保持统一接口。

保留证据：

- `analysis_results/ptc_ablation_smoke_20260716_182138/dynamic_ptc/`

单日 smoke case 恰好走 `mixed_evidence_dual_branch`，没有展示实际删层。后续全量实验需要统计三类路由频率和每条路由的调用节省。

## 8. 下一步：手动 Profile 与动态路由消融

下一阶段建议在同一个 PTC 编译器中增加人工 profile：

- `full`：多空 + disagreement；
- `bull_only`：仅看涨分支；
- `bear_only`：仅看跌分支；
- `dual_no_disagreement`：多空分支但删除分歧 Agent；
- `dynamic`：由市场状态选择。

所有 case 必须使用相同股票、日期、模型配置、仓位限制、next-day-open 执行和手续费，再同时比较 SPR、CR、MDD、AV、运行时间、工具调用、跳过 Agent、错误率和路由分布。

## 9. 版本与证据对应

| 迭代 | 当前代码可运行 | 完整历史指标 | 代表 trajectory |
| --- | --- | --- | --- |
| LLMCompiler | 否 | 是 | 1 个 |
| DataEvolver signal-only | 否 | 是 | BUY/SELL/HOLD 各 1 个 |
| 人工优化固定 DAG | 否 | 是 | BUY/SELL/HOLD 各 1 个 |
| 完整七 Agent baseline | 是 | 仅单日 smoke | 1 个 |
| static PTC | 是 | 仅单日 smoke | 1 个 |
| dynamic PTC | 是 | 仅单日 smoke | 1 个 |

该表用于防止把“历史上有完整指标的旧规则方法”和“当前有完整架构但尚未跑完全量的动态方法”混为一谈。
