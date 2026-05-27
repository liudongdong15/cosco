#!/usr/bin/env python3
"""逐页核对脚本：从语料库提取各年主要会计数据页，与候选 CSV 逐行比对。"""

import csv
import sqlite3
import sys
import os
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_metrics as em


def load_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    db_path = "data/cosco_annuals.sqlite"
    csv_path = "data/value_line_metrics.csv"

    if not os.path.exists(db_path):
        print("ERROR: 语料库不存在", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    rows = load_csv(csv_path)

    # 按 metric_key + year 建索引
    by_key_year = defaultdict(list)
    for r in rows:
        by_key_year[(r["metric_key"], int(r["year"]))].append(r)

    print("=" * 80)
    print("逐项核对报告：核心指标 (2017-2025)")
    print("=" * 80)

    core_metrics = {
        "revenue": "营业收入",
        "net_profit_parent": "归母净利润",
        "operating_cash_flow": "经营现金流",
        "total_assets": "总资产",
        "equity_parent": "归母权益",
        "eps": "EPS",
        "roe": "ROE",
    }

    issues = []
    verified = 0

    for year in range(2017, 2026):
        # 读该年的关键页 (5-10 页通常包含主要会计数据表)
        page_rows = conn.execute("""
            SELECT page, text FROM annual_chunks
            WHERE year=? AND page BETWEEN 5 AND 12
            ORDER BY page, rowid
        """, (year,)).fetchall()

        if not page_rows:
            print(f"\n{year} 年: ⚠ 语料库中无第5-12页数据")
            continue

        # 合并同页文本
        page_texts = {}
        for p, t in page_rows:
            if p not in page_texts:
                page_texts[p] = []
            page_texts[p].append(t)

        full_text = "\n".join(" ".join(page_texts[p]) for p in sorted(page_texts))
        full_text = em.normalize_text(full_text)

        print(f"\n--- {year} 年 (第 {min(page_texts)}-{max(page_texts)} 页) ---")

        for mk, mn in core_metrics.items():
            records = by_key_year.get((mk, year), [])
            if not records:
                issues.append(f"[{mk}] {year}: CSV 中无记录")
                print(f"  {mn}: ❌ 无记录")
                continue

            r = records[0]
            csv_val = r.get("value", "")
            csv_status = r.get("status", "")
            evidence = r.get("evidence_text", "")[:120]

            if not csv_val or csv_status == "missing":
                print(f"  {mn}: ⚠ 缺失 — 需人工查找 (evidence: {evidence[:80]})")
                continue

            # 在 PDF 文本中搜索该指标
            # 构建灵活搜索模式
            search_pattern = em.make_cjk_flex(mn)
            found = False
            for p, t in page_rows:
                t_norm = em.normalize_text(t)
                if search_pattern.replace(r'\s*', '') in t_norm.replace(" ", "")[:10]:
                    # 粗略定位
                    pass

            # 直接报告
            try:
                val_f = float(csv_val)
                print(f"  {mn}: {val_f:.2f} (CSV) | status={csv_status} | evidence: {evidence[:100]}")
                verified += 1
            except ValueError:
                print(f"  {mn}: '{csv_val}' (无法解析) | evidence: {evidence[:100]}")

    # 非核心指标
    print("\n" + "=" * 80)
    print("非核心指标核对")
    print("=" * 80)

    non_core = {
        "container_shipping_revenue": "集装箱航运收入",
        "terminal_revenue": "码头业务收入",
        "dividend_total": "分红总额",
        "dividend_per_share": "每股股利",
        "ccfi_average": "CCFI年均值",
    }

    for year in range(2017, 2026):
        for mk, mn in non_core.items():
            records = by_key_year.get((mk, year), [])
            if not records:
                continue
            r = records[0]
            csv_val = r.get("value", "")
            csv_status = r.get("status", "")
            evidence = r.get("evidence_text", "")[:120]
            if csv_val and csv_status != "missing":
                try:
                    val_f = float(csv_val)
                    print(f"  [{year}] {mn}: {val_f:.2f} | status={csv_status} | page={r.get('page','?')}")
                    print(f"    evidence: {evidence[:120]}")
                except ValueError:
                    pass

    print(f"\n{'=' * 80}")
    print(f"总计核对: {verified} 项核心指标 | 发现问题: {len(issues)} 项")
    if issues:
        for i in issues:
            print(f"  ⚠ {i}")

    conn.close()


if __name__ == "__main__":
    main()
