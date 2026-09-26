#!/usr/bin/env python3
"""抓 Polymarket 已结算市场（免密钥，Gamma API 公开只读）。

用途：给"校准审计"准备真值数据集 —— 每个已结算市场 = 一行「当时市场说 p，后来真实结果 0/1」。

用法:
    python3 fetch_markets.py --days 60            # 抓近 60 天已结算市场
    python3 fetch_markets.py --days 60 --pages 40 # 限制页数（每页 100 条）
"""
import argparse
import datetime
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

API = "https://gamma-api.polymarket.com/markets"
OUT = pathlib.Path("/var/minis/workspace/polymarket/data")
PAGE = 100          # Gamma API 单页上限


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "jev-audit/0.1"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read())
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            if i == tries - 1:
                print(f"  [warn] {e}", file=sys.stderr)
                return []
            time.sleep(2 * (i + 1))
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--pages", type=int, default=0, help="0=不限")
    a = ap.parse_args()

    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=a.days))
    cutoff_s = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    OUT.mkdir(parents=True, exist_ok=True)
    day = datetime.datetime.now().strftime("%Y%m%d")
    path = OUT / f"markets_resolved_{day}.jsonl"

    seen = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(json.loads(line)["id"])
            except Exception:
                pass
    print(f"起点：已有 {len(seen)} 条｜时间窗：{cutoff_s} 之后结算")

    offset, saved, pages = 0, 0, 0
    with open(path, "a", encoding="utf-8") as f:
        while True:
            url = f"{API}?limit={PAGE}&offset={offset}&closed=true&order=endDate&ascending=false"
            batch = get(url)
            if not batch:
                print("  页面为空 → 收尾")
                break
            oldest = None
            for m in batch:
                end = str(m.get("endDate") or "")
                oldest = end or oldest
                if end and end < cutoff_s:
                    continue
                if m["id"] in seen:
                    continue
                seen.add(m["id"])
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
                saved += 1
            f.flush()
            pages += 1
            print(f"  页{pages:>3} offset={offset:>6} 新增{saved:>5} 最新={oldest}")
            if a.pages and pages >= a.pages:
                print("  达到页数上限 → 停")
                break
            if oldest and oldest < cutoff_s:
                print("  已越过时间窗 → 停")
                break
            offset += PAGE
            time.sleep(0.4)

    size = path.stat().st_size
    print(f"\n结果：{path}")
    print(f"  本轮新增 {saved} 条｜文件总计 {len(seen)} 条｜{size/1048576:.2f} MB")


if __name__ == "__main__":
    main()
