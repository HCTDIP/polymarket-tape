#!/usr/bin/env python3
"""校准审计第一版：拿真金白银的结算市场算「市场当时说的概率」准不准。

数据：prices_*.jsonl（每个已结算市场的 YES 价格轨迹 + 最终真值）
做法：取结算前若干时点的市场概率 p，配最终结果 y∈{0,1}，算
      · Brier score（越低越好）
      · 校准曲线（分桶：说了 x% 的，真实发生几成）
      · 与两个基线对比（全猜 0.5 / 全猜多数类）—— 赢不了基线就是没本事
输出：打印 + 写 report.md
"""
import argparse
import collections
import datetime
import json
import pathlib
import statistics

ROOT = pathlib.Path("/var/minis/workspace/polymarket")
LEADS = [("30d", 30 * 86400), ("14d", 14 * 86400), ("7d", 7 * 86400),
         ("3d", 3 * 86400), ("1d", 86400), ("6h", 6 * 3600), ("1h", 3600)]


def epoch(iso):
    try:
        return datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def price_at(hist, target_ts, tolerance):
    """取 target_ts 之前最近的一个点位；太久远（超过 tolerance）视为缺失。"""
    best = None
    for t, p in hist:
        try:
            t = float(t); p = float(p)          # 有的点位 t 是字符串
        except (TypeError, ValueError):
            continue
        if t <= target_ts and (best is None or t > best[0]):
            best = (t, p)
    if best is None or (target_ts - best[0]) > tolerance:
        return None
    return float(best[1])


def brier(rows):
    return sum((p - y) ** 2 for p, y in rows) / len(rows)


def majority_baseline(rows):
    ones = sum(y for _, y in rows) / len(rows)
    base = 1.0 if ones >= 0.5 else 0.0
    return sum((base - y) ** 2 for _, y in rows) / len(rows)


def calib_table(rows, bins=10):
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        grp = [(p, y) for p, y in rows if lo <= p < hi or (i == bins - 1 and p >= hi - 1e-9 and p <= 1)]
        if grp:
            pm = sum(p for p, _ in grp) / len(grp)
            ob = sum(y for _, y in grp) / len(grp)
            out.append((f"{lo:.1f}-{hi:.1f}", len(grp), pm, ob, ob - pm))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None)
    ap.add_argument("--out", default=str(ROOT / "校准审计报告.md"))
    a = ap.parse_args()

    f = pathlib.Path(a.file) if a.file else sorted((ROOT / "data").glob("prices_*.jsonl"))[-1]
    recs = []
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("history"):
                recs.append(r)
    print(f"数据：{f.name}｜有点位市场 {len(recs)} 个")
    ys = [r["outcome_yes"] for r in recs]
    print(f"结果分布：YES {sum(ys)} / NO {len(ys)-sum(ys)}（YES 率 {sum(ys)/len(ys):.3f}）")

    # 逐时点
    lines = ["# Polymarket 校准审计报告 · 第一版", "",
             f"- 数据：`{f.name}`（{len(recs)} 个已结算市场）",
             f"- 结果分布：YES {sum(ys)} / NO {len(ys)-sum(ys)}（基准 YES 率 {sum(ys)/len(ys):.3f}）", "",
             "## ① 各时点：市场概率 vs 真实结果", "",
             "| 距结算 | 样本 | Brier | 全猜0.5基线 | 猜多数类基线 | 结论 |",
             "|---|---|---|---|---|---|"]
    per_lead = {}
    for name, secs in LEADS:
        rows = []
        for r in recs:
            ct = epoch(r.get("closed_time"))
            if not ct:
                continue
            p = price_at(r["history"], ct - secs, tolerance=max(secs, 2 * 86400))
            if p is None:
                continue
            rows.append((p, r["outcome_yes"]))
        if len(rows) < 30:
            continue
        b = brier(rows); mb = majority_baseline(rows)
        verdict = "✅ 优于多数类基线" if b < mb - 1e-9 else "❌ 不如多数类基线（这批样本证明不了本事）"
        per_lead[name] = rows
        lines.append(f"| {name} | {len(rows)} | {b:.4f} | 0.2500 | {mb:.4f} | {verdict} |")
        print(f"  {name:>4}: n={len(rows):<5} Brier={b:.4f}  多数类基线={mb:.4f}  {'OK' if b<mb else 'BEAT-BY-BASELINE'}")

    # 校准曲线（取样本最多的那个时点）
    if per_lead:
        key = max(per_lead, key=lambda k: len(per_lead[k]))
        rows = per_lead[key]
        lines += ["", f"## ② 校准曲线（距结算 {key}，样本 {len(rows)}）", "",
                  "| p 区间 | 条数 | 预测均值 | 实际发生 | 偏差 |", "|---|---|---|---|---|"]
        for b_, n, pm, ob, d in calib_table(rows):
            flag = "✅" if abs(d) <= 0.05 else ("⚠️" if abs(d) <= 0.15 else "❌")
            lines.append(f"| {b_} | {n} | {pm:.3f} | {ob:.3f} | {d:+.3f} {flag} |")
            print(f"  {b_:>7}: n={n:<4} 预测{pm:.3f} 实际{ob:.3f} 偏差{d:+.3f} {flag}")

    pathlib.Path(a.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n→ 已写 {a.out}")


if __name__ == "__main__":
    main()
