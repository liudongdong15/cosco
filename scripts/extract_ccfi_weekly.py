#!/usr/bin/env python3
"""Extract weekly CCFI rows from screenshot OCR text into a draft CSV.

The OCR dependency is intentionally optional. The reviewed CSV remains the
source of truth for report generation; this script only produces a candidate
file for human review.
"""

import argparse
import csv
import os
import re
import shutil
import sys
from datetime import date
from typing import Dict, Iterable, List, Optional


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


def normalize_number(token: str) -> float:
    cleaned = token.replace(",", "").replace("，", "").strip()
    return float(cleaned)


def parse_ccfi_row(text: str) -> Optional[Dict[str, str]]:
    """Parse one OCR text line containing YYYYMMDD and a CCFI value."""
    date_match = re.search(r"\b(20\d{6})\b", text)
    if not date_match:
        return None

    raw_date = date_match.group(1)
    tail = text[date_match.end():]
    value_match = re.search(r"(\d{1,3}(?:[,，]\d{3})+\.\d+|\d+\.\d+)", tail)
    if not value_match:
        return None

    parsed_date = date(
        int(raw_date[:4]),
        int(raw_date[4:6]),
        int(raw_date[6:8]),
    )
    iso_year, iso_week, _ = parsed_date.isocalendar()
    ccfi = normalize_number(value_match.group(1))
    return {
        "date": parsed_date.isoformat(),
        "year": str(parsed_date.year),
        "iso_week": f"{iso_year}-W{iso_week:02d}",
        "week_of_year": str(iso_week),
        "ccfi": f"{ccfi:.2f}",
        "ocr_text": text.strip(),
    }


def extract_rows_from_text(text: str, source_image: str = "") -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        parsed = parse_ccfi_row(line)
        if parsed:
            parsed["source_image"] = source_image
            parsed["source_row"] = str(idx)
            parsed["status"] = "candidate"
            parsed["review_note"] = ""
            rows.append(parsed)
    return rows


def _require_ocr_backend():
    if shutil.which("tesseract") is None:
        raise RuntimeError("未找到 tesseract；请安装 OCR 后端，或手工维护 reviewed CSV。")
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError as exc:
        raise RuntimeError("未安装 pytesseract/Pillow；请安装后再运行 OCR 草稿提取。") from exc
    return pytesseract, Image


def extract_rows_from_images(image_dir: str) -> List[Dict[str, str]]:
    pytesseract, Image = _require_ocr_backend()
    rows: List[Dict[str, str]] = []
    image_names = sorted(
        name for name in os.listdir(image_dir)
        if name.lower().endswith((".jpg", ".jpeg", ".png"))
    )
    for image_name in image_names:
        path = os.path.join(image_dir, image_name)
        with Image.open(path) as image:
            text = pytesseract.image_to_string(image, lang="eng")
        rows.extend(extract_rows_from_text(text, image_name))
    return rows


def dedupe_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    by_date: Dict[str, Dict[str, str]] = {}
    for row in rows:
        existing = by_date.get(row["date"])
        if existing is None:
            by_date[row["date"]] = row
            continue
        if existing["ccfi"] != row["ccfi"]:
            raise ValueError(
                f"重复日期数值冲突: {row['date']} {existing['ccfi']} vs {row['ccfi']}"
            )
    return [by_date[d] for d in sorted(by_date)]


def write_csv(rows: List[Dict[str, str]], output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDNAMES})


def main() -> int:
    parser = argparse.ArgumentParser(description="从 CCFI 周均值截图 OCR 生成候选 CSV")
    parser.add_argument("--images", default="data/external_sources/ccfi_weekly_images")
    parser.add_argument("--output", default="data/external_sources/ccfi_weekly_draft.csv")
    args = parser.parse_args()

    try:
        rows = dedupe_rows(extract_rows_from_images(args.images))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    write_csv(rows, args.output)
    print(f"CCFI 周均值 OCR 草稿已生成: {args.output} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
