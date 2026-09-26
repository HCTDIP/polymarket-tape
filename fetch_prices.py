#!/usr/bin/env python3
"""抓每个已结算市场的价格轨迹（CLOB 公开只读）→ 监督数据集。

为什么是这个数据：
    每个市场 = 一行「市场当时说的概率 p(t)」+ 一行「最终真值 0/1」。
    这正是校准审计需要的配对：p 与 outcome 同源、可复算、有时间戳。

数据源:
    GET https://clob.polymarket.com/prices-history?market=<YES token id>&interval=max&fidelity=60
    token id 来自 Gamma 的 clobTokenIds[0]（YES 侧）

用法:
    python3 fetch_prices.py --days 60 --workers 6
"""
import argparse
import datetime
import json
import pathlib
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path("/var/minis/workspace/polymarket")
OUT = ROOT / "data"
CLOB = "https://clob.polymarket.com/prices-history"
LOCK = threading.Lock()


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "jev-audit/0.1"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(4 * (i + 1)); continue
            return None
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def yes_token(m):
    try:
        return json.loads(m.get("clobTokenIds") or "[]")[0]
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--fidelity", type=int, default=60, help="分钟粒度")
    a = ap.parse_args()

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=a.days)
    mfile = sorted(OUT.glob("markets_resolved_*.jsonl"))[-1]
    markets = []
    with open(mfile, encoding="utf-8") as fh_in:          # 流式，不整文件读入
        for line in fh_in:
            try:
                m = json.loads(line)
            except Exception:
                continue
            ct = m.get("closedTime") or m.get("endDate")
            try:
                t = datetime.datetime.fromisoformat(str(ct).replace("Z", "+00:00"))
            except Exception:
                continue
            tok = yes_token(m)          # 从 raw market 提 YES token
            if t >= cutoff and tok:
                markets.append({                       # 只留必要字段，砍掉 90% 体积
                    "id": m["id"], "conditionId": m.get("conditionId"),
                    "question": (m.get("question") or "")[:200], "category": m.get("category"),
                    "volume": m.get("volume"), "liquidity": m.get("liquidity"),
                    "closedTime": ct, "endDate": m.get("endDate"),
                    "outcomePrices": m.get("outcomePrices"), "tok": tok,
                })
            del m

    pf = OUT / f"prices_{a.days}d.jsonl"
    done = set()
    if pf.exists():
        with open(pf, encoding="utf-8") as fh_d:      # 流式读已完成列表
            for line in fh_d:
                try:
                    done.add(json.loads(line)["market_id"])
                except Exception:
                    pass
    todo = [m for m in markets if m["id"] not in done]
    print(f"目标市场 {len(markets)} 个｜已完成 {len(done)}｜本轮待抓 {len(todo)}｜粒度 {a.fidelity}min")

    fh = open(pf, "a", encoding="utf-8")
    n_ok = n_bad = 0

    def work(m):
        nonlocal n_ok, n_bad
        tok = m["tok"]
        url = f"{CLOB}?market={tok}&interval=max&fidelity={a.fidelity}"
        d = get(url)
        pts = (d or {}).get("history") or []
        rec = {
            "market_id": m["id"], "condition_id": m.get("conditionId"),
            "question": (m.get("question") or "")[:300], "category": m.get("category"),
            "volume": m.get("volume"), "liquidity": m.get("liquidity"),
            "closed_time": m.get("closedTime") or m.get("endDate"),
            "end_date": m.get("endDate"),
            "outcome_prices": m.get("outcomePrices"),
            "outcome_yes": 1 if '"1"' in str(m.get("outcomePrices")) and str(m.get("outcomePrices")).startswith('["1') else 0,
            "n_points": len(pts),
            "history": [[x.get("t"), x.get("p")] for x in pts],
        }
        with LOCK:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if pts:
                n_ok += 1
            else:
                n_bad += 1
            if (n_ok + n_bad) % 50 == 0:
                fh.flush()
                print(f"  进度 {n_ok+n_bad}/{len(todo)}｜有点位 {n_ok}｜空 {n_bad}", flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(work, todo))
    fh.close()
    size = pf.stat().st_size
    print(f"\n完成：{pf}")
    print(f"  有点位 {n_ok}｜空 {n_bad}｜文件 {size/1048576:.2f} MB")


if __name__ == "__main__":
    main()
