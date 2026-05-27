#!/usr/bin/env python3
"""build_value_line.py — 生成中远海控 Value Line 风格单页 HTML 报告。"""

import argparse
import csv
import html as html_lib
import os
import sys
from datetime import date
from typing import Dict, List, Optional, Tuple


DEFAULT_WEEKLY_CCFI_PATH = "data/external_sources/ccfi_weekly.csv"


# ============================================================
# SVG 图表生成
# ============================================================

def build_line_chart(
    data: Dict[int, float],
    width: int = 720,
    height: int = 320,
    margin: int = 60,
    color: str = "#2563eb",
    y_label: str = "",
    y_min: Optional[float] = None,
    y_max: Optional[float] = None,
    unit_format: str = ".1f",
) -> str:
    """生成折线图 SVG。"""
    years = sorted(data.keys())
    values = [data[y] for y in years]
    if not years:
        return '<p class="no-data">暂无数据</p>'

    if y_min is None:
        y_min = min(values) * 0.9 if min(values) > 0 else min(values) * 1.1
    if y_max is None:
        y_max = max(values) * 1.1 if max(values) > 0 else max(values) * 0.9
    if y_min == y_max:
        y_max += 1

    plot_w = width - 2 * margin
    plot_h = height - 2 * margin

    def x(year):
        idx = years.index(year)
        return margin + idx * plot_w / max(1, len(years) - 1)

    def y(val):
        return margin + plot_h - (val - y_min) / (y_max - y_min) * plot_h

    # 构建 points
    points = [(x(years[i]), y(values[i])) for i in range(len(years))]
    pts_str = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
    polyline = f'<polyline points="{pts_str}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round"/>'

    # 数据点
    dots = ""
    for px, py in points:
        dots += f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{color}"/>'

    # 数值标签
    labels = ""
    for i, (px, py) in enumerate(points):
        val = values[i]
        lbl = f"{val:{unit_format}}"
        labels += f'<text x="{px:.1f}" y="{py - 12:.1f}" text-anchor="middle" font-size="11" fill="#374151">{lbl}</text>'

    # Y 轴刻度
    y_ticks = ""
    for i in range(5):
        vy = y_min + (y_max - y_min) * i / 4
        py = y(vy)
        y_ticks += f'<text x="{margin - 8}" y="{py + 4:.1f}" text-anchor="end" font-size="10" fill="#6b7280">{vy:{unit_format}}</text>'
        y_ticks += f'<line x1="{margin}" y1="{py:.1f}" x2="{width - margin}" y2="{py:.1f}" stroke="#e5e7eb" stroke-width="0.5"/>'

    # X 轴刻度
    x_ticks = ""
    for yr in years:
        px = x(yr)
        x_ticks += f'<text x="{px:.1f}" y="{height - margin + 20}" text-anchor="middle" font-size="11" fill="#374151">{yr}</text>'

    svg = f"""<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
  <rect width="{width}" height="{height}" fill="#fafafa" rx="4"/>
  {y_ticks}
  {polyline}
  {dots}
  {labels}
  {x_ticks}
  <text x="{width / 2:.0f}" y="{margin - 38}" text-anchor="middle" font-size="13" fill="#6b7280">{y_label}</text>
</svg>"""
    return svg


