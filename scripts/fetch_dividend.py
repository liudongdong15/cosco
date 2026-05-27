#!/usr/bin/env python3
"""从 akshare 获取 A 股分红数据，输出每股股利和分红总额。

用法:
  python scripts/fetch_dividend.py                    # 默认 601919 中远海控
  python scripts/fetch_dividend.py --symbol 600519    # 其他股票
  python scripts/fetch_dividend.py --year 2025         # 只看某一年
  python scripts/fetch_dividend.py --csv               # 输出 CSV 格式便于导入
"""

import argparse
import sys

import akshare as ak


def fetch_dividend(symbol: str = "601919") -> list[dict]:
    """返回分红记录列表，每条包含财年、中期/末期、每股股利(元)、总额提示。"""
    try:
        df = ak.stock_history_dividend_detail(symbol=symbol, indicator="分红")
    except Exception as e:
        print(f"ERROR: akshare 分红接口失败: {e}", file=sys.stderr)
        sys.exit(1)

    records = []
    for _, row in df.iterrows():
        plan_date = str(row["公告日期"])[:10]
        song = int(row["送股"]) if row["送股"] is not None else 0
        zhuan = int(row["转增"]) if row["转增"] is not None else 0
        pai_xi = float(row["派息"]) if row["派息"] is not None else 0.0
        progress = str(row["进度"])
        ex_date = str(row["除权除息日"])[:10] if str(row["除权除息日"]) != "NaT" else ""

        records.append({
            "公告日期": plan_date,
            "送股": song,
            "转增": zhuan,
            "派息_元每10股": pai_xi,
            "派息_元每股": round(pai_xi / 10, 4) if pai_xi > 0 else 0,
            "进度": progress,
            "除权除息日": ex_date,
        })

    return records


def assign_fiscal_year(records: list[dict]) -> list[dict]:
    """将分红记录归入对应财年，区分中期/末期。

    规则：除权日在 7 月及之前 → 上财年末期；除权日在 8 月及之后 → 当前财年中期。
    特殊情况：预案状态的为下一财年末期。
    """
    result = []
    for r in records:
        if r["派息_元每股"] == 0:
            continue  # 跳过不分配年份

        date_str = r["除权除息日"] if r["除权除息日"] else r["公告日期"]
        if not date_str:
            continue

        year = int(date_str[:4])
        month = int(date_str[5:7]) if len(date_str) >= 7 else 6

        if r["进度"] == "预案":
            # 预案通常是当年年报的末期分红，对应上一财年
            fiscal_year = year - 1
            dividend_type = "末期"
        elif month <= 7:
            fiscal_year = year - 1
            dividend_type = "末期"
        else:
            fiscal_year = year
            dividend_type = "中期"

        result.append({**r, "财年": fiscal_year, "类型": dividend_type})

    return result


def aggregate_by_fiscal_year(assigned: list[dict]) -> dict[int, dict]:
    """按财年汇总：全年每股股利 = 中期 + 末期。"""
    by_year: dict[int, dict] = {}
    for r in assigned:
        fy = r["财年"]
        if fy not in by_year:
            by_year[fy] = {"中期": 0, "末期": 0, "details": []}
        by_year[fy][r["类型"]] += r["派息_元每股"]
        by_year[fy]["details"].append(r)

    result = {}
    for fy, data in sorted(by_year.items()):
        result[fy] = {
            "中期": round(data["中期"], 4),
            "末期": round(data["末期"], 4),
            "全年": round(data["中期"] + data["末期"], 4),
            "details": data["details"],
        }
    return result


def print_table(by_year: dict[int, dict]):
    """打印可读的分红汇总表。"""
    print(f"{'财年':<6} {'中期(元/股)':<12} {'末期(元/股)':<12} {'全年(元/股)':<12}")
    print("-" * 42)
    for fy in sorted(by_year.keys()):
        d = by_year[fy]
        print(f"{fy:<6} {d['中期']:<12.2f} {d['末期']:<12.2f} {d['全年']:<12.2f}")


def print_csv(by_year: dict[int, dict]):
    """输出 CSV 格式，可直接追加到 value_line_metrics.csv。"""
    src_url = "akshare.stock_history_dividend_detail(symbol='601919')"
    print("metric_key,metric_name,year,value,unit,source_type,source_file,page,source_url,evidence_text,confidence,status,note")
    for fy in sorted(by_year.keys()):
        d = by_year[fy]
        detail_str = "；".join(
            f"{r['公告日期'][:10]} {r['类型']} {r['派息_元每股']}元/股"
            for r in d["details"]
        )
        print(f'dividend_per_share,每股股利,{fy},{d["全年"]},元/股,external,,,{src_url},akshare stock_history_dividend_detail: {detail_str},high,reviewed,akshare自动获取')

        # 分红总额需要总股本，这里只输出提示
        print(f'dividend_total,分红总额,{fy},,亿元,,,,{src_url},需根据总股本计算: {d["全年"]}元/股 × 总股本,medium,candidate,待填入总股本后确认')


def main():
    parser = argparse.ArgumentParser(description="从 akshare 获取 A 股分红数据")
    parser.add_argument("--symbol", default="601919", help="股票代码 (默认 601919 中远海控)")
    parser.add_argument("--year", type=int, help="只显示指定财年")
    parser.add_argument("--csv", action="store_true", help="输出 CSV 格式")
    args = parser.parse_args()

    records = fetch_dividend(args.symbol)
    assigned = assign_fiscal_year(records)
    by_year = aggregate_by_fiscal_year(assigned)

    if args.year:
        filtered = {args.year: by_year[args.year]} if args.year in by_year else {}
        if not filtered:
            print(f"财年 {args.year} 无分红数据", file=sys.stderr)
            sys.exit(1)
        by_year = filtered

    if args.csv:
        print_csv(by_year)
    else:
        print_table(by_year)
        print(f"\n共 {len(by_year)} 个财年有分红记录")
        print("使用 --csv 输出可导入的 CSV 格式")


if __name__ == "__main__":
    main()
