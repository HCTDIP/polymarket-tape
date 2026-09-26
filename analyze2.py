#!/usr/bin/env python3
"""校准审计 v2 —— 修掉 v1 的两个方法学错误。

v1 的错（必须记下来）：
  ① **样本不独立**：一个事件会拆出十几个「X 会赢吗」子市场，它们高度相关。
     v1 把这 95 个当成 95 个独立观测 → 把一个事件的错价放大成"系统性错价"。
  ② **没过滤薄市场**：volume=62 的市场和 volume=千万 的市场同权。

v2 做法：
  · 按事件家族（events[0].id / slug 前缀）聚类 → 家族内只算一次（取该家族成交量最大的子市场代表）
  · 加最小成交量门槛（默认 $1000）
  · 同一套 Brier + 校准曲线，分「全部 / 去相关 / 去相关+有量」三档对照
"""
import argparse
import collections
import datetime
import json
import pathlib

ROOT = pathlib.Path("/var/minis/workspace/polymarket")
LEADS = [("14d", 14 * 86400), ("7d", 7 * 86400), ("3d", 3 * 86400),
         ("1d", 86400), ("6h", 6 * 3600), ("1h", 3600)]


def ep(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def price_at(h, t, tol):
    best = None
    for pt in h:
        try:
            tt, pp = float(pt[0]), float(pt[1])
        except Exception:
            continue
        if tt <= t and (best is None or tt > best[0]):
            best = (tt, pp)
    if best is None or (t - best[0]) > tol:
        return None
    return best[1]


def brier(rows):
    return sum((p - y) ** 2 for p, y in rows) / len(rows)


def maj(rows):
    r = sum(y for _, y in rows) / len(rows)
    b = 1.0 if r >= 0.5 else 0.0
    return sum((b - y) ** 2 for _, y in rows) / len(rows)


def calib(rows, k=10):
    out = []
    for i in range(k):
        lo, hi = i / k, (i + 1) / k
        g = [(p, y) for p, y in rows if lo <= p < hi]
        if g:
            out.append((f"{lo:.1f}-{hi:.1f}", len(g),
                        sum(p for p, _ in g) / len(g), sum(y for _, y in g) / len(g)))
    return out


def load_meta():
    mk = {}
    f = sorted((ROOT / "data").glob("markets_resolved_*.jsonl"))[-1]
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            try:
                m = json.loads(line)
            except Exception:
                continue
            fam = None
            try:
                ev = m.get("events") or []
                if ev:
                    fam = str(ev[0].get("id") or ev[0].get("slug") or "")
            except Exception:
                pass
            if not fam:
                fam = str(m.get("slug") or m.get("id"))
                fam = fam.rsplit("-", 1)[0]
            mk[m["id"]] = {"fam": fam, "vol": float(m.get("volume") or 0),
                           "liq": float(m.get("liquidity") or 0)}
    return mk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-volume", type=float, default=1000)
    ap.add_argument("--out", default=str(ROOT / "校准审计报告-v2.md"))
    a = ap.parse_args()

    mk = load_meta()
    recs = []
    with open(sorted((ROOT / "data").glob("prices_*.jsonl"))[-1], encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("history") and r["market_id"] in mk:
                r["fam"] = mk[r["market_id"]]["fam"]
                r["vol"] = mk[r["market_id"]]["vol"]
                recs.append(r)

    fams = collections.Counter(r["fam"] for r in recs)
    multi = [f for f, c in fams.items() if c > 1]
    print(f"市场 {len(recs)} 个｜事件家族 {len(fams)} 个｜多子市场家族 {len(multi)} 个"
          f"（占市场 {sum(fams[f] for f in multi)} 个）")

    lines = ["# Polymarket 校准审计报告 · v2（去相关 + 去薄市场）", "",
             f"- 市场 {len(recs)} 个｜事件家族 {len(fams)} 个｜家族内多子市场占 {sum(fams[f] for f in multi)} 个",
             f"- 成交量门槛：${a.min_volume:,.0f}", ""]

    for label, sel in [("A 全部市场（v1 口径，含相关样本）", lambda r: True),
                       ("B 去相关（每家族取成交量最大的子市场）", "dedup"),
                       ("C 去相关 + 有量市场", "dedup_vol")]:
        if sel == "dedup":
            best = {}
            for r in recs:
                if r["fam"] not in best or r["vol"] > best[r["fam"]]["vol"]:
                    best[r["fam"]] = r
            pool = list(best.values())
        elif sel == "dedup_vol":
            best = {}
            for r in recs:
                if r["vol"] >= a.min_volume and (r["fam"] not in best or r["vol"] > best[r["fam"]]["vol"]):
                    best[r["fam"]] = r
            pool = list(best.values())
        else:
            pool = recs
        lines += [f"## {label}（{len(pool)} 个市场）", "",
                  "| 距结算 | 样本 | Brier | 多数类基线 | 优于基线 |", "|---|---|---|---|---|"]
        print(f"\n■ {label}｜{len(pool)} 个市场")
        for name, secs in LEADS:
            rows = []
            for r in pool:
                ct = ep(r.get("closed_time"))
                if not ct:
                    continue
                p = price_at(r["history"], ct - secs, max(secs, 2 * 86400))
                if p is None:
                    continue
                rows.append((p, r["outcome_yes"]))
            if len(rows) < 20:
                continue
            b, mb = brier(rows), maj(rows)
            lines.append(f"| {name} | {len(rows)} | {b:.4f} | {mb:.4f} | {'✅' if b < mb - 1e-9 else '❌'} |")
            print(f"   {name:>4} n={len(rows):<5} Brier={b:.4f}  基线={mb:.4f}  {'✅' if b<mb else '❌'}")

    # 校准曲线：B 档 3d
    best = {}
    for r in recs:
        if r["fam"] not in best or r["vol"] > best[r["fam"]]["vol"]:
            best[r["fam"]] = r
    pool = [r for r in best.values() if r["vol"] >= a.min_volume]
    rows = []
    for r in pool:
        ct = ep(r.get("closed_time"))
        if not ct:
            continue
        p = price_at(r["history"], ct - 3 * 86400, 3 * 86400)
        if p is not None:
            rows.append((p, r["outcome_yes"]))
    lines += ["", f"## 校准曲线（去相关 + 有量 · 距结算 3 天 · n={len(rows)}）", "",
              "| p 区间 | 条数 | 预测均值 | 实际发生 | 偏差 |", "|---|---|---|---|---|"]
    print(f"\n■ 校准曲线（去相关+有量，3d，n={len(rows)}）")
    for bn, n, pm, ob in calib(rows):
        d = ob - pm
        fl = "✅" if abs(d) <= 0.05 else ("⚠️" if abs(d) <= 0.15 else "❌")
        lines.append(f"| {bn} | {n} | {pm:.3f} | {ob:.3f} | {d:+.3f} {fl} |")
        print(f"   {bn:>7} n={n:<4} 预测{pm:.3f} 实际{ob:.3f} 偏差{d:+.3f} {fl}")

    pathlib.Path(a.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n→ 已写 {a.out}")


if __name__ == "__main__":
    main()
