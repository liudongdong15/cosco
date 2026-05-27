#!/usr/bin/env python3
"""validate_metrics.py — 校验候选指标表，生成审核版 CSV。"""

import argparse
import csv
import os
import sys
from urllib.parse import urlparse
from typing import Dict, List, Optional, Set, Tuple


# 核心指标：必须全部审核通过才能生成报告
CORE_METRICS = {
    "revenue", "net_profit_parent", "operating_cash_flow",
    "total_assets", "equity_parent", "eps", "roe",
}

# 预期取值范围（用于合理性校验）
SANITY_RANGES = {
    "revenue": (100, 10000),            # 亿元
    "net_profit_parent": (-500, 3000),  # 亿元
    "operating_cash_flow": (-500, 5000),  # 亿元
    "total_assets": (500, 10000),       # 亿元
    "equity_parent": (100, 5000),       # 亿元
    "eps": (-10, 50),                   # 元/股
    "roe": (-100, 200),                 # %
    "container_shipping_revenue": (10, 10000),  # 亿元
    "terminal_revenue": (0.5, 500),     # 亿元
    "dividend_total": (0, 600),         # 亿元
    "dividend_per_share": (0, 5),       # 元/股
    "ccfi_average": (600, 3500),        # 点
}

FIELDS = [
    "metric_key", "metric_name", "year", "value", "unit",
    "source_type", "source_file", "page", "source_url", "evidence_text",
    "confidence", "status", "note",
]

SOURCE_URL_SCHEMES = {"http", "https", "file"}


def is_valid_source_url(value: str) -> bool:
    """Return True for reproducible external source references."""
    value = (value or "").strip()
    if not value:
        return False

    parsed = urlparse(value)
    if parsed.scheme in SOURCE_URL_SCHEMES and parsed.path:
        return True

    # Accept executable data-fetch references used by local ingestion scripts.
    return value.startswith("akshare.") and "(" in value and ")" in value


def load_rows(path: str) -> List[Dict]:
    """加载候选指标表 CSV。"""
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def validate_metrics(rows: List[Dict], start_year: int, end_year: int) -> Tuple[List[Dict], List[str]]:
    """校验候选指标，返回 (审核版行列表, 错误列表)。"""
    errors: List[str] = []
    reviewed: Dict[Tuple[str, int], Dict] = {}
    warnings: List[str] = []

    for r in rows:
        mk = r["metric_key"]
        year = int(r["year"])
        key = (mk, year)
        value_str = r.get("value", "")

        # 规则 1: 缺失值保留为 missing
        if r["status"] == "missing":
            if key not in reviewed:
                reviewed[key] = dict(r)
                reviewed[key]["status"] = "missing"
            continue

        # 规则 2: 必须有 value
        if not value_str or value_str.strip() == "":
            if mk in CORE_METRICS:
                errors.append(f"[{mk}] {year}: 核心指标缺失值")
                reviewed[key] = dict(r)
                reviewed[key]["status"] = "missing"
                reviewed[key]["note"] = (reviewed[key].get("note", "") + " 核心指标缺失值").strip()
            else:
                warnings.append(f"[{mk}] {year}: 非核心指标缺失值，标记为 missing")
                reviewed[key] = dict(r)
                reviewed[key]["status"] = "missing"
            continue

        try:
            value = float(value_str)
        except (ValueError, TypeError):
            errors.append(f"[{mk}] {year}: 无法解析数值 '{value_str}'")
            reviewed[key] = dict(r)
            reviewed[key]["status"] = "missing"
            continue

        # 规则 3: 同一 metric_key + year 只能有一条 reviewed 记录
        if key in reviewed:
            errors.append(f"[{mk}] {year}: 存在重复候选记录")
            reviewed[key]["status"] = "conflict"
            reviewed[key]["note"] = (reviewed[key].get("note", "") + " 重复候选值").strip()
            continue

        # 规则 4: 必须有 source_file 和 page (年报来源)
        if r["source_type"] == "annual_report":
            if not r.get("source_file") or not r.get("page"):
                errors.append(f"[{mk}] {year}: 年报来源缺少文件或页码")
                r["status"] = "candidate"
                r["note"] = (r.get("note", "") + " 缺少来源引用").strip()
                reviewed[key] = dict(r)
                continue

        # 规则 4b: 外部数据源必须有可复核的 source_url/source reference
        if r["source_type"] == "external":
            if not is_valid_source_url(r.get("source_url", "")):
                errors.append(f"[{mk}] {year}: 外部数据 source_url 不可复核")
                r["status"] = "candidate"
                r["note"] = (r.get("note", "") + " source_url不可复核").strip()
                reviewed[key] = dict(r)
                continue

        # 规则 5: 合理性校验 (high confidence 时校验范围)
        if r["confidence"] == "high" and mk in SANITY_RANGES:
            lo, hi = SANITY_RANGES[mk]
            if not (lo <= value <= hi):
                warnings.append(
                    f"[{mk}] {year}: 数值 {value} 超出预期范围 [{lo}, {hi}]"
                )
                r["confidence"] = "medium"
                r["note"] = (r.get("note", "") + f" 值{value}超出预期范围").strip()

        # 规则 6: unit 记录
        if not r.get("unit"):
            errors.append(f"[{mk}] {year}: 缺少单位")
            r["status"] = "candidate"
            reviewed[key] = dict(r)
            continue

        # 状态判定：已人工审核通过 → 保持；核心高置信度 → 自动通过；其余 → 待复核
        if r.get("status") == "reviewed":
            pass  # 人工已审核，保持 reviewed
        elif r["confidence"] == "high" and mk in CORE_METRICS:
            r["status"] = "reviewed"
            if "从文本" in r.get("note", ""):
                r["note"] = r["note"].replace("从文本描述中抽取，需人工复核", "规则抽取+自动审核通过")
        else:
            # 保持 candidate，待人工复核
            r["status"] = "candidate"

        reviewed[key] = dict(r)

    # 规则 7: 检查核心指标是否全部覆盖
    missing_core = []
    for year in range(start_year, end_year + 1):
        for mk in CORE_METRICS:
            key = (mk, year)
            if key not in reviewed or reviewed[key].get("status") in ("missing", "candidate", "conflict"):
                missing_core.append(f"[{mk}] {year}")

    if missing_core:
        errors.append(
            f"核心指标存在未审核通过项 ({len(missing_core)} 个): {', '.join(missing_core[:10])}"
            + ("..." if len(missing_core) > 10 else "")
        )

    # 汇总
    result = sorted(reviewed.values(), key=lambda x: (x["year"], x["metric_key"]))

    return result, errors, warnings


