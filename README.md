# Polymarket 结算真值数据集

**用途**：给「决策校准审计」提供真值 —— 每个已结算市场 = 一行「当时市场说的概率 p(t)」+ 一行「最终真值 0/1」。

## 数据
| 文件 | 内容 |
|---|---|
| `data/markets_resolved_*.jsonl.gz` | 已结算市场全量元数据（含 outcomes / clobTokenIds / 成交量 / 结算时间） |
| `data/prices_*d.jsonl.gz` | 每个市场的 YES 价格轨迹（`history: [[t, p], ...]`）+ 结算结果 |

数据源：Polymarket 公开只读接口（Gamma `/markets`、CLOB `/prices-history`），**不需要密钥**。

## 方法学（重要）
v1 犯过两个错，v2 修正 —— 留档提醒：
1. **样本不独立**：一个事件会拆成十几个「X 会赢吗」子市场，高度相关 → 必须按事件家族去重
2. **未过滤薄市场**：volume=62 的市场与 volume=千万 同权 → 加成交量门槛

## 复现
```
python3 fetch_markets.py --days 60     # 抓已结算市场
python3 fetch_prices.py  --days 60     # 抓价格轨迹（真值配对）
python3 analyze2.py                    # 出校准报告（去相关 + 去薄市场）
```
