#!/usr/bin/env python3
"""Validate reviewed weekly CCFI source data."""

import argparse
import csv
import os
import sys
from datetime import date
from typing import Dict, List, Tuple


FIELDNAMES = [
    "date",
    "year",
    "iso_week",
    "week_of_year",
    "ccfi",
    "source_image",
    "source_row",
    "ocr_text",
    "status",
    "review_note",
]
VALID_STATUSES = {"reviewed", "candidate", "missing"}
MIN_CCFI = 500.0
MAX_CCFI = 5000.0


def load_rows(path: str) -> List[Dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _expected_week_fields(date_text: str) -> Tuple[int, str, int]:
    parsed = date.fromisoformat(date_text)
    iso_year, iso_week, _ = parsed.isocalendar()
    return parsed.year, f"{iso_year}-W{iso_week:02d}", iso_week


def validate_rows(rows: List[Dict[str, str]], image_dir: str = "") -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    seen: Dict[str, str] = {}

    for idx, row in enumerate(rows, start=2):
        missing_fields = [field for field in FIELDNAMES if field not in row]
        if missing_fields:
            errors.append(f"第 {idx} 行缺少字段: {', '.join(missing_fields)}")
            continue

        status = row.get("status", "")
        if status not in VALID_STATUSES:
            errors.append(f"第 {idx} 行 status 非法: {status}")

        date_text = row.get("date", "")
        try:
            expected_year, expected_iso_week, expected_week = _expected_week_fields(date_text)
        except ValueError:
            errors.append(f"第 {idx} 行日期格式非法: {date_text}")
            continue

        if row.get("year") != str(expected_year):
            errors.append(f"第 {idx} 行 year 与 date 不一致: {row.get('year')} vs {expected_year}")
        if row.get("iso_week") != expected_iso_week:
            errors.append(f"第 {idx} 行 iso_week 与 date 不一致: {row.get('iso_week')} vs {expected_iso_week}")
        if row.get("week_of_year") != str(expected_week):
            errors.append(f"第 {idx} 行 week_of_year 与 date 不一致: {row.get('week_of_year')} vs {expected_week}")

        try:
            value = float(row.get("ccfi", ""))
        except ValueError:
            errors.append(f"第 {idx} 行 CCFI 数值非法: {row.get('ccfi')}")
            continue
        if not (MIN_CCFI <= value <= MAX_CCFI):
            warnings.append(f"第 {idx} 行 CCFI 超出常规区间: {value:.2f}")

        if date_text in seen and seen[date_text] != f"{value:.2f}":
            errors.append(f"重复日期数值冲突: {date_text} {seen[date_text]} vs {value:.2f}")
        else:
            seen[date_text] = f"{value:.2f}"

        source_image = row.get("source_image", "")
        if status == "reviewed" and not source_image:
            errors.append(f"第 {idx} 行 reviewed 记录缺少 source_image")
        if source_image and image_dir:
            image_path = os.path.join(image_dir, source_image)
            if not os.path.exists(image_path):
                errors.append(f"第 {idx} 行 source_image 不存在: {image_path}")

        source_row = row.get("source_row", "")
        if source_row:
            try:
                if int(source_row) <= 0:
                    errors.append(f"第 {idx} 行 source_row 必须为正整数: {source_row}")
            except ValueError:
                errors.append(f"第 {idx} 行 source_row 非法: {source_row}")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 CCFI 周均值事实表")
    parser.add_argument("path", nargs="?", default="data/external_sources/ccfi_weekly.csv")
    parser.add_argument("--image-dir", default="data/external_sources/ccfi_weekly_images")
    args = parser.parse_args()

    rows = load_rows(args.path)
    errors, warnings = validate_rows(rows, args.image_dir)
    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    reviewed = sum(1 for row in rows if row.get("status") == "reviewed")
    print(f"CCFI 周均值校验通过: {args.path} ({reviewed} reviewed rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