def main():
    parser = argparse.ArgumentParser(description="校验候选指标表")
    parser.add_argument("--input", default="data/value_line_metrics.csv")
    parser.add_argument("--output", default="data/value_line_metrics_reviewed.csv")
    parser.add_argument("--start-year", type=int, default=2017)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--strict", action="store_true", help="严格模式：有错误时返回非零退出码")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: 候选指标表不存在: {args.input}", file=sys.stderr)
        print("请先运行: python scripts/extract_metrics.py", file=sys.stderr)
        sys.exit(1)

    rows = load_rows(args.input)
    print(f"加载 {len(rows)} 条候选指标记录")

    reviewed_rows, errors, warnings = validate_metrics(rows, args.start_year, args.end_year)

    # 输出警告
    if warnings:
        print(f"\n⚠ 合理性警告 ({len(warnings)}):")
        for w in warnings:
            print(f"  {w}")

    # 输出错误
    if errors:
        print(f"\n❌ 校验错误 ({len(errors)}):")
        for e in errors:
            print(f"  {e}")
        if args.strict:
            sys.exit(1)
    else:
        print("\n✓ 校验通过，所有硬性规则满足")

    # 写入审核版 CSV
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for r in reviewed_rows:
            writer.writerow(r)

    # 统计
    by_status = {}
    for r in reviewed_rows:
        s = r["status"]
        by_status[s] = by_status.get(s, 0) + 1

    print(f"\n审核结果: {len(reviewed_rows)} 条记录")
    print(f"状态分布: {by_status}")
    print(f"输出: {args.output}")

    # 检查是否可以生成报告
    # 规则：任何会进入报告的指标不能是 conflict 或 candidate（有值但未审核）
    unreviewed_with_value = [
        r for r in reviewed_rows
        if r["status"] in ("conflict", "candidate") and r.get("value", "") != ""
    ]
    core_missing = [
        r for r in reviewed_rows
        if r["metric_key"] in CORE_METRICS and r["status"] == "missing"
    ]
    core_unreviewed = [
        r for r in reviewed_rows
        if r["metric_key"] in CORE_METRICS and r["status"] in ("conflict", "candidate")
    ]

    can_generate = not unreviewed_with_value and not core_missing and not core_unreviewed

    if unreviewed_with_value:
        print(f"\n⚠ 存在未审核但有值的指标 ({len(unreviewed_with_value)} 条)，不会进入报告:")
        for r in unreviewed_with_value:
            print(f"    [{r['metric_key']}] {r['year']}: {r['status']} → 报告中将视为缺失")

    if core_missing or core_unreviewed:
        issue_list = core_missing + core_unreviewed
        print(f"\n⚠ 核心指标存在问题 ({len(issue_list)} 条)，不建议直接生成最终报告:")
        for r in issue_list:
            print(f"    [{r['metric_key']}] {r['year']}: {r['status']} — {r.get('note', '')}")

    if can_generate:
        print("\n✓ 可以生成 Value Line 报告（所有指标均通过审核）")
    elif args.strict:
        print("\n❌ --strict 模式下存在未审核指标，退出")
        sys.exit(1)


if __name__ == "__main__":
    main()
