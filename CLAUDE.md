# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Generating a Value Line style single-page research report for 中远海控 (COSCO SHIPPING Holdings, A-share `601919`) covering 2017-2025 + Q1 2026. All financial data comes from local annual/quarterly report PDFs or explicitly cited public external sources. The output is an offline-viewable HTML page.

## Architecture

```
cosco/
  annual/                        # Raw PDFs (2017-2025年报 + 2026Q1季报)
  data/
    cosco_annuals.sqlite         # PDF text corpus (SQLite + FTS5)
    value_line_metrics.csv       # Candidate metrics (extraction output)
    value_line_metrics_reviewed.csv  # Reviewed metrics (validation output)
    external_sources/
      ccfi_weekly.csv            # CCFI weekly data (2021-12 to present)
      ccfi_annual_sources.md     # CCFI annual source documentation
  scripts/
    build_corpus.py              # Stage 1: PDF → SQLite corpus
    extract_metrics.py           # Stage 2: Rule-based extraction → candidate CSV
    validate_metrics.py          # Stage 3: Validation → reviewed CSV
    build_value_line.py          # Stage 4: Render → offline HTML report
    fetch_dividend.py            # External: akshare dividend data → CSV
    fetch_market.py              # External: akshare market/PE/PB data → CSV
    audit_metrics.py             # Audit: PDF vs CSV cross-verification
    test_pipeline.py             # 56 unit + integration tests
  reports/
    cosco_value_line.html        # Generated report
  docs/reviews/                  # Code review & audit reports
  CLAUDE.md
```

## Data Pipeline (5 stages)

1. **build_corpus.py** — PyMuPDF extracts text from PDFs → SQLite `annual_chunks` table with FTS5 index. Note: FTS5 default tokenizer doesn't handle Chinese; use SQL `LIKE` for Chinese text search.
2. **extract_metrics.py** — Rule-based extraction from corpus → `data/value_line_metrics.csv` (candidate). Extracts: core financials (7 metrics), business segments (container/terminal revenue + cost), CCFI references, dividend info, interest-bearing debt, freight volume.
3. **validate_metrics.py** — Validates candidates: unit checks, sanity ranges, source verification, duplicate detection. Auto-promotes core high-confidence metrics to `reviewed`. Outputs `data/value_line_metrics_reviewed.csv`.
4. **build_value_line.py** — Loads reviewed metrics + external data (CCFI weekly, akshare market) → offline HTML with inline SVG charts, annual matrix table, valuation band, dividend summary, buyback summary.
5. **fetch_dividend.py / fetch_market.py** — Fetch external data from akshare (dividends, stock prices, PE/PB/market cap). Output CSV fragments for appending to the metrics CSV.

## Key Constraints

- **No fabricated numbers.** All metrics trace back to a PDF page (`source_file` + `page`) or a cited external source (`source_url`). External sources require `source_url` in a reproducible format (URL or `akshare.function_name()` reference).
- **Units must be consistent.** Revenue/profit/assets in 亿元, EPS/dividends in 元/股, ROE in %, freight volume in 万TEU, CCFI in 点.
- **Every metric has an evidence trail.** `source_file` + `page` for annual report data; `source_url` for external data. Validator enforces this.
- **No investment advice.** The report presents data and observations only — no target prices, buy/sell recommendations.
- **Quarterly reports.** Q1/H1/Q3 data for the current year (no annual report yet) shows as `2026Q1` columns. Once annual report data (dividend) exists, column label auto-switches to the year number.

## Metrics Tracked (20 metrics × 9 years + Q1 = 209 records)

| Category | Metrics | Source |
|----------|---------|--------|
| Core financials | revenue, net_profit_parent, operating_cash_flow, eps, roe, total_assets, equity_parent | Annual report p5-7 |
| Derived ratios | net_margin, equity_ratio, container_rev_ratio, container_gross_margin | Computed in build_value_line.py |
| Debt | interest_bearing_debt (short+long+bonds+current portion) | Balance sheet p70-105 + notes |
| Business segments | container_shipping_revenue/cost, terminal_revenue | Annual report p13-20 MD&A |
| Freight | freight_volume (万TEU) | Annual report 行业经营性信息分析 |
| CCFI | ccfi_average | Annual report (2017-2021) + external SIMIC (2022-2025) + ccfi_weekly.csv (Q1 2026) |
| Dividends | dividend_per_share, dividend_total | akshare + annual report profit distribution table |
| Buyback | buyback_amount (A+H 合计) | Annual report profit distribution table, akshare cross-verified |
| Market/valuation | year_end_close/high/low, market_cap, pe_year_end, pb_year_end | akshare 不复权日线 + EPS/equity from metrics |

## External Data Sources

- **akshare.stock_history_dividend_detail("601919")** — Dividend history (per-share amounts)
- **akshare.stock_zh_a_daily("sh601919", adjust="")** — Daily prices (不复权), used for PE/PB/market cap
- **akshare.stock_repurchase_em()** — A-share buyback amounts (cross-verification)
- **data/external_sources/ccfi_weekly.csv** — CCFI weekly data, used for quarterly CCFI averages
- **SIMIC (上海国际海事信息与文献网)** — Annual CCFI averages for 2022-2025

## Key Script Details

### extract_metrics.py patterns
- `make_cjk_flex(pattern)` — Inserts `\s*` between CJK characters to handle PDF text spacing
- `NUM_RE = r"(\d[\d, ]*(?:\.\d+)?)"` — Number regex supporting comma separators and spaces
- `parse_chinese_number(s)` — Strips commas/spaces before float conversion
- `to_yi(val)` — Converts 元 → 亿元
- Business segment extraction uses LIKE (not FTS5) to find pages, `make_cjk_flex` for label matching
- Freight volume extraction collects all candidates across pages, takes max (to avoid confusing 中远海运集运 sub-total with 本集团 total)

### build_value_line.py report structure
- Top grid: stock code, latest revenue/profit/ROE, PE, PB, date
- Quick read cards: 4 key metrics with growth sentences
- Left pane: 14-row annual matrix table, dual-axis trend chart (revenue+profit+cashflow+CCFI), A-share valuation band table (price/PE/PB/market cap)
- Right pane: CAGR sidebar, dividend compact (5-year: DPS/total/payout/yield), market & buyback summary, valuation notes, investment notes, data sources
- SVG charts: line_chart, dual_axis_chart, bar_chart — all inline, no external dependencies

### validate_metrics.py rules
1. Missing values → `missing` status
2. Core metrics must have values
3. Duplicate detection per (metric_key, year)
4. annual_report: requires `source_file` + `page`
5. external: requires `source_url` (validated via `is_valid_source_url`)
6. Sanity range check for high-confidence metrics
7. Unit required
8. Auto-review: core + high confidence → `reviewed`; manually set `reviewed` preserved
9. Core metric coverage check across all years

### CSV schema (FIELDS)
`metric_key, metric_name, year, value, unit, source_type, source_file, page, source_url, evidence_text, confidence, status, note`

## Testing

```bash
python3 scripts/test_pipeline.py       # 56 tests (unit + integration)
python3 scripts/audit_metrics.py       # PDF vs CSV cross-verification
python3 scripts/validate_metrics.py --strict --input data/value_line_metrics.csv   # Strict validation
```

## Current Status

- 9 annual reports (2017-2025) + 1 quarterly report (2026Q1) processed
- 209 metrics, all `reviewed` status
- Report generated at `reports/cosco_value_line.html`
- All 56 tests passing
- Remaining gaps: quarterly report extraction automation (currently manual), 航运毛利率 for Q1 (cost not disclosed in quarterly reports)