def build_dual_axis_chart(
    data1: Dict[int, float],
    data2: Dict[int, float],
    label1: str = "",
    label2: str = "",
    color1: str = "#2563eb",
    color2: str = "#dc2626",
    width: int = 720,
    height: int = 340,
    margin: int = 60,
) -> str:
    """生成双轴折线图 SVG（如 CCFI vs 归母净利润）。"""
    years = sorted(set(data1.keys()) & set(data2.keys()))
    vals1 = [data1[y] for y in years]
    vals2 = [data2[y] for y in years]
    if not years:
        return '<p class="no-data">暂无数据</p>'

    def calc_range(vals):
        mn = min(vals) * 0.9 if min(vals) > 0 else min(vals) * 1.1
        mx = max(vals) * 1.1 if max(vals) > 0 else max(vals) * 0.9
        if mn == mx:
            mx += 1
        return mn, mx

    y1_min, y1_max = calc_range(vals1)
    y2_min, y2_max = calc_range(vals2)

    plot_w = width - 2 * margin
    plot_h = height - 2 * margin

    def x(year):
        idx = years.index(year)
        return margin + idx * plot_w / max(1, len(years) - 1)

    def y1(val):
        return margin + plot_h - (val - y1_min) / (y1_max - y1_min) * plot_h

    def y2(val):
        return margin + plot_h - (val - y2_min) / (y2_max - y2_min) * plot_h

    # Left axis (data1)
    pts1 = [(x(yr), y1(data1[yr])) for yr in years]
    poly1 = f'<polyline points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in pts1)}" fill="none" stroke="{color1}" stroke-width="2.5"/>'
    dots1 = "".join(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{color1}"/>' for px, py in pts1)

    # Right axis (data2)
    pts2 = [(x(yr), y2(data2[yr])) for yr in years]
    poly2 = f'<polyline points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in pts2)}" fill="none" stroke="{color2}" stroke-width="2.5" stroke-dasharray="6,3"/>'
    dots2 = "".join(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{color2}"/>' for px, py in pts2)

    # X ticks
    x_ticks = "".join(
        f'<text x="{x(yr):.1f}" y="{height - margin + 20}" text-anchor="middle" font-size="11" fill="#374151">{yr}</text>'
        for yr in years
    )

    # Legend
    legend = f"""<rect x="{width - 280}" y="10" width="270" height="34" rx="4" fill="white" stroke="#e5e7eb"/>
  <line x1="{width - 270}" y1="22" x2="{width - 240}" y2="22" stroke="{color1}" stroke-width="2.5"/>
  <text x="{width - 235}" y="26" font-size="11" fill="#374151">{label1}</text>
  <line x1="{width - 130}" y1="22" x2="{width - 100}" y2="22" stroke="{color2}" stroke-width="2.5" stroke-dasharray="6,3"/>
  <text x="{width - 95}" y="26" font-size="11" fill="#374151">{label2}</text>"""

    svg = f"""<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
  <rect width="{width}" height="{height}" fill="#fafafa" rx="4"/>
  {poly1}{dots1}
  {poly2}{dots2}
  {x_ticks}
  {legend}
</svg>"""
    return svg


def build_bar_chart(
    data: Dict[int, float],
    width: int = 720,
    height: int = 260,
    margin: int = 60,
    color: str = "#2563eb",
    y_label: str = "",
    unit_format: str = ".1f",
) -> str:
    """生成柱状图 SVG。"""
    years = sorted(data.keys())
    values = [data[y] for y in years]
    if not years:
        return '<p class="no-data">暂无数据</p>'

    max_val = max(values)
    y_max = max_val * 1.2 or 1
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin
    bar_count = len(years)
    bar_gap = plot_w / bar_count * 0.3
    bar_w = (plot_w / bar_count) - bar_gap

    bars = ""
    labels = ""
    for i, yr in enumerate(years):
        val = values[i]
        bx = margin + i * plot_w / bar_count + bar_gap / 2
        bh = val / y_max * plot_h
        by = margin + plot_h - bh
        bars += f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" fill="{color}" opacity="0.85" rx="2"/>'
        labels += f'<text x="{bx + bar_w / 2:.1f}" y="{by - 6:.1f}" text-anchor="middle" font-size="11" fill="#374151">{val:{unit_format}}</text>'

    x_ticks = ""
    for i, yr in enumerate(years):
        bx = margin + i * plot_w / bar_count + bar_gap / 2
        x_ticks += f'<text x="{bx + bar_w / 2:.1f}" y="{height - margin + 20}" text-anchor="middle" font-size="11" fill="#374151">{yr}</text>'

    svg = f"""<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
  <rect width="{width}" height="{height}" fill="#fafafa" rx="4"/>
  {bars}
  {labels}
  {x_ticks}
  <text x="{width / 2:.0f}" y="{margin - 38}" text-anchor="middle" font-size="13" fill="#6b7280">{y_label}</text>
</svg>"""
    return svg


# ============================================================
# HTML 报告生成
# ============================================================

def load_metrics(path: str) -> Dict[Tuple[str, int], Dict]:
    """加载指标 CSV，返回 {(metric_key, year): row} 字典。"""
    rows = {}
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows[(r["metric_key"], int(r["year"]))] = r
    return rows


def load_weekly_ccfi(path: str = DEFAULT_WEEKLY_CCFI_PATH) -> List[Dict]:
    """加载已复核的 CCFI 周均值，缺失文件时返回空列表。"""
    if not path or not os.path.exists(path):
        return []

    records: List[Dict] = []
    seen: Dict[str, float] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {
            "date", "year", "iso_week", "week_of_year", "ccfi",
            "source_image", "source_row", "ocr_text", "status", "review_note",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CCFI 周均值表缺少字段: {', '.join(sorted(missing))}")

        for line_no, row in enumerate(reader, start=2):
            if row.get("status") != "reviewed":
                continue
            try:
                parsed_date = date.fromisoformat(row["date"])
                ccfi_value = float(row["ccfi"])
                week_of_year = int(row["week_of_year"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"CCFI 周均值表第 {line_no} 行格式非法") from exc

            iso_year, iso_week, _ = parsed_date.isocalendar()
            expected_iso_week = f"{iso_year}-W{iso_week:02d}"
            if row.get("year") != str(parsed_date.year):
                raise ValueError(f"CCFI 周均值表第 {line_no} 行 year 与 date 不一致")
            if row.get("iso_week") != expected_iso_week or week_of_year != iso_week:
                raise ValueError(f"CCFI 周均值表第 {line_no} 行 week 与 date 不一致")
            if not (500 <= ccfi_value <= 5000):
                raise ValueError(f"CCFI 周均值表第 {line_no} 行数值超出区间: {ccfi_value}")
            if not row.get("source_image"):
                raise ValueError(f"CCFI 周均值表第 {line_no} 行缺少 source_image")

            date_key = parsed_date.isoformat()
            if date_key in seen:
                if abs(seen[date_key] - ccfi_value) > 0.005:
                    raise ValueError(
                        f"CCFI 周均值表重复日期数值冲突: {date_key} {seen[date_key]:.2f} vs {ccfi_value:.2f}"
                    )
                continue
            seen[date_key] = ccfi_value
            record = dict(row)
            record["date_obj"] = parsed_date
            record["year"] = parsed_date.year
            record["week_of_year"] = week_of_year
            record["ccfi"] = ccfi_value
            records.append(record)

    return sorted(records, key=lambda r: r["date_obj"])


def get_value(metrics, mk: str, year: int) -> Optional[float]:
    """只返回 status=='reviewed' 的值，未审核数据视为缺失。"""
    r = metrics.get((mk, year))
    if r and r.get("status") == "reviewed" and r.get("value"):
        try:
            return float(r["value"])
        except (ValueError, TypeError):
            pass
    return None


def get_row(metrics, mk: str, year: int) -> Optional[Dict]:
    return metrics.get((mk, year))


def fmt_val(v: Optional[float], unit: str = "", fmt: str = ".2f") -> str:
    if v is None:
        return "--"
    return f"{v:{fmt}}"


def format_unit(value: Optional[float], fmt: str = ".2f") -> str:
    if value is None:
        return "--"
    return f"{value:{fmt}}"


def build_html(
    metrics_path: str,
    output_path: str,
    start_year: int,
    end_year: int,
    weekly_ccfi_path: str = DEFAULT_WEEKLY_CCFI_PATH,
):
    metrics = load_metrics(metrics_path)
    weekly_ccfi = load_weekly_ccfi(weekly_ccfi_path)
    today = date.today().strftime("%Y/%m/%d")
    years = list(range(start_year, end_year + 1))

    # 提取数据
    revenue = {y: get_value(metrics, "revenue", y) for y in years}
    net_profit = {y: get_value(metrics, "net_profit_parent", y) for y in years}
    op_cf = {y: get_value(metrics, "operating_cash_flow", y) for y in years}
    total_assets = {y: get_value(metrics, "total_assets", y) for y in years}
    equity = {y: get_value(metrics, "equity_parent", y) for y in years}
    eps = {y: get_value(metrics, "eps", y) for y in years}
    roe = {y: get_value(metrics, "roe", y) for y in years}
    freight_vol = {y: get_value(metrics, "freight_volume", y) for y in years}
    container_rev = {y: get_value(metrics, "container_shipping_revenue", y) for y in years}
    container_cost = {y: get_value(metrics, "container_shipping_cost", y) for y in years}
    terminal_rev = {y: get_value(metrics, "terminal_revenue", y) for y in years}
    dividend_total = {y: get_value(metrics, "dividend_total", y) for y in years}
    dividend_ps = {y: get_value(metrics, "dividend_per_share", y) for y in years}
    interest_debt = {y: get_value(metrics, "interest_bearing_debt", y) for y in years}
    buyback = {y: get_value(metrics, "buyback_amount", y) for y in years}
    ccfi = {y: get_value(metrics, "ccfi_average", y) for y in years}
    close = {y: get_value(metrics, "year_end_close", y) for y in years}
    high = {y: get_value(metrics, "year_high", y) for y in years}
    low = {y: get_value(metrics, "year_low", y) for y in years}
    market_cap = {y: get_value(metrics, "market_cap", y) for y in years}
    pe = {y: get_value(metrics, "pe_year_end", y) for y in years}
    pb = {y: get_value(metrics, "pb_year_end", y) for y in years}

    # 入口校验：核心指标至少要有已审核数据，否则可能是传入了未审核的候选表
    reviewed_core_count = sum(
        1 for mk in ("revenue", "net_profit_parent", "operating_cash_flow")
        for y in years
        if get_value(metrics, mk, y) is not None
    )
    if reviewed_core_count == 0:
        print("ERROR: metrics 文件不包含任何已审核核心指标。", file=sys.stderr)
        print("请先运行 validate_metrics.py 处理候选指标表，确保核心指标状态为 reviewed 后再生成报告。", file=sys.stderr)
        print("示例: python scripts/validate_metrics.py --input data/value_line_metrics.csv --output data/value_line_metrics_reviewed.csv", file=sys.stderr)
        sys.exit(1)

    payout_ratio = {
        y: (dividend_total[y] / net_profit[y] * 100)
        if dividend_total.get(y) not in (None, 0) and net_profit.get(y) not in (None, 0) else None
        for y in years
    }
    buyback_ratio = {
        y: (buyback[y] / (market_cap[y] if market_cap.get(y) not in (None, 0) else 1) * 100)
        if buyback.get(y) not in (None, 0) and market_cap.get(y) not in (None, 0) else None
        for y in years
    }
    dividend_yield = {
        y: (dividend_ps[y] / close[y] * 100)
        if dividend_ps.get(y) not in (None, 0) and close.get(y) not in (None, 0) else None
        for y in years
    }
    net_margin = {
        y: (net_profit[y] / revenue[y] * 100)
        if revenue.get(y) not in (None, 0) and net_profit.get(y) is not None else None
        for y in years
    }
    container_rev_ratio = {
        y: (container_rev[y] / revenue[y] * 100)
        if container_rev.get(y) not in (None, 0) and revenue.get(y) not in (None, 0) else None
        for y in years
    }
    container_gross_margin = {
        y: ((container_rev[y] - container_cost[y]) / container_rev[y] * 100)
        if container_rev.get(y) not in (None, 0) and container_cost.get(y) not in (None, 0) else None
        for y in years
    }
    equity_ratio = {
        y: (equity[y] / total_assets[y] * 100)
        if total_assets.get(y) not in (None, 0) and equity.get(y) is not None else None
        for y in years
    }
    latest_year = years[-1]
    latest_revenue = revenue.get(latest_year)
    latest_np = net_profit.get(latest_year)
    latest_roe = roe.get(latest_year)
    latest_cf = op_cf.get(latest_year)
    latest_equity_ratio = equity_ratio.get(latest_year)
    latest_assets = total_assets.get(latest_year)
    chart = _build_value_line_chart(years, revenue, net_profit, op_cf, ccfi)
    weekly_chart = _build_weekly_ccfi_chart(weekly_ccfi)
    weekly_chart_block = (
        f'<div class="block-title">CCFI周均值年内曲线</div>'
        f'<div class="chart-wrap weekly-chart">{weekly_chart}</div>'
        if weekly_chart else ""
    )

    # 构建 HTML
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>中远海控价值线</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: Arial, "Noto Sans SC", "Microsoft YaHei", sans-serif;
  color: #171717;
  background: #e8e8e8;
  line-height: 1.35;
  padding: 12px;
}}
.sheet {{
  width: 100%;
  max-width: 1380px;
  min-height: 1680px;
  margin: 0 auto;
  background: #fff;
  border: 3px solid #333;
  box-shadow: 0 2px 12px rgba(0,0,0,.14);
}}
.top-grid {{
  display: grid;
  grid-template-columns: 26% 24% 15% 18% 17%;
  border-bottom: 2px solid #777;
}}
.brand, .top-cell, .metric-cell, .valuation-cell {{
  min-height: 58px;
  border-right: 2px solid #999;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
}}
.brand {{
  grid-column: 1;
  grid-row: 1 / span 2;
  flex-direction: column;
  font-size: 26px;
  font-weight: 800;
  letter-spacing: .2px;
}}
.title-cell {{ grid-column: 2; grid-row: 1; }}
.rev-cell {{ grid-column: 3; grid-row: 1; }}
.profit-cell {{ grid-column: 4; grid-row: 1; }}
.roe-cell {{ grid-column: 5; grid-row: 1; border-right: 0; }}
.pe-cell {{ grid-column: 2; grid-row: 2; }}
.pb-cell {{ grid-column: 3 / span 2; grid-row: 2; }}
.date-cell {{ grid-column: 5; grid-row: 2; border-right: 0; }}
.top-cell {{
  font-size: 16px;
  font-weight: 800;
}}
.metric-cell {{
  flex-direction: column;
  gap: 2px;
  font-size: 13px;
  font-weight: 700;
}}
.metric-cell strong, .valuation-cell strong {{
  display: block;
  color: #005b9f;
  font-size: 18px;
  line-height: 1.1;
}}
.valuation-cell {{
  flex-direction: column;
  font-size: 12px;
  font-weight: 700;
}}
.valuation-cell.big strong {{ font-size: 28px; }}
.quick-grid {{
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  border-bottom: 2px solid #777;
}}
.quick-card {{
  min-height: 82px;
  padding: 8px 10px;
  border-right: 2px solid #aaa;
}}
.quick-card:last-child {{ border-right: 0; }}
.eyebrow {{
  font-size: 11px;
  color: #555;
  font-weight: 800;
  margin-bottom: 3px;
}}
.quick-value {{
  color: #005b9f;
  font-size: 22px;
  font-weight: 900;
  line-height: 1.1;
}}
.quick-note {{
  margin-top: 4px;
  color: #444;
  font-size: 12px;
}}
.main-grid {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) 305px;
}}
.left-pane {{
  border-right: 2px solid #777;
}}
.side-pane {{
  min-width: 0;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 12px;
}}
th, td {{
  border: 1px solid #999;
  padding: 5px 7px;
  text-align: right;
  vertical-align: middle;
  white-space: nowrap;
}}
th {{
  background: #efefef;
  font-weight: 800;
}}
td:first-child, th:first-child {{
  text-align: left;
  font-weight: 800;
}}
.missing {{
  color: #999;
}}
.block-title {{
  height: 31px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-top: 2px solid #777;
  border-bottom: 1px solid #999;
  background: #f3f3f3;
  font-size: 14px;
  font-weight: 900;
}}
.block-title:first-child {{ border-top: 0; }}
.chart-wrap {{
  padding: 10px 12px 8px;
}}
.chart-wrap svg {{
  width: 100%;
  height: auto;
  display: block;
}}
.side-section {{
  border-bottom: 2px solid #777;
}}
.side-section .content {{
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.55;
}}
.side-section p + p {{ margin-top: 8px; }}
.side-section strong {{ display: block; margin-bottom: 3px; }}
.sources {{
  font-size: 11px;
  color: #333;
  line-height: 1.55;
  word-break: break-all;
}}
.footer-row {{
  display: grid;
  grid-template-columns: 150px 1fr;
  border-top: 2px solid #777;
  font-size: 11px;
}}
.footer-row > div {{
  padding: 8px 10px;
  border-right: 1px solid #999;
}}
.footer-row > div:last-child {{ border-right: 0; }}
.status-pill {{
  display: inline-block;
  padding: 1px 5px;
  border: 1px solid #aaa;
  background: #f7f7f7;
  font-size: 11px;
}}
@media print {{
  body {{ background: white; padding: 0; }}
  .sheet {{ box-shadow: none; width: 100%; border-width: 2px; }}
}}
@media (max-width: 1420px) {{
  body {{ padding: 0; }}
  .sheet {{ max-width: none; }}
}}
</style>
</head>
<body>

