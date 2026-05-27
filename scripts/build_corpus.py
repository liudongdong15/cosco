#!/usr/bin/env python3
"""build_corpus.py — 从 annual/ 下年报 PDF 生成 SQLite FTS5 语料库。"""

import argparse
import hashlib
import os
import re
import sqlite3
import sys
from typing import Optional, Tuple


def extract_year(filename: str) -> Optional[int]:
    m = re.search(r"(\d{4})", os.path.basename(filename))
    return int(m.group(1)) if m else None


def chunk_text(text: str, max_len: int = 800) -> list[str]:
    """按自然段切分，超长段再按固定长度切分。"""
    paragraphs = re.split(r"\n\s*\n", text)
    chunks = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if len(p) <= max_len:
            chunks.append(p)
        else:
            for i in range(0, len(p), max_len):
                chunks.append(p[i:i + max_len])
    return chunks


def make_chunk_id(year: int, source_file: str, page: int, idx: int) -> str:
    raw = f"{year}:{source_file}:{page}:{idx}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def build_corpus(annual_dir: str, db_path: str, year_range: Optional[Tuple[int, int]] = None):
    pdf_files = sorted(
        [f for f in os.listdir(annual_dir) if f.lower().endswith(".pdf")]
    )
    if not pdf_files:
        print("ERROR: annual/ 下未找到 PDF 文件", file=sys.stderr)
        sys.exit(1)

    # 过滤年份
    if year_range:
        start_y, end_y = year_range
        pdf_files = [
            f for f in pdf_files
            if (y := extract_year(f)) and start_y <= y <= end_y
        ]

    print(f"找到 {len(pdf_files)} 份年报 PDF")

    # 连接 SQLite
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS annual_chunks (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id TEXT UNIQUE NOT NULL,
            year INTEGER NOT NULL,
            source_file TEXT NOT NULL,
            page INTEGER NOT NULL,
            text TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS annual_chunks_fts USING fts5(
            text,
            content='annual_chunks',
            content_rowid='rowid'
        )
    """)
    conn.execute("DELETE FROM annual_chunks")
    conn.execute("DELETE FROM annual_chunks_fts")
    conn.commit()

    # 使用 fitz (PyMuPDF) 提取文本
    import fitz

    total_chunks = 0
    for fname in pdf_files:
        fpath = os.path.join(annual_dir, fname)
        year = extract_year(fname)
        if year is None:
            print(f"  警告: 无法从文件名 '{fname}' 提取年份，跳过", file=sys.stderr)
            continue

        doc = fitz.open(fpath)
        print(f"  处理: {fname} ({year}, {doc.page_count} 页)")

        page = 0
        page_chunks = 0
        for page_idx in range(doc.page_count):
            text = doc[page_idx].get_text().strip()
            if not text:
                page += 1
                continue
            page += 1
            chunks = chunk_text(text)
            for ci, chunk in enumerate(chunks):
                cid = make_chunk_id(year, fname, page, ci)
                conn.execute(
                    "INSERT INTO annual_chunks (chunk_id, year, source_file, page, text) VALUES (?, ?, ?, ?, ?)",
                    (cid, year, fname, page, chunk),
                )
                page_chunks += 1
                total_chunks += 1

        doc.close()
        print(f"    → {page_chunks} chunks")

    # 重建 FTS 索引
    conn.execute("INSERT INTO annual_chunks_fts (rowid, text) SELECT rowid, text FROM annual_chunks")
    conn.commit()

    # 验证
    row_count = conn.execute("SELECT COUNT(*) FROM annual_chunks").fetchone()[0]
    fts_count = conn.execute("SELECT COUNT(*) FROM annual_chunks_fts").fetchone()[0]
    print(f"\n语料库构建完成: {row_count} chunks, FTS {fts_count} 条索引")
    print(f"数据库: {db_path}")

    # 基础检索测试
    test_queries = ["营业收入", "归属于上市公司股东的净利润", "CCFI"]
    print("\n检索测试:")
    for q in test_queries:
        rows = conn.execute(
            "SELECT c.year, c.source_file, c.page, c.text "
            "FROM annual_chunks_fts f "
            "JOIN annual_chunks c ON f.rowid = c.rowid "
            "WHERE annual_chunks_fts MATCH ? LIMIT 1",
            (q,),
        ).fetchall()
        if rows:
            r = rows[0]
            snippet = r[3].replace("\n", " ")[:120]
            print(f"  '{q}' → {r[0]} 年报 p{r[2]}: {snippet}...")
        else:
            print(f"  '{q}' → 未找到 (可能是编码差异)")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="构建年报 PDF 语料库")
    parser.add_argument("--annual-dir", default="annual", help="年报 PDF 目录 (默认: annual)")
    parser.add_argument("--db", default="data/cosco_annuals.sqlite", help="输出 SQLite 路径 (默认: data/cosco_annuals.sqlite)")
    parser.add_argument("--start-year", type=int, default=2017, help="起始年份 (默认: 2017)")
    parser.add_argument("--end-year", type=int, default=2025, help="结束年份 (默认: 2025)")
    args = parser.parse_args()

    if not os.path.isdir(args.annual_dir):
        print(f"ERROR: 目录不存在: {args.annual_dir}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(args.db), exist_ok=True)
    build_corpus(args.annual_dir, args.db, (args.start_year, args.end_year))


if __name__ == "__main__":
    main()
