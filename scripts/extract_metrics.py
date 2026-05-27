#!/usr/bin/env python3
"""extract_metrics.py — 从 SQLite 语料库中抽取候选指标表。"""

import argparse
import csv
import os
import re
import sqlite3
import sys
from typing import Optional


# ============================================================
# 指标定义
# ============================================================
METRICS = {
    "revenue": "营业收入",
    "net_profit_parent": "归属于上市公司股东的净利润",
    "operating_cash_flow": "经营活动产生的现金流量净额",
    "total_assets": "总资产",
    "equity_parent": "归属于上市公司股东的净资产",
    "eps": "基本每股收益",
    "roe": "加权平均净资产收益率",
    "container_shipping_revenue": "集装箱航运收入",
    "terminal_revenue": "码头业务收入",
    "dividend_total": "分红总额",
    "dividend_per_share": "每股股利",
    "ccfi_average": "CCFI 年均值",
}

# 字段
FIELDS = [
    "metric_key", "metric_name", "year", "value", "unit",
    "source_type", "source_file", "page", "evidence_text",
    "confidence", "status", "note",
]


def parse_chinese_number(text: str) -> Optional[float]:
    """解析带千分位逗号和空格的中文数字。"""
    clean = text.replace(",", "").replace("，", "").replace(" ", "").strip()
    try:
        return float(clean)
    except ValueError:
        return None


def normalize_text(text: str) -> str:
    """归一化 PDF 文本：折叠连续空白字符为单个空格。"""
    return re.sub(r"\s+", " ", text).strip()


# 数字捕获正则：允许数字内部有空格（PDF 换行导致），懒匹配防止跨数字合并
NUM_RE = r"(\d[\d, ]*(?:\.\d+)?)"


def make_cjk_flex(pattern: str) -> str:
    """在连续中文字符间插入 \\s*，使正则可匹配 PDF 中带空格的标签文本。"""
    result = []
    prev_cjk = False
    for ch in pattern:
        is_cjk = '一' <= ch <= '鿿'
        if prev_cjk and is_cjk:
            result.append(r'\s*')
        result.append(ch)
        prev_cjk = is_cjk
    return ''.join(result)


def to_yi(value_in_yuan: float) -> float:
    """元 → 亿元"""
    return round(value_in_yuan / 100_000_000, 2)