<div class="sheet">
  <div class="top-grid">
    <div class="brand">
      <div>601919.SH</div>
      <div>01919.HK</div>
    </div>
    <div class="top-cell title-cell">中远海控价值线</div>
    <div class="metric-cell rev-cell">最新收入<strong>{_fmt_num(latest_revenue, 1)}亿</strong></div>
    <div class="metric-cell profit-cell">最新归母净利<strong>{_fmt_num(latest_np, 1)}亿</strong></div>
    <div class="metric-cell roe-cell">最新ROE<strong>{_fmt_pct(latest_roe, 1)}</strong></div>
    <div class="valuation-cell big pe-cell">PE<strong>{_fmt_num(pe.get(latest_year), 1)}</strong></div>
    <div class="valuation-cell big pb-cell">PB<strong>{_fmt_num(pb.get(latest_year), 2)}</strong></div>
    <div class="valuation-cell date-cell">编制日期<strong>{today}</strong></div>
  </div>

  <div class="quick-grid">
    {_build_quick_read("营业收入", latest_revenue, "亿", _growth_sentence(revenue, years))}
    {_build_quick_read("归母净利润", latest_np, "亿", _growth_sentence(net_profit, years))}
    {_build_quick_read("经营现金流", latest_cf, "亿", _growth_sentence(op_cf, years))}
    {_build_quick_read("资本结构", latest_equity_ratio, "%", f"总资产 {_fmt_num(latest_assets, 1)} 亿，归母权益/总资产")}
  </div>

  <div class="main-grid">
    <div class="left-pane">
      {_build_annual_matrix(years, revenue, net_profit, op_cf, net_margin, roe, eps, total_assets, equity, equity_ratio, ccfi, interest_debt, container_cost, container_gross_margin, container_rev_ratio, dividend_ps, freight_vol)}
      <div class="block-title">收入、归母净利润、经营现金流 &amp; CCFI均值趋势</div>
      <div class="chart-wrap">{chart}</div>
      {weekly_chart_block}
      <div class="block-title">A股估值带（601919.SH）</div>
      {_build_valuation_band(years, eps, close, high, low, pe, pb, market_cap)}
    </div>
    <div class="side-pane">
      <div class="side-section">
        <div class="block-title">年均增长率</div>
        {_build_growth_sidebar(years, revenue, net_profit, op_cf, equity)}
      </div>
      <div class="side-section">
        <div class="block-title">每股分红</div>
        {_build_dividend_compact(years, dividend_ps, dividend_total, payout_ratio, dividend_yield, metrics)}
      </div>
      <div class="side-section">
        <div class="block-title">市值与回购</div>
        <div class="content">{_build_market_summary(years, close, market_cap, buyback, buyback_ratio)}</div>
      </div>
      <div class="side-section">
        <div class="block-title">估值摘要</div>
        {_build_valuation_notes(today, pe.get(latest_year), pb.get(latest_year), close.get(latest_year), market_cap.get(latest_year), pe, pb)}
      </div>
      <div class="side-section">
        <div class="block-title">投资判断</div>
        {_build_investment_notes(revenue, net_profit, op_cf, roe, ccfi, years)}
      </div>
      <div class="side-section">
        <div class="block-title">数据来源</div>
        <div class="content sources">{_build_compact_sources(metrics)}</div>
      </div>
    </div>
  </div>

  <div class="footer-row">
    <div><strong>说明</strong><br>本地年报数据整理</div>
    <div>PE/PB、行情估值来自 akshare 不复权日线数据；CCFI 年均值来自年报原文 + 外部数据交叉验证；CCFI 周均值来自 Wind 截图人工复核表。核心指标均与年报原文核对一致。仅供个人研究，不构成投资建议。</div>
  </div>