def extract_main_accounting_data(conn: sqlite3.Connection, year: int) -> list[dict]:
    """从'主要会计数据'表抽取核心财务指标。"""
    # 只搜索主要财务数据表区域（第 5-15 页），跳过摘要/提示页（1-3 页）
    rows = conn.execute("""
        SELECT year, source_file, page, text FROM annual_chunks
        WHERE year=? AND page >= 5 AND page < 16
        ORDER BY page, rowid
    """, (year,)).fetchall()

    if not rows:
        return []

    # 按页合并文本，避免 chunk 边界截断数字
    page_texts = {}
    source_file = rows[0][1]
    for row in rows:
        p = row[2]
        if p not in page_texts:
            page_texts[p] = []
        page_texts[p].append(row[3])

    results = []

    for page in sorted(page_texts.keys()):
        text = "\n".join(page_texts[page])

        # 找营业收入
        _extract_metric_value(
            text, source_file, page, year,
            r"营业收入\s*[\s\S]*?(\d[\d, ]*(?:\.\d+)?)",
            "revenue", "营业收入", "亿元", "annual_report", results,
            post_process=to_yi,
        )

        # 找归属于上市公司股东的净利润（不含"扣除非经常性损益"）
        _extract_metric_value(
            text, source_file, page, year,
            r"归属于上市公司股东[的]*净利润\s*[\s\S]*?(\d[\d, ]*(?:\.\d+)?)",
            "net_profit_parent", "归属于上市公司股东的净利润", "亿元", "annual_report", results,
            post_process=to_yi,
            avoid_pattern=r"扣除非经常性",
        )

        # 找经营活动产生的现金流量净额
        _extract_metric_value(
            text, source_file, page, year,
            r"经营活动产生的现金流量净额\s*[\s\S]*?(\d[\d, ]*(?:\.\d+)?)",
            "operating_cash_flow", "经营活动产生的现金流量净额", "亿元", "annual_report", results,
            post_process=to_yi,
        )

        # 找总资产
        _extract_metric_value(
            text, source_file, page, year,
            r"总资产\s*[\s\S]*?(\d[\d, ]*(?:\.\d+)?)",
            "total_assets", "总资产", "亿元", "annual_report", results,
            post_process=to_yi,
        )

        # 找归属于上市公司股东的净资产
        _extract_metric_value(
            text, source_file, page, year,
            r"归属于上市公司股东[的]*净资产\s*[\s\S]*?(\d[\d, ]*(?:\.\d+)?)",
            "equity_parent", "归属于上市公司股东的净资产", "亿元", "annual_report", results,
            post_process=to_yi,
        )

        # 找基本每股收益
        _extract_metric_value(
            text, source_file, page, year,
            r"基本每股收益[（(]?[元股／/.]*[）)]?\s*[\s\S]*?(\d[\d, ]*(?:\.\d+)?)",
            "eps", "基本每股收益", "元/股", "annual_report", results,
        )

        # 找加权平均净资产收益率
        _extract_metric_value(
            text, source_file, page, year,
            r"加权平均净资产收益率[（(]?[%％]?[）)]?\s*[\s\S]*?(\d[\d, ]*(?:\.\d+)?)",
            "roe", "加权平均净资产收益率", "%", "annual_report", results,
        )

    # 去重：只保留每 metric_key 第一次出现在最前面的 page
    seen = set()
    deduped = []
    for r in sorted(results, key=lambda x: x["page"]):
        key = (r["metric_key"], r["year"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    return deduped


def _extract_metric_value(
    text: str, source_file: str, page: int, year: int,
    pattern: str, metric_key: str, metric_name: str, unit: str,
    source_type: str, results: list,
    post_process=None,
    avoid_pattern: Optional[str] = None,
):
    """从文本中提取指标值，如果匹配成功则添加到结果列表。"""
    normalized = normalize_text(text)

    # 允许标签中嵌入空白字符
    flex_pattern = make_cjk_flex(pattern)

    # 如果指定了避让模式，先检查是否匹配了不该匹配的行
    if avoid_pattern:
        m = re.search(flex_pattern, normalized, re.DOTALL)
        if m:
            match_text = m.group(0)
            if re.search(avoid_pattern, match_text):
                return
        else:
            return

    m = re.search(flex_pattern, normalized, re.DOTALL)
    if not m:
        return

    raw_value = m.group(1)
    value = parse_chinese_number(raw_value)
    if value is None:
        return

    if post_process:
        value = post_process(value)

    # 提取证据片段：取匹配内容前50字到后80字
    start = max(0, m.start() - 50)
    end = min(len(normalized), m.end() + 80)
    evidence = normalized[start:end].strip()

    results.append({
        "metric_key": metric_key,
        "metric_name": metric_name,
        "year": year,
        "value": value,
        "unit": unit,
        "source_type": source_type,
        "source_file": source_file,
        "page": page,
        "evidence_text": evidence[:300],
        "confidence": "high",
        "status": "candidate",
        "note": "",
    })


def extract_dividend_info(conn: sqlite3.Connection, year: int) -> list[dict]:
    """从年报中抽取分红信息。"""
    results = []
    found_total = False
    found_dps = False

    # FTS5 分词器不支持中文，用 LIKE 搜索
    rows = conn.execute("""
        SELECT year, source_file, page, text FROM annual_chunks
        WHERE year=? AND (text LIKE '%派发现金红利%' OR text LIKE '%每股派%' OR text LIKE '%现金分红%' OR text LIKE '%利润分配预案%')
        ORDER BY page
    """, (year,)).fetchall()

    for row in rows:
        if found_total and found_dps:
            break
        text = row[3]
        normalized = normalize_text(text)
        source_file = row[1]
        page = row[2]

        # 每股股利 — 多种格式
        if not found_dps:
            dps_patterns = [
                # "每股派发现金红利人民币1.03元（含税）" (优先匹配，最精确)
                (r"每\s*股\s*派\s*发\s*现\s*金\s*红\s*利\s*(?:人民币)?\s*(\d+\.?\d*)\s*元", 1.0),
                # "每股派发现金红利0.87元"
                (r"每\s*股\s*派\s*发\s*现\s*金\s*红\s*利\s*(\d+\.?\d*)\s*元", 1.0),
                # 表格格式: "每10股派息数(元)...0.87" — 匹配实际的派息数值，不是"10"
                (r"每\s*10\s*股\s*派\s*息\s*数.*?(\d+\.?\d*)", 0.1),
                # 简单格式
                (r"每股\s*股利\s*(\d+\.?\d*)\s*元", 1.0),
            ]
            for pat, multiplier in dps_patterns:
                m = re.search(pat, normalized)
                if m:
                    value = float(m.group(1)) * multiplier
                    # 质量检查：每股股利合理范围 0-3 元，且不是"每10股"中的10
                    if 0 <= value < 3 and value != 1.0:
                        results.append(make_dividend_record(
                            "dividend_per_share", "每股股利", year, value, "元/股",
                            source_file, page, normalized, m, "annual_report",
                            "从文本描述中抽取，需人工复核",
                        ))
                        found_dps = True
                        break

        # 分红总额 — 多种格式
        if not found_total:
            total_patterns = [
                # "合计派发现金红利约人民币161.31亿元（含税）"
                (r"合\s*计\s*(?:拟\s*)?派\s*发\s*现\s*金\s*红\s*利\s*(?:约)?\s*(?:人民币)?\s*(\d+\.?\d*)\s*亿", 1.0),
                # "合计派发现金红利139.32亿元"
                (r"合\s*计\s*派\s*发.*?(\d+\.?\d*)\s*亿", 1.0),
                # "拟派发现金红利人民币161.31亿元"
                (r"拟\s*派\s*发\s*现\s*金\s*红\s*利.*?(\d+\.?\d*)\s*亿", 1.0),
                # "现金分红总额为XXX亿元"
                (r"现\s*金\s*分\s*红\s*(?:总额|的数额).*?(\d+\.?\d*)\s*亿", 1.0),
                # 表格: "现金分红的数额（含税）...0.00" — 数字后是一行中的数字
                (r"现\s*金\s*分\s*红\s*的\s*数\s*额.*?(\d+\.?\d*)", 1.0),
                # "本年度公司现金分红...约人民币161.31亿元"
                (r"(?:本\s*年\s*度?)?(?:公司\s*)?现\s*金\s*分\s*红.*?(?:约)?\s*(?:人民币)?\s*(\d+\.?\d*)\s*亿", 1.0),
                # "拟向全体股东每股派发...合计拟派发现金红利约人民币161.31亿元"
                (r"合\s*计\s*拟\s*派\s*发.*?(?:人民币)?\s*(\d+\.?\d*)\s*亿", 1.0),
            ]
            for pat, multiplier in total_patterns:
                m = re.search(pat, normalized)
                if m:
                    value = float(m.group(1)) * multiplier
                    # 过滤年份误匹配 (2017-2025) 和异常值 (>500亿)
                    if 0 <= value < 500 and not (2017 <= value <= 2025):
                        results.append(make_dividend_record(
                            "dividend_total", "分红总额", year, value, "亿元",
                            source_file, page, normalized, m, "annual_report",
                            "从文本描述中抽取，需人工复核",
                        ))
                        found_total = True
                        break

    return results


def make_dividend_record(mk, mn, year, value, unit, sf, page, text, match, st, note):
    start = max(0, match.start() - 40)
    end = min(len(text), match.end() + 60)
    evidence = text[start:end].strip()
    return {
        "metric_key": mk, "metric_name": mn, "year": year,
        "value": value, "unit": unit, "source_type": st,
        "source_file": sf, "page": page,
        "evidence_text": evidence[:300],
        "confidence": "medium", "status": "candidate", "note": note,
    }


def extract_business_segments(conn: sqlite3.Connection, year: int) -> list[dict]:
    """从年报管理层讨论与分析部分抽取分部业务收入。"""
    results = []
    found_container = False
    found_terminal = False

    # FTS5 无中文分词器，改用 LIKE 避免漏页
    rows = conn.execute("""
        SELECT year, source_file, page, text FROM annual_chunks
        WHERE year=? AND (
            text LIKE '%集装箱航运%' OR text LIKE '%码头%业务%'
            OR text LIKE '%码头及%' OR text LIKE '%分部%'
        )
        ORDER BY page
    """, (year,)).fetchall()

    for row in rows:
        if found_container and found_terminal:
            break
        text = row[3]
        normalized = normalize_text(text)
        source_file = row[1]
        page = row[2]

        # 集装箱航运收入：在讨论分析段落中寻找
        if not found_container:
            # 用 make_cjk_flex 处理中文间的 PDF 空格
            base_direct = make_cjk_flex("集装箱航运业务收入")
            base_related = make_cjk_flex("集装箱航运及相关业务收入")
            container_patterns = [
                rf"{base_direct}\s*(?:约)?(?:为)?(?:人民币)?\s*{NUM_RE}\s*亿",
                rf"{base_related}\s*(?:约)?(?:为)?(?:人民币)?\s*{NUM_RE}\s*亿",
            ]
            for pat in container_patterns:
                m = re.search(pat, normalized)
                if m:
                    val = parse_chinese_number(m.group(1))
                    if val is None:
                        continue
                    if 10 < val < 100000:
                        results.append(make_segment_record(
                            "container_shipping_revenue", "集装箱航运收入", year, val, "亿元",
                            source_file, page, normalized, m,
                            "需人工确认金额口径(合并/分部/含/不含其他)",
                        ))
                        found_container = True
                        break

        # 码头业务收入
        if not found_terminal:
            base_direct = make_cjk_flex("码头业务收入")
            base_related = make_cjk_flex("码头及相关业务收入")
            base_csp = make_cjk_flex("中远海运港口码头业务收入")
            terminal_patterns = [
                rf"{base_direct}\s*(?:约)?(?:为)?(?:人民币)?\s*{NUM_RE}\s*亿",
                rf"{base_related}\s*(?:约)?(?:为)?(?:人民币)?\s*{NUM_RE}\s*亿",
                rf"{base_csp}\s*(?:约)?(?:为)?(?:人民币)?\s*{NUM_RE}\s*亿",
            ]
            for pat in terminal_patterns:
                m = re.search(pat, normalized)
                if m:
                    val = parse_chinese_number(m.group(1))
                    if val is None:
                        continue
                    if 0.5 < val < 10000:
                        results.append(make_segment_record(
                            "terminal_revenue", "码头业务收入", year, val, "亿元",
                            source_file, page, normalized, m,
                            "需人工确认金额口径",
                        ))
                        found_terminal = True
                        break

    return results


def make_segment_record(mk, mn, year, value, unit, sf, page, text, match, note):
    start = max(0, match.start() - 40)
    end = min(len(text), match.end() + 60)
    evidence = text[start:end].strip()
    return {
        "metric_key": mk, "metric_name": mn, "year": year,
        "value": value, "unit": unit, "source_type": "annual_report",
        "source_file": sf, "page": page,
        "evidence_text": evidence[:300],
        "confidence": "medium", "status": "candidate", "note": note,
    }


def extract_freight_volume(conn: sqlite3.Connection, year: int) -> Optional[float]:
    """从行业经营性信息分析章节提取本集团集装箱货运量合计（万TEU）。"""
    rows = conn.execute("""
        SELECT page, text FROM annual_chunks
        WHERE year=? AND page BETWEEN 8 AND 30
        AND text LIKE '%货运量%'
        ORDER BY page, rowid
    """, (year,)).fetchall()

    if not rows:
        return None

    page_texts = {}
    for p, t in rows:
        if p not in page_texts:
            page_texts[p] = []
        page_texts[p].append(t)

    candidates = []

    for page in sorted(page_texts.keys()):
        text = "\n".join(page_texts[page])
        normalized = normalize_text(text)

        # 模式1: 表格"合计"行 — "合计 27,434,538"
        if re.search(r"跨太平洋|亚欧|亚洲区内", normalized):
            for s in re.findall(r"合\s*计\s*(\d[\d,]{4,})", normalized):
                val = int(s.replace(",", "")) / 10000
                if 500 < val < 5000:
                    candidates.append(val)

        # 模式2: 叙述格式 — "完成货运量20,913,746 标准箱"
        for m in re.finditer(r"货运量\s*(\d[\d,]{4,})\s*标准箱", normalized):
            val = int(m.group(1).replace(",", "")) / 10000
            if 500 < val < 5000:
                candidates.append(val)

        # 模式3: "货运量2,634.45 万标准箱"
        for m in re.finditer(r"货运量\s*(\d[\d,.]*)\s*万\s*标准箱", normalized):
            val = float(m.group(1).replace(",", ""))
            if 500 < val < 5000:
                candidates.append(val)

    # 取最大值 = 本集团合计（表格中有本集团和中远海运集运两个合计）
    return max(candidates) if candidates else None


def extract_container_shipping_cost(conn: sqlite3.Connection, year: int) -> Optional[float]:
    """从管理层讨论部分提取集装箱航运业务成本（用于计算毛利率）。"""
    rows = conn.execute("""
        SELECT page, text FROM annual_chunks
        WHERE year=? AND page BETWEEN 13 AND 20
        AND text LIKE '%集装箱%成本%'
        ORDER BY page, rowid
    """, (year,)).fetchall()

    if not rows:
        return None

    # 按页合并文本，避免 chunk 截断
    page_texts = {}
    for p, t in rows:
        if p not in page_texts:
            page_texts[p] = []
        page_texts[p].append(t)

    # 两种表述：2017-2018 用"集装箱航运及相关业务成本"，2019+ 用"集装箱航运业务成本"
    patterns = [
        make_cjk_flex("集装箱航运业务成本"),
        make_cjk_flex("集装箱航运及相关业务成本"),
    ]

    for page in sorted(page_texts.keys()):
        text = "\n".join(page_texts[page])
        normalized = normalize_text(text)

        for flex_label in patterns:
            label_m = re.search(flex_label, normalized)
            if label_m:
                after_label = normalized[label_m.end():label_m.end() + 100]
                # 管理层讨论中成本数字已是亿元单位，直接取第一个 > 10亿 的数
                for num_m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)", after_label):
                    raw = num_m.group(1)
                    val = parse_chinese_number(raw)
                    if val is None:
                        continue
                    if 10 < val < 5000:
                        return val

    return None


def _extract_bonds_from_notes(page_texts: dict, source_file: str) -> Optional[float]:
    """从附注页提取应付债券期末余额，处理不适用/零值情况。"""
    notes_texts = []
    for p in sorted(page_texts.keys()):
        if p >= 170:
            notes_texts.append("\n".join(page_texts[p]))

    for text in notes_texts:
        normalized = normalize_text(text)

        # 检查不适用
        if re.search(r"应付债券.{0,30}(?:不适用|□适用\s*√不适用)", normalized, re.DOTALL):
            return 0.0

        # 找附注46：应付债券，匹配"合计"后的金额
        note_m = re.search(r"46[、.]\s*应付债券", normalized)
        if note_m:
            after = normalized[note_m.start():note_m.start() + 600]
            # 匹配"合计 / / / 2,909,862,719.06" 模式
            total_m = re.search(r"合计\s*/\s*/\s*/\s*(\d[\d,]*(?:\.\d+)?)", after)
            if total_m:
                val = parse_chinese_number(total_m.group(1))
                if val and val / 1e8 > 0.01:
                    return val / 1e8

            # 匹配"合计 2,909,862,719.06" 模式
            total_m2 = re.search(r"合\s*计\s*(\d[\d,]{6,}(?:\.\d+)?)", after)
            if total_m2:
                val = parse_chinese_number(total_m2.group(1))
                if val and val / 1e8 > 0.01:
                    return val / 1e8

            # 如果合计接近0（如0.01亿以内），返回0
            # 检查是否"减：一年内到期的应付债券" ≈ 总债券 → net ≈ 0
            if re.search(r"减[：:]\s*一[年]内到期.*?应付债券", after):
                # 找合计和一年内到期部分
                all_nums = re.findall(r"(\d[\d,]{6,}(?:\.\d+)?)", after)
                if len(all_nums) >= 2:
                    total_val = parse_chinese_number(all_nums[-1])  # 最后一个大数通常是合计
                    curr_val = parse_chinese_number(all_nums[0])    # 第一个大数可能是中期票据
                    if total_val and curr_val and abs(total_val - curr_val) / max(total_val, curr_val) < 0.001:
                        return 0.0

    # 仍未找到：如果资产负债表页的应付债券后面没有数字，可能是0
    for p in sorted(page_texts.keys()):
        if p < 170:
            text = "\n".join(page_texts[p])
            normalized = normalize_text(text)
            flex_label = make_cjk_flex("应付债券")
            label_m = re.search(flex_label, normalized)
            if label_m:
                after_label = normalized[label_m.end():label_m.end() + 50].strip()
                # 如果标签后只有附注编号或为空，视为0
                if not after_label or re.match(r"^[七]?[、，]?\s*\d{0,2}\s*$", after_label):
                    return 0.0

    return None


def extract_interest_bearing_debt(conn: sqlite3.Connection, year: int) -> list[dict]:
    """从合并资产负债表提取有息负债（短期借款+长期借款+应付债券+一年内到期非流动负债）。"""
    # 搜索资产负债表及附注区域（第 70-180 页），应付债券金额可能在附注中
    rows = conn.execute("""
        SELECT year, source_file, page, text FROM annual_chunks
        WHERE year=? AND page BETWEEN 70 AND 180
        AND (text LIKE '%短期借款%' OR text LIKE '%长期借款%'
             OR text LIKE '%应付债券%' OR text LIKE '%一年内到期的非流动负债%')
        ORDER BY page, rowid
    """, (year,)).fetchall()

    if not rows:
        return []

    # 按页合并文本
    page_texts = {}
    source_file = rows[0][1]
    for row in rows:
        p = row[2]
        if p not in page_texts:
            page_texts[p] = []
        page_texts[p].append(row[3])

    # 四项有息负债的定义及匹配模式
    debt_items = [
        ("short_borrow", make_cjk_flex("短期借款")),
        ("lt_borrow", make_cjk_flex("长期借款")),
        ("bonds", make_cjk_flex("应付债券")),
        ("curr_noncurrent", make_cjk_flex("一年内到期的非流动负债")),
    ]

    extracted = {}
    evidence_parts = {}

    for page in sorted(page_texts.keys()):
        text = "\n".join(page_texts[page])
        normalized = normalize_text(text)

        for key, flex_label in debt_items:
            if key in extracted:
                continue

            # 特殊处理：应付债券可能为 "应付债券 -"（零值）
            if key == "bonds":
                dash_pat = rf"{flex_label}\s*[-–—]"
                if re.search(dash_pat, normalized):
                    extracted[key] = 0.0
                    evidence_parts[key] = "应付债券0(资产负债表显示为-)"
                    continue

            # 应付债券在附注明细页（含"(1). 应付债券"或"46、应付债券"）不直接提取
            # 附注页通常同时包含长借和债券明细，易串扰
            if key == "bonds" and page >= 170 and re.search(r"(?:\(\d\)[.、\s]*应付债券|\d+[、.]\s*应付债券)", normalized):
                continue

            # 资产负债表格式: "label 七、XX 期末余额 期初余额"
            bs_num_re = re.compile(r"(\d[\d,]*(?:\.\d+)?)")
            label_m = re.search(flex_label, normalized)
            if label_m:
                after_label = normalized[label_m.end():label_m.end() + 150]
                for num_m in bs_num_re.finditer(after_label):
                    raw = num_m.group(1)
                    val = parse_chinese_number(raw)
                    if val is None:
                        continue
                    val_yi = val / 1e8
                    if 0.5 < val_yi < 10000:
                        extracted[key] = val_yi
                        evidence_parts[key] = (
                            f"{'短期借款' if key == 'short_borrow' else '长期借款' if key == 'lt_borrow' else '应付债券' if key == 'bonds' else '一年内到期非流动负债'}"
                            f"{val_yi:.2f}亿"
                        )
                        break

    # 应付债券回退：资产负债表上未匹配到数字时，检查附注
    if "bonds" not in extracted:
        bonds_val = _extract_bonds_from_notes(page_texts, source_file)
        if bonds_val is not None:
            extracted["bonds"] = bonds_val
            evidence_parts["bonds"] = f"应付债券{bonds_val:.2f}亿(附注)"

    if len(extracted) < 4:
        return []  # 数据不完整，不输出

    total = sum(extracted.values())
    evidence = "；".join(evidence_parts[k] for k, _ in debt_items)
    evidence += f"；合计{total:.2f}亿"

    return [{
        "metric_key": "interest_bearing_debt",
        "metric_name": "有息负债",
        "year": year,
        "value": f"{total:.2f}",
        "unit": "亿元",
        "source_type": "annual_report",
        "source_file": source_file,
        "page": min(page_texts.keys()),
        "evidence_text": evidence,
        "confidence": "high",
        "status": "candidate",
        "note": "短期借款+长期借款+应付债券+一年内到期的非流动负债",
    }]


def extract_ccfi(conn: sqlite3.Connection, year: int) -> list[dict]:
    """从年报中抽取 CCFI 参考值。"""
    rows = conn.execute("""
        SELECT c.year, c.source_file, c.page, c.text FROM annual_chunks_fts f
        JOIN annual_chunks c ON f.rowid = c.rowid
        WHERE c.year=? AND annual_chunks_fts MATCH 'CCFI'
        ORDER BY c.page
    """, (year,)).fetchall()

    results = []
    for row in rows:
        text = row[3]
        normalized = normalize_text(text)
        source_file = row[1]
        page = row[2]

        patterns = [
            (r"CCFI\s*(?:综合指数\s*)?均值\s*(\d+\.?\d*)", "CCFI 均值"),
            (r"CCFI\s*(?:综合指数\s*)?平均\s*(\d+\.?\d*)", "CCFI 平均"),
            (r"中国出口集装箱运价.*?CCFI[^0-9]*?(\d+\.?\d*)", "中国出口集装箱运价指数 CCFI"),
            (r"中国出口集装箱运价.*?均值[^0-9]*?(\d+\.?\d*)", "中国出口集装箱运价指数均值"),
        ]
        for pat, desc in patterns:
            m = re.search(pat, normalized)
            if m:
                value = float(m.group(1))
                # CCFI range: historically 600-3500
                if 600 < value < 3500:
                    # 额外检查：数字后面不应紧跟"年"
                    after_match = normalized[m.end():m.end()+5]
                    if "年" in after_match[:2]:
                        continue
                    start = max(0, m.start() - 40)
                    end = min(len(normalized), m.end() + 60)
                    evidence = normalized[start:end].strip()
                    results.append({
                        "metric_key": "ccfi_average",
                        "metric_name": "CCFI 年均值",
                        "year": year,
                        "value": value,
                        "unit": "点",
                        "source_type": "annual_report",
                        "source_file": source_file,
                        "page": page,
                        "evidence_text": evidence[:300],
                        "confidence": "medium",
                        "status": "candidate",
                        "note": f"年报参考值({desc})，可能非全年均值，需确认口径",
                    })
                    return results  # 取第一个匹配

    return results


def extract_metrics(db_path: str, start_year: int = 2017, end_year: int = 2025):
    conn = sqlite3.connect(db_path)
    all_rows = []

    for year in range(start_year, end_year + 1):
        print(f"抽取 {year} 年指标...")

        main_data = extract_main_accounting_data(conn, year)
        print(f"  核心财务指标: {len(main_data)} 项")
        all_rows.extend(main_data)

        dividend_data = extract_dividend_info(conn, year)
        print(f"  分红信息: {len(dividend_data)} 项")
        all_rows.extend(dividend_data)

        biz_data = extract_business_segments(conn, year)
        print(f"  分部业务收入: {len(biz_data)} 项")
        all_rows.extend(biz_data)

        ccfi_data = extract_ccfi(conn, year)
        print(f"  CCFI 参考值: {len(ccfi_data)} 项")
        all_rows.extend(ccfi_data)

        debt_data = extract_interest_bearing_debt(conn, year)
        print(f"  有息负债: {len(debt_data)} 项")
        all_rows.extend(debt_data)

        freight_vol = extract_freight_volume(conn, year)
        if freight_vol is not None:
            all_rows.append({
                "metric_key": "freight_volume",
                "metric_name": "航运运量",
                "year": year,
                "value": f"{freight_vol:.1f}",
                "unit": "万TEU",
                "source_type": "annual_report",
                "source_file": f"中远海控{year}年报.pdf",
                "page": "",
                "evidence_text": f"本集团货运量合计{freight_vol:.1f}万TEU",
                "confidence": "high",
                "status": "candidate",
                "note": "年报行业经营性信息分析-集装箱航运业务-货运量表格合计行",
            })
            print(f"  航运运量: {freight_vol:.1f} 万TEU")

        container_cost = extract_container_shipping_cost(conn, year)
        if container_cost is not None:
            all_rows.append({
                "metric_key": "container_shipping_cost",
                "metric_name": "集装箱航运成本",
                "year": year,
                "value": f"{container_cost:.2f}",
                "unit": "亿元",
                "source_type": "annual_report",
                "source_file": f"中远海控{year}年报.pdf",
                "page": "",
                "evidence_text": f"集装箱航运业务成本{container_cost:.2f}亿元",
                "confidence": "high",
                "status": "candidate",
                "note": "规则抽取，需人工确认口径",
            })
            print(f"  集装箱航运成本: {container_cost:.2f} 亿元")

    conn.close()

    # 按 metric_key、year 去重，保留第一个（按 page 最靠前）
    seen = set()
    deduped = []
    for r in sorted(all_rows, key=lambda x: (x["metric_key"], x["year"], x["page"])):
        key = (r["metric_key"], r["year"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    return deduped


def main():
    parser = argparse.ArgumentParser(description="从语料库抽取候选指标")
    parser.add_argument("--db", default="data/cosco_annuals.sqlite", help="SQLite 语料库路径")
    parser.add_argument("--output", default="data/value_line_metrics.csv", help="输出 CSV 路径")
    parser.add_argument("--start-year", type=int, default=2017)
    parser.add_argument("--end-year", type=int, default=2025)
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"ERROR: 语料库不存在: {args.db}", file=sys.stderr)
        print("请先运行: python scripts/build_corpus.py", file=sys.stderr)
        sys.exit(1)

    rows = extract_metrics(args.db, args.start_year, args.end_year)

    # 补充缺失记录：对每个未覆盖的 metric_key + year 添加 missing 记录
    covered = set()
    for r in rows:
        covered.add((r["metric_key"], r["year"]))
    for year in range(args.start_year, args.end_year + 1):
        for mk, mn in METRICS.items():
            if (mk, year) not in covered:
                rows.append({
                    "metric_key": mk, "metric_name": mn, "year": year,
                    "value": "", "unit": "",
                    "source_type": "missing",
                    "source_file": "", "page": "",
                    "evidence_text": "",
                    "confidence": "", "status": "missing",
                    "note": "未在年报中找到对应数据，需从外部来源或人工补录",
                })

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for r in sorted(rows, key=lambda x: (x["year"], x["metric_key"])):
            writer.writerow(r)

    # 统计
    by_status = {}
    by_metric = {}
    for r in rows:
        s = r["status"]
        by_status[s] = by_status.get(s, 0) + 1
        m = r["metric_key"]
        if m not in by_metric:
            by_metric[m] = set()
        by_metric[m].add(r["year"])

    print(f"\n候选指标抽取完成: {len(rows)} 条记录")
    print(f"状态分布: {by_status}")
    print(f"输出: {args.output}")
    print("\n各指标覆盖年份:")
    for mk, mn in METRICS.items():
        years = sorted(by_metric.get(mk, set()))
        missing = sorted(set(range(args.start_year, args.end_year + 1)) - set(years))
        status = f"✓ {len(years)}/{args.end_year - args.start_year + 1}" if not missing else f"✗ 缺 {missing}"
        print(f"  {mk}: {status}")


if __name__ == "__main__":
    main()