</div>

</body>
</html>"""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"报告生成完成: {output_path}")


def _fmt_num(value: Optional[float], decimals: int = 1) -> str:
    if value is None:
        return "--"
    return f"{value:,.{decimals}f}"


def _fmt_pct(value: Optional[float], decimals: int = 1) -> str:
    if value is None:
        return "--"
    return f"{value:.{decimals}f}%"


def _fmt_table_value(value: Optional[float], decimals: int = 1, pct: bool = False) -> str:
    if value is None:
        return '<span class="missing">--</span>'
    if pct:
        return _fmt_pct(value, decimals)
    return _fmt_num(value, decimals)


def _latest_non_empty(data: Dict[int, Optional[float]], years: List[int]) -> Tuple[Optional[int], Optional[float]]:
    for year in reversed(years):
        value = data.get(year)
        if value is not None:
            return year, value
    return None, None


def _cagr(data: Dict[int, Optional[float]], end_year: int, span: int) -> Optional[float]:
    start_year = end_year - span
    start = data.get(start_year)
    end = data.get(end_year)
    if start is None or end is None or start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / span) - 1


def _growth_sentence(data: Dict[int, Optional[float]], years: List[int]) -> str:
    latest_year, latest = _latest_non_empty(data, years)
    if latest_year is None or latest is None:
        return "暂无已审核数据"

    parts = []
    prev = data.get(latest_year - 1)
    if prev not in (None, 0):
        yoy = latest / prev - 1
        parts.append(f"同比 {yoy:+.1%}")

    full_span = latest_year - years[0]
    full_cagr = _cagr(data, latest_year, full_span) if full_span > 0 else None
    if full_cagr is not None:
        parts.append(f"{years[0]}-{latest_year} CAGR {full_cagr:.1%}")

    return "；".join(parts) if parts else f"{latest_year} 年已审核"


def _build_quick_read(label: str, value: Optional[float], unit: str, note: str) -> str:
    if unit == "%":
        display = _fmt_pct(value, 1)
    elif value is None:
        display = "--"
    else:
        display = f"{_fmt_num(value, 1)}{unit}"
    return f"""
    <div class="quick-card">
      <div class="eyebrow">Quick Read | {html_lib.escape(label)}</div>
      <div class="quick-value">{display}</div>
      <div class="quick-note">{html_lib.escape(note)}</div>
    </div>"""


def _build_table_row(label: str, years: List[int], data: Dict[int, Optional[float]], decimals: int = 1, pct: bool = False) -> str:
    cells = "".join(f"<td>{_fmt_table_value(data.get(y), decimals, pct)}</td>" for y in years)
    return f"<tr><td>{label}</td>{cells}</tr>"


def _build_annual_matrix(
    years,
    revenue,
    net_profit,
    op_cf,
    net_margin,
    roe,
    eps,
    total_assets,
    equity,
    equity_ratio,
    ccfi,
    interest_debt,
    container_cost,
    container_gross_margin,
    container_rev_ratio,
    dividend_ps,
    freight_vol,
):
    def _year_label(y):
        has_annual = dividend_ps.get(y) is not None
        if has_annual:
            return str(y)
        return f"{y}Q1"
    header = "<tr><th>年度</th>" + "".join(f"<th>{_year_label(y)}</th>" for y in years) + "</tr>"
    rows = [
        _build_table_row("营业收入（亿元）", years, revenue, 1),
        _build_table_row("归母净利润（亿元）", years, net_profit, 1),
        _build_table_row("经营现金流（亿元）", years, op_cf, 1),
        _build_table_row("销售净利率", years, net_margin, 1, True),
        _build_table_row("净资产收益率ROE", years, roe, 1, True),
        _build_table_row("每股收益EPS（元）", years, eps, 2),
        _build_table_row("总资产（亿元）", years, total_assets, 1),
        _build_table_row("归母权益（亿元）", years, equity, 1),
        _build_table_row("有息负债（亿元）", years, interest_debt, 1),
        _build_table_row("权益/资产", years, equity_ratio, 1, True),
        _build_table_row("航运运量（万TEU）", years, freight_vol, 1),
        _build_table_row("航运营收比例", years, container_rev_ratio, 1, True),
        _build_table_row("航运毛利率", years, container_gross_margin, 1, True),
        _build_table_row("CCFI均值（点）", years, ccfi, 2),
    ]
    return f'<table class="annual-table">{header}{"".join(rows)}</table>'


def _build_growth_sidebar(years, revenue, net_profit, op_cf, equity):
    end_year = years[-1]
    metrics = [
        ("营业收入", revenue),
        ("归母净利", net_profit),
        ("经营现金流", op_cf),
        ("归母权益", equity),
    ]
    spans = [8, 5, 3]
    rows = ""
    for label, data in metrics:
        cells = ""
        for span in spans:
            value = _cagr(data, end_year, span)
            cells += f"<td>{_fmt_table_value(value * 100 if value is not None else None, 1, True)}</td>"
        rows += f"<tr><td>{label}</td>{cells}</tr>"
    return f"""
    <table>
      <tr><th>项目</th><th>8年</th><th>5年</th><th>3年</th></tr>
      {rows}
    </table>"""


def _build_dividend_compact(years, dps, total, payout_ratio, dividend_yield, metrics):
    rows = ""
    for year in reversed(years[-5:]):
        rows += (
            f"<tr><td>{year}</td>"
            f"<td>{_fmt_table_value(dps.get(year), 2)}</td>"
            f"<td>{_fmt_table_value(total.get(year), 1)}</td>"
            f"<td>{_fmt_table_value(payout_ratio.get(year), 1, pct=True)}</td>"
            f"<td>{_fmt_table_value(dividend_yield.get(year), 1, pct=True)}</td></tr>"
        )
    return f"""
    <table>
      <tr><th>年度</th><th>每股</th><th>总额(亿)</th><th>支付率</th><th>股息率</th></tr>
      {rows}
    </table>"""


def _build_market_summary(years, close, market_cap, buyback, buyback_ratio):
    """市值与回购摘要。"""
    rows = ""
    for year in reversed(years[-5:]):
        bb = buyback.get(year)
        bb_str = f"{bb:.2f}" if bb and bb > 0 else "-"
        rows += (
            f"<tr><td>{year}</td>"
            f"<td>{_fmt_table_value(close.get(year), 2)}</td>"
            f"<td>{_fmt_table_value(market_cap.get(year), 0)}</td>"
            f"<td>{bb_str}</td>"
            f"<td>{_fmt_table_value(buyback_ratio.get(year), 1, pct=True)}</td></tr>"
        )
    return f"""
    <table>
      <tr><th>年度</th><th>年末收盘(元)</th><th>市值(亿)</th><th>回购(亿)</th><th>回购占比</th></tr>
      {rows}
    </table>
    <p style="margin-top:6px;font-size:11px;color:#555;">行情来源 akshare 不复权日线，回购金额来自年报（A+H合计，A股部分akshare交叉验证一致）。</p>"""


def _build_valuation_notes(today: str, latest_pe=None, latest_pb=None, latest_close=None, latest_mc=None, pe_all=None, pb_all=None) -> str:
    pe_str = f"PE {_fmt_num(latest_pe, 1)} 倍" if latest_pe else "PE --"
    pb_str = f"PB {_fmt_num(latest_pb, 2)} 倍" if latest_pb else "PB --"
    close_str = f"收盘 {_fmt_num(latest_close, 2)} 元" if latest_close else ""
    mc_str = f"市值 {_fmt_num(latest_mc, 0)} 亿" if latest_mc else ""

    pe_range = ""
    if pe_all:
        pe_vals = [v for v in pe_all.values() if v is not None]
        if pe_vals:
            pe_range = f"2017-2025 年 PE 区间 {min(pe_vals):.1f}–{max(pe_vals):.1f} 倍"
    pb_range = ""
    if pb_all:
        pb_vals = [v for v in pb_all.values() if v is not None]
        if pb_vals:
            pb_range = f"PB 区间 {min(pb_vals):.2f}–{max(pb_vals):.2f} 倍"

    return f"""
    <div class="content">
      <p><strong>当前A股</strong>截至 {today}，{pe_str}，{pb_str}，{close_str}，{mc_str}。数据来源 akshare 不复权日线 + 年报 EPS/权益。</p>
      <p><strong>历史估值</strong>{pe_range}，{pb_range}。航运业重资产、高周期，PB 持续低于 1 倍净资产。</p>
      <p><strong>怎么看</strong>对中远海控这类强周期公司，低 PE 往往对应盈利顶峰而非买入信号，估值应与运价周期、分红政策、资产负债表一起观察。</p>
    </div>"""


def _build_investment_notes(revenue, net_profit, op_cf, roe, ccfi, years):
    latest = years[-1]
    rev = revenue.get(latest)
    npv = net_profit.get(latest)
    cf = op_cf.get(latest)
    roe_v = roe.get(latest)
    peak_year, peak_profit = _latest_non_empty(
        {y: v for y, v in net_profit.items() if v == max([x for x in net_profit.values() if x is not None], default=None)},
        years,
    )

    profit_vals = {y: v for y, v in net_profit.items() if v is not None}
    if profit_vals:
        peak_year = max(profit_vals, key=profit_vals.get)
        peak_profit = profit_vals[peak_year]

    ccfi_reviewed = [v for v in ccfi.values() if v is not None]
    ccfi_note = "CCFI 年均值暂无已审核数据，需补齐外部来源后再判断运价联动。" if not ccfi_reviewed else "CCFI 已审核数据可与利润曲线对照观察。"
    return f"""
    <div class="content">
      <p><strong>周期主线</strong>{latest} 年收入 {_fmt_num(rev, 1)} 亿、归母净利 {_fmt_num(npv, 1)} 亿、经营现金流 {_fmt_num(cf, 1)} 亿，ROE {_fmt_pct(roe_v, 1)}。</p>
      <p><strong>盈利弹性</strong>{years[0]}-{latest} 年归母净利峰值出现在 {peak_year or '--'} 年，约 {_fmt_num(peak_profit, 1)} 亿，利润对运价周期高度敏感。</p>
      <p><strong>跟踪指标</strong>{ccfi_note}</p>
      <p><strong>主要风险</strong>全球贸易、运价、有效运力、燃油成本、港口拥堵和地缘事件均可能影响盈利。</p>
    </div>"""


def _build_valuation_band(years, eps, close, high, low, pe, pb, market_cap):
    rows = ""
    for year in years:
        rows += (
            f"<tr><td>{year}</td>"
            f"<td>{_fmt_table_value(low.get(year), 2)}</td>"
            f"<td>{_fmt_table_value(high.get(year), 2)}</td>"
            f"<td>{_fmt_table_value(close.get(year), 2)}</td>"
            f"<td>{_fmt_table_value(eps.get(year), 2)}</td>"
            f"<td>{_fmt_table_value(pe.get(year), 1)}</td>"
            f"<td>{_fmt_table_value(pb.get(year), 2)}</td>"
            f"<td>{_fmt_table_value(market_cap.get(year), 0)}</td></tr>"
        )
    return f"""
    <table>
      <tr>
        <th>年度</th><th>最低价</th><th>最高价</th><th>年末收盘</th><th>EPS</th>
        <th>年末PE</th><th>年末PB</th><th>总市值(亿)</th>
      </tr>
      {rows}
    </table>"""


def _build_value_line_chart(years, revenue, net_profit, op_cf, ccfi):
    width, height = 1040, 360
    left, right, top, bottom = 54, 72, 32, 58
    plot_w = width - left - right
    plot_h = height - top - bottom
    financial_series = [
        ("营业收入", revenue, "#1597f5", False),
        ("归母净利润", net_profit, "#13bfa9", False),
        ("经营现金流", op_cf, "#20b832", False),
    ]
    ccfi_values = [v for v in ccfi.values() if v is not None]
    if ccfi_values:
        financial_series.append(("CCFI均值", ccfi, "#bd2b24", True))

    fin_values = [
        v
        for _, data, _, is_right_axis in financial_series
        if not is_right_axis
        for v in data.values()
        if v is not None
    ]
    if not fin_values:
        return '<div class="no-data">暂无数据</div>'

    y_max = max(fin_values) * 1.12
    y_min = 0
    ccfi_min = min(ccfi_values) * 0.88 if ccfi_values else 0
    ccfi_max = max(ccfi_values) * 1.08 if ccfi_values else 1
    if ccfi_min == ccfi_max:
        ccfi_max += 1

    def x(year):
        return left + years.index(year) * plot_w / max(1, len(years) - 1)

    def y_fin(value):
        return top + plot_h - (value - y_min) / (y_max - y_min) * plot_h

    def y_ccfi(value):
        return top + plot_h - (value - ccfi_min) / (ccfi_max - ccfi_min) * plot_h

    grid = ""
    for i in range(5):
        value = y_min + (y_max - y_min) * i / 4
        py = y_fin(value)
        grid += f'<line x1="{left}" y1="{py:.1f}" x2="{width-right}" y2="{py:.1f}" stroke="#cfcfcf" stroke-width="1"/>'
        grid += f'<text x="{left-8}" y="{py+4:.1f}" text-anchor="end" font-size="12" fill="#666">{value:.0f}</text>'
        if ccfi_values:
            cvalue = ccfi_min + (ccfi_max - ccfi_min) * i / 4
            grid += f'<text x="{width-right+10}" y="{py+4:.1f}" text-anchor="start" font-size="12" fill="#b54747">{cvalue:.0f}</text>'

    x_ticks = "".join(
        f'<text x="{x(year):.1f}" y="{height-26}" text-anchor="middle" font-size="13" font-weight="700" fill="#555">{year}</text>'
        for year in years
    )

    lines = ""
    legend_parts = []
    legend_x = width / 2 - 250
    for idx, (label, data, color, is_right_axis) in enumerate(financial_series):
        points = []
        for year in years:
            value = data.get(year)
            if value is None:
                continue
            py = y_ccfi(value) if is_right_axis else y_fin(value)
            points.append((x(year), py))
        if points:
            dash = ' stroke-dasharray="7,4"' if is_right_axis else ""
            pts = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
            lines += f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="3"{dash}/>'
            lines += "".join(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{color}"/>' for px, py in points)
        lx = legend_x + idx * 132
        dash = ' stroke-dasharray="7,4"' if is_right_axis else ""
        legend_parts.append(
            f'<line x1="{lx:.1f}" y1="{height-10}" x2="{lx+28:.1f}" y2="{height-10}" stroke="{color}" stroke-width="3"{dash}/>'
            f'<text x="{lx+34:.1f}" y="{height-6}" font-size="12" font-weight="700" fill="#333">{label}</text>'
        )

    if not ccfi_values:
        legend_parts.append(
            f'<text x="{width-260}" y="{height-6}" font-size="12" fill="#777">CCFI待复核，暂不入图</text>'
        )

    return f"""
    <svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
      <rect width="{width}" height="{height}" fill="#fff"/>
      <text x="{width/2:.0f}" y="20" text-anchor="middle" font-size="15" font-weight="900" fill="#222">收入、归母净利润、经营现金流 &amp; CCFI均值趋势</text>
      {grid}
      {lines}
      {x_ticks}
      {''.join(legend_parts)}
    </svg>"""


def _build_weekly_ccfi_chart(records: List[Dict]) -> str:
    """按年叠加渲染 CCFI 周均值曲线。"""
    display_years = [2022, 2023, 2024, 2025, 2026]
    groups: Dict[int, List[Dict]] = {year: [] for year in display_years}
    for record in records:
        year = record["year"]
        if year in groups:
            groups[year].append(record)

    groups = {year: sorted(rows, key=lambda r: r["week_of_year"]) for year, rows in groups.items() if rows}
    values = [row["ccfi"] for rows in groups.values() for row in rows]
    if not values:
        return ""

    width, height = 1040, 300
    left, right, top, bottom = 54, 30, 34, 64
    plot_w = width - left - right
    plot_h = height - top - bottom
    y_min = max(0, min(values) * 0.88)
    y_max = max(values) * 1.08
    if y_min == y_max:
        y_max += 1

    colors = {
        2022: "#bd2b24",
        2023: "#6b7280",
        2024: "#1597f5",
        2025: "#20b832",
        2026: "#8b5cf6",
    }

    def x(week: int) -> float:
        return left + (week - 1) * plot_w / 52

    def y(value: float) -> float:
        return top + plot_h - (value - y_min) / (y_max - y_min) * plot_h

    grid = ""
    for i in range(5):
        value = y_min + (y_max - y_min) * i / 4
        py = y(value)
        grid += f'<line x1="{left}" y1="{py:.1f}" x2="{width-right}" y2="{py:.1f}" stroke="#cfcfcf" stroke-width="1"/>'
        grid += f'<text x="{left-8}" y="{py+4:.1f}" text-anchor="end" font-size="12" fill="#666">{value:.0f}</text>'

    week_ticks = [(1, "W1"), (13, "W13"), (26, "W26"), (39, "W39"), (53, "W53")]
    x_ticks = "".join(
        f'<text x="{x(week):.1f}" y="{height-30}" text-anchor="middle" font-size="12" font-weight="700" fill="#555">{label}</text>'
        for week, label in week_ticks
    )
    x_ticks += "".join(
        f'<line x1="{x(week):.1f}" y1="{top}" x2="{x(week):.1f}" y2="{top+plot_h}" stroke="#e5e5e5" stroke-width="1"/>'
        for week, _ in week_ticks
    )

    lines = ""
    legend_parts = []
    legend_x = width / 2 - 330
    for idx, year in enumerate(display_years):
        rows = groups.get(year, [])
        if not rows:
            continue
        points = [(x(row["week_of_year"]), y(row["ccfi"])) for row in rows]
        pts = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
        color = colors[year]
        lines += (
            f'<polyline class="weekly-ccfi-line" data-year="{year}" points="{pts}" '
            f'fill="none" stroke="{color}" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>'
        )
        lines += "".join(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.4" fill="{color}" opacity="0.85"/>'
            for px, py in points
        )

        legend_label = f"{year}（YTD）" if year == 2026 else f"{year}（{len(rows)}周）"
        lx = legend_x + idx * 138
        legend_parts.append(
            f'<line x1="{lx:.1f}" y1="{height-10}" x2="{lx+28:.1f}" y2="{height-10}" stroke="{color}" stroke-width="3"/>'
            f'<text x="{lx+34:.1f}" y="{height-6}" font-size="12" font-weight="700" fill="#333">{legend_label}</text>'
        )

    return f"""
    <svg class="weekly-ccfi-svg" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
      <rect width="{width}" height="{height}" fill="#fff"/>
      <text x="{width/2:.0f}" y="20" text-anchor="middle" font-size="15" font-weight="900" fill="#222">CCFI周均值年内曲线</text>
      {grid}
      {x_ticks}
      {lines}
      {''.join(legend_parts)}
    </svg>"""


def _build_compact_sources(metrics):
    source_files = sorted({r.get("source_file", "") for r in metrics.values() if r.get("source_file")})
    reviewed_count = sum(1 for r in metrics.values() if r.get("status") == "reviewed")
    candidate_count = sum(1 for r in metrics.values() if r.get("status") == "candidate")
    missing_count = sum(1 for r in metrics.values() if r.get("status") == "missing")
    files = "<br>".join(html_lib.escape(sf) for sf in source_files[:9])

    # Summarize external sources by category
    external_categories = {}
    for r in metrics.values():
        if r.get("source_type") == "external" and r.get("status") == "reviewed":
            mk = r.get("metric_key", "")
            if mk.startswith("ccfi"):
                cat = "CCFI均值"
            elif mk.startswith("dividend"):
                cat = "分红"
            elif mk in ("year_end_close", "year_high", "year_low", "market_cap", "pe_year_end", "pb_year_end"):
                cat = "行情估值"
            else:
                cat = "其他"
            if cat not in external_categories:
                external_categories[cat] = set()
            external_categories[cat].add(int(r.get("year", 0)))

    ext_lines = []
    for cat in ["CCFI均值", "行情估值", "分红"]:
        if cat in external_categories:
            years = sorted(external_categories[cat])
            yr_range = f"{min(years)}-{max(years)}" if len(years) > 1 else str(years[0])
            ext_lines.append(f"{cat}（{yr_range}，{len(years)}年）")
    ext_summary = "、".join(ext_lines) if ext_lines else "暂无外部数据"
    repo_available = any(
        r.get("metric_key", "").startswith("repo") or r.get("metric_key", "").startswith("buyback")
        for r in metrics.values() if r.get("status") == "reviewed"
    )

    return (
        f"<p><strong>年报文件</strong><br>{files}</p>"
        f"<p><strong>状态统计</strong><br>"
        f'<span class="status-pill">reviewed {reviewed_count}</span> '
        f'<span class="status-pill">candidate {candidate_count}</span> '
        f'<span class="status-pill">missing {missing_count}</span></p>'
        f"<p><strong>外部数据</strong><br>{ext_summary}。"
        + ("回购数据待补齐。" if not repo_available else "")
        + "</p>"
    )


def _generate_observations(revenue, net_profit, op_cf, roe, ccfi, years):
    """生成三到五条快速观察。"""
    obs = []
    years_list = list(years)

    # 周期观察：利润波动
    np_vals = [v for v in net_profit.values() if v is not None]
    if np_vals:
        peak = max(np_vals)
        trough = min(v for v in np_vals if v > 0)
        peak_yr = [y for y, v in net_profit.items() if v == peak][0]
        obs.append(f"归母净利润在{peak_yr}年达到周期高点 {peak:.0f} 亿元，周期低点约 {trough:.0f} 亿元，呈现典型强周期特征。")

    # 现金流
    cf_recent = [op_cf[y] for y in years_list[-3:] if op_cf.get(y) is not None]
    if cf_recent:
        obs.append(f"近三年经营现金流净额保持在 {min(cf_recent):.0f}–{max(cf_recent):.0f} 亿元，造血能力充沛。")

    # ROE
    roe_recent = [roe[y] for y in years_list[-3:] if roe.get(y) is not None]
    if roe_recent:
        obs.append(f"近三年 ROE 在 {min(roe_recent):.1f}%–{max(roe_recent):.1f}% 区间波动，盈利效率随周期震荡。")

    # CCFI 关联 — 基于已审核数据计算实际相关性
    ccfi_vals = {y: v for y, v in ccfi.items() if v is not None}
    np_for_ccfi = {y: v for y, v in net_profit.items() if v is not None and y in ccfi_vals}
    if ccfi_vals and np_for_ccfi:
        common_years = sorted(set(ccfi_vals) & set(np_for_ccfi))
        if len(common_years) >= 4:
            xs = [ccfi_vals[y] for y in common_years]
            ys = [np_for_ccfi[y] for y in common_years]
            n = len(xs)
            sum_x = sum(xs)
            sum_y = sum(ys)
            sum_xy = sum(x * y for x, y in zip(xs, ys))
            sum_x2 = sum(x * x for x in xs)
            sum_y2 = sum(y * y for y in ys)
            denom = ((n * sum_x2 - sum_x ** 2) * (n * sum_y2 - sum_y ** 2)) ** 0.5
            if denom > 0:
                r = (n * sum_xy - sum_x * sum_y) / denom
                if r > 0.7:
                    corr_desc = "与净利润高度正相关"
                elif r > 0.4:
                    corr_desc = "与净利润存在一定正相关性"
                elif r > -0.4:
                    corr_desc = "与净利润相关性较弱"
                else:
                    corr_desc = "与净利润呈负相关"
            else:
                corr_desc = "与净利润的联动关系需更多数据验证"
        elif len(common_years) >= 2:
            corr_desc = "与净利润的联动关系可对照观察"
        else:
            corr_desc = ""
        if corr_desc:
            obs.append(f"CCFI 年均值在 {min(ccfi_vals.values()):.0f}–{max(ccfi_vals.values()):.0f} 点之间，{corr_desc}，是跟踪周期位置的关键领先指标。")
        else:
            obs.append(f"CCFI 年均值在 {min(ccfi_vals.values()):.0f}–{max(ccfi_vals.values()):.0f} 点之间，可用于跟踪运价周期变化。")
    elif ccfi_vals:
        obs.append(f"CCFI 年均值在 {min(ccfi_vals.values()):.0f}–{max(ccfi_vals.values()):.0f} 点之间，可用于跟踪运价周期变化。")

    # 收入规模
    rev_vals = {y: v for y, v in revenue.items() if v is not None}
    if rev_vals:
        obs.append(f"营业收入从{years_list[0]}年 {rev_vals.get(years_list[0], 0):.0f} 亿元增长至{years_list[-1]}年 {rev_vals.get(years_list[-1], 0):.0f} 亿元。")

    return "<br>".join(f"• {o}" for o in obs[:5])


def _build_core_table(years, revenue, net_profit, op_cf, total_assets, equity, eps, roe):
    """生成核心指标表。"""
    rows_html = '<tr><th>指标</th>' + "".join(f"<th>{y}</th>" for y in years) + "</tr>"

    metrics_list = [
        ("营业收入（亿元）", revenue),
        ("归母净利润（亿元）", net_profit),
        ("经营现金流（亿元）", op_cf),
        ("总资产（亿元）", total_assets),
        ("归母净资产（亿元）", equity),
        ("EPS（元/股）", eps),
        ("ROE（%）", roe),
    ]

    for label, data in metrics_list:
        cells = ""
        for y in years:
            v = data.get(y)
            if v is not None:
                cells += f'<td>{v:.2f}</td>'
            else:
                cells += '<td class="missing">--</td>'
        rows_html += f"<tr><td>{label}</td>{cells}</tr>"

    return f'<table>{rows_html}</table>'


def _render_dual_svg(years, data1, data2, label1, label2, color1, color2):
    """在SVG中渲染双指标折线。"""
    width, height, margin = 720, 320, 56
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin

    def calc_range(vals):
        vals = [v for v in vals if v is not None]
        if not vals:
            return 0, 1
        mn = min(vals)
        mx = max(vals)
        if mn == mx:
            mx += 1
        return mn - (mx - mn) * 0.05, mx + (mx - mn) * 0.15

    all_years = sorted(years)
    vals1 = [data1.get(y) for y in all_years]
    vals2 = [data2.get(y) for y in all_years]
    has_data = any(v is not None for v in vals1 + vals2)
    if not has_data:
        return '<text x="360" y="160" text-anchor="middle" font-size="14" fill="#d1d5db">暂无数据</text>'
    ymin, ymax = calc_range([v for v in vals1 + vals2 if v is not None])

    def x(yr):
        return margin + all_years.index(yr) * plot_w / max(1, len(all_years) - 1)

    def y(v):
        return margin + plot_h - (v - ymin) / (ymax - ymin) * plot_h

    elements = ""

    # Y ticks
    for i in range(5):
        vy = ymin + (ymax - ymin) * i / 4
        py = y(vy)
        elements += f'<text x="{margin - 8}" y="{py + 4:.1f}" text-anchor="end" font-size="10" fill="#6b7280">{vy:.0f}</text>'
        elements += f'<line x1="{margin}" y1="{py:.1f}" x2="{width - margin}" y2="{py:.1f}" stroke="#e5e7eb" stroke-width="0.5"/>'

    # Lines
    for data, color in [(data1, color1), (data2, color2)]:
        pts = [(x(yr), y(data[yr])) for yr in all_years if data.get(yr) is not None]
        if pts:
            pts_str = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
            elements += f'<polyline points="{pts_str}" fill="none" stroke="{color}" stroke-width="2.5"/>'
            elements += "".join(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="{color}"/>' for px, py in pts)

    # X ticks
    elements += "".join(
        f'<text x="{x(yr):.1f}" y="{height - margin + 18}" text-anchor="middle" font-size="11" fill="#374151">{yr}</text>'
        for yr in all_years
    )

    # Legend
    elements += f"""<rect x="{width - 280}" y="10" width="270" height="34" rx="4" fill="white" stroke="#e5e7eb"/>
  <line x1="{width - 270}" y1="22" x2="{width - 240}" y2="22" stroke="{color1}" stroke-width="2.5"/>
  <text x="{width - 235}" y="26" font-size="11" fill="#374151">{label1}</text>
  <line x1="{width - 130}" y1="22" x2="{width - 100}" y2="22" stroke="{color2}" stroke-width="2.5"/>
  <text x="{width - 95}" y="26" font-size="11" fill="#374151">{label2}</text>"""

    return elements


def _render_business_bars(years, container, terminal):
    """渲染业务分部柱状图。"""
    width, height, margin = 720, 280, 56
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin
    all_years = sorted(years)

    # 合并所有可用值以确定 y 范围
    all_vals = [v for v in list(container.values()) + list(terminal.values()) if v is not None]
    if not all_vals:
        return '<text x="360" y="140" text-anchor="middle" font-size="14" fill="#d1d5db">暂无分部收入数据</text>'

    ymax = max(all_vals) * 1.2
    n = len(all_years)
    bar_w = plot_w / n * 0.35
    elements = ""

    for i, yr in enumerate(all_years):
        cx = margin + i * plot_w / n - bar_w
        tx = cx + bar_w * 2

        # Container bar
        cv = container.get(yr)
        if cv is not None:
            ch = cv / ymax * plot_h
            cy = margin + plot_h - ch
            elements += f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{bar_w:.1f}" height="{ch:.1f}" fill="#2563eb" opacity="0.85" rx="2"/>'

        # Terminal bar
        tv = terminal.get(yr)
        if tv is not None:
            th = tv / ymax * plot_h
            ty = margin + plot_h - th
            elements += f'<rect x="{tx:.1f}" y="{ty:.1f}" width="{bar_w:.1f}" height="{th:.1f}" fill="#16a34a" opacity="0.85" rx="2"/>'

    # X ticks
    elements += "".join(
        f'<text x="{margin + i * plot_w / n:.1f}" y="{height - margin + 18}" text-anchor="middle" font-size="11" fill="#374151">{yr}</text>'
        for i, yr in enumerate(all_years)
    )

    # Legend
    elements += f"""<rect x="{width - 300}" y="10" width="290" height="34" rx="4" fill="white" stroke="#e5e7eb"/>
  <rect x="{width - 290}" y="17" width="14" height="14" rx="2" fill="#2563eb" opacity="0.85"/>
  <text x="{width - 272}" y="28" font-size="11" fill="#374151">集装箱航运收入（亿元）</text>
  <rect x="{width - 135}" y="17" width="14" height="14" rx="2" fill="#16a34a" opacity="0.85"/>
  <text x="{width - 117}" y="28" font-size="11" fill="#374151">码头业务收入（亿元）</text>"""

    return elements


def _build_dividend_table(years, dps, total, metrics):
    rows = ""
    for y in years:
        dp = dps.get(y)
        dt = total.get(y)
        r = get_row(metrics, "dividend_per_share", y)
        status = r["status"] if r else "missing"
        status_cn = {"reviewed": "已审核", "candidate": "待复核", "missing": "缺失"}.get(status, status)
        rows += f"<tr><td>{y}</td><td>{format_unit(dp)}</td><td>{format_unit(dt)}</td><td>{status_cn}</td></tr>"
    return rows


def _build_conclusion(revenue, net_profit, op_cf, roe, ccfi, dividend_total, dps, years):
    """基于已校验数据生成简短文字结论。"""
    years_list = list(years)
    last = years_list[-1]
    rev_last = revenue.get(last)
    np_last = net_profit.get(last)
    cf_last = op_cf.get(last)
    roe_last = roe.get(last)
    div_last = dividend_total.get(last)
    dps_last = dps.get(last)

    parts = []
    if rev_last:
        parts.append(f"中远海控{last}年实现营业收入 {rev_last:.0f} 亿元。")
    if np_last:
        parts.append(f"归属于上市公司股东的净利润为 {np_last:.0f} 亿元。")
    if cf_last:
        parts.append(f"经营活动产生的现金流量净额为 {cf_last:.0f} 亿元。")
    if roe_last:
        parts.append(f"加权平均净资产收益率（ROE）为 {roe_last:.2f}%。")
    if dps_last:
        parts.append(f"每股派发现金股利 {dps_last:.2f} 元（含税）。")
    if div_last:
        parts.append(f"年度现金分红总额约 {div_last:.1f} 亿元。")

    # 周期特征
    np_clean = {y: v for y, v in net_profit.items() if v is not None}
    if len(np_clean) >= 3:
        vals = sorted(np_clean.values())
        peak = vals[-1]
        trough = vals[0]
        peak_y = [y for y, v in net_profit.items() if v == peak][0]
        parts.append(f"纵观{min(years_list)}-{max(years_list)}年，公司归母净利润在{peak_y}年达到峰值 {peak:.0f} 亿元、低谷约 {trough:.0f} 亿元，波动幅度巨大，凸显集装箱航运业的强周期性特征。")

    html = "".join(f"<p style='margin-bottom:8px;'>{p}</p>" for p in parts)
    return f'<div style="font-size:14px;line-height:1.8;">{html}</div>'


def _build_sources(metrics, years):
    """构建数据来源索引。"""
    # 收集所有涉及的源文件
    source_files = set()
    for (mk, yr), r in metrics.items():
        sf = r.get("source_file", "")
        if sf:
            source_files.add(sf)

    html = "<ul style='font-size:13px;line-height:1.8;'>"
    html += "<li><strong>年报文件：</strong></li>"
    for sf in sorted(source_files):
        html += f"<li style='margin-left:16px;'>- {sf}</li>"

    # CCFI 来源
    ccfi_rows = [(yr, r) for (mk, yr), r in metrics.items() if mk == "ccfi_average" and r.get("status") != "missing"]
    if ccfi_rows:
        html += "<li style='margin-top:8px;'><strong>CCFI 外部来源（年报未覆盖年份）：</strong></li>"
        html += "<li style='margin-left:16px;'>- 交通运输部 / 上海航运交易所公开数据（CCFI 综合指数）</li>"

    # 缺失项
    missing = [(mk, yr) for (mk, yr), r in metrics.items() if r.get("status") == "missing"]
    if missing:
        html += "<li style='margin-top:8px;'><strong>缺失项（需外部补齐或人工补录）：</strong></li>"
        for mk, yr in sorted(missing, key=lambda x: (x[1], x[0])):
            html += f"<li style='margin-left:16px;'>- [{mk}] {yr} 年</li>"

    html += "</ul>"
    return html


def main():
    parser = argparse.ArgumentParser(description="生成 Value Line HTML 报告")
    parser.add_argument("--metrics", default="data/value_line_metrics_reviewed.csv")
    parser.add_argument("--output", default="reports/cosco_value_line.html")
    parser.add_argument("--start-year", type=int, default=2017)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--ccfi-weekly", default=DEFAULT_WEEKLY_CCFI_PATH)
    args = parser.parse_args()

    if not os.path.exists(args.metrics):
        print(f"ERROR: 指标表不存在: {args.metrics}", file=sys.stderr)
        print("请先运行: python scripts/extract_metrics.py && python scripts/validate_metrics.py", file=sys.stderr)
        sys.exit(1)

    build_html(args.metrics, args.output, args.start_year, args.end_year, args.ccfi_weekly)


if __name__ == "__main__":
    main()
