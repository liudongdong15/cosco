#!/usr/bin/env python3
"""从 akshare 获取 A 股行情数据，计算年末估值指标（收盘价、PE、PB、市值、年度高低点）。

用法:
  python scripts/fetch_market.py                      # 默认 601919，2017-当前
  python scripts/fetch_market.py --year 2025           # 只看某一年
  python scripts/fetch_market.py --csv                 # 输出 CSV 格式
  python scripts/fetch_market.py --metrics data/value_line_metrics_reviewed.csv  # 指定指标文件
"""

import argparse
import csv
import os
import sys
import io
from typing import Optional

import akshare as ak


def load_fundamentals(metrics_path: str) -> dict:
    """从审核版指标 CSV 加载 EPS 和归母权益（计算 BPS 用）。"""
    eps = {}
    equity = {}  # 归母权益，亿元
    if not os.path.exists(metrics_path):
        print(f"WARNING: 指标文件 {metrics_path} 不存在，PE/PB 将无法计算", file=sys.stderr)
        return eps, equity

    with open(metrics_path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("status") != "reviewed":
                continue
            year = int(r["year"])
            mk = r["metric_key"]
            try:
                val = float(r["value"])
            except (ValueError, TypeError):
                continue
            if mk == "eps":
                eps[year] = val
            elif mk == "equity_parent":
                equity[year] = val

    return eps, equity


def fetch_daily(symbol: str = "601919") -> "pd.DataFrame":
    """获取日线数据（不复权，反映当年实际交易价格）。"""
    code = f"sh{symbol}" if symbol.startswith("6") else f"sz{symbol}"
    df = ak.stock_zh_a_daily(symbol=code, start_date="20170101", end_date="20991231", adjust="")
    df["date"] = df["date"].astype(str)
    return df


def compute_year_metrics(df, year: int, eps: dict, equity: dict) -> Optional[dict]:
    """计算单个年份的估值指标。"""
    year_str = str(year)
    year_data = df[df["date"].str.startswith(year_str)]
    if year_data.empty:
        return None

    last = year_data.iloc[-1]
    close = float(last["close"])
    high = float(year_data["high"].max())
    low = float(year_data["low"].min())
    shares = float(last["outstanding_share"]) / 1e8  # 亿股

    market_cap = close * shares  # 亿元

    result = {
        "year": year,
        "close": round(close, 2),
        "high": round(high, 2),
        "low": round(low, 2),
        "shares": round(shares, 2),
        "market_cap": round(market_cap, 0),
    }

    # PE = 收盘价 / 每股收益
    ep = eps.get(year)
    if ep and ep > 0:
        result["pe"] = round(close / ep, 1)
    else:
        result["pe"] = None

    # PB = 收盘价 / 每股净资产
    eq = equity.get(year)
    if eq and shares > 0:
        bps = eq / shares
        result["bps"] = round(bps, 2)
        result["pb"] = round(close / bps, 2)
    else:
        result["bps"] = None
        result["pb"] = None

    return result


def print_table(results: list[dict]):
    """打印估值汇总表。"""
    header = f"{'年份':<6} {'年末收盘':<10} {'最高':<8} {'最低':<8} {'市值(亿)':<12} {'EPS':<8} {'BPS':<8} {'PE':<8} {'PB':<8}"
    print(header)
    print("-" * len(header))
    for r in results:
        pe_str = f"{r['pe']:.1f}" if r.get("pe") else "-"
        pb_str = f"{r['pb']:.2f}" if r.get("pb") else "-"
        bps_str = f"{r['bps']:.2f}" if r.get("bps") else "-"
        print(f"{r['year']:<6} {r['close']:<10.2f} {r['high']:<8.2f} {r['low']:<8.2f} "
              f"{r['market_cap']:<12.0f} {r.get('_eps', '-'):<8} {bps_str:<8} {pe_str:<8} {pb_str:<8}")


def print_csv(results: list[dict], eps: dict):
    """输出 CSV 格式，可追加到 value_line_metrics.csv。"""
    src_url = "akshare.stock_zh_a_daily(symbol='sh601919', adjust='') 不复权日线"
    # Use csv.writer for proper quoting
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["metric_key","metric_name","year","value","unit","source_type","source_file","page","source_url","evidence_text","confidence","status","note"])
    sys.stdout.write(out.getvalue())

    for r in results:
        y = r["year"]
        rows = []
        # 年末收盘价
        rows.append(["year_end_close","年末收盘价",str(y),str(r["close"]),"元","external","","",src_url,"akshare stock_zh_a_daily 不复权年末收盘价","high","reviewed","自动获取"])
        # 年度最高
        rows.append(["year_high","年度最高价",str(y),str(r["high"]),"元","external","","",src_url,"akshare stock_zh_a_daily 不复权年度最高价","high","reviewed","自动获取"])
        # 年度最低
        rows.append(["year_low","年度最低价",str(y),str(r["low"]),"元","external","","",src_url,"akshare stock_zh_a_daily 不复权年度最低价","high","reviewed","自动获取"])
        # 年末市值
        rows.append(["market_cap","年末总市值",str(y),f"{r['market_cap']:.0f}","亿元","external","","",src_url,"akshare: 年末收盘价×流通股本","high","reviewed","自动获取"])
        # PE
        pe_str = f"{r['pe']:.1f}" if r.get("pe") else ""
        pe_note = "" if r.get("pe") else "EPS为负或缺失，无法计算PE"
        rows.append(["pe_year_end","年末市盈率PE",str(y),pe_str,"倍","external","","",src_url,"akshare: 年末收盘价÷EPS","high","reviewed",pe_note])
        # PB
        pb_str = f"{r['pb']:.2f}" if r.get("pb") else ""
        pb_note = "" if r.get("pb") else "权益数据缺失，无法计算PB"
        rows.append(["pb_year_end","年末市净率PB",str(y),pb_str,"倍","external","","",src_url,"akshare: 年末收盘价÷每股净资产","high","reviewed",pb_note])

        for row in rows:
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(row)
            sys.stdout.write(out.getvalue())


def main():
    parser = argparse.ArgumentParser(description="从 akshare 获取 A 股行情估值数据")
    parser.add_argument("--symbol", default="601919", help="股票代码 (默认 601919)")
    parser.add_argument("--year", type=int, help="只显示指定年份")
    parser.add_argument("--start-year", type=int, default=2017, help="起始年份")
    parser.add_argument("--metrics", default="data/value_line_metrics_reviewed.csv", help="审核版指标 CSV 路径")
    parser.add_argument("--csv", action="store_true", help="输出 CSV 格式")
    args = parser.parse_args()

    eps, equity = load_fundamentals(args.metrics)
    df = fetch_daily(args.symbol)

    end_year = args.year if args.year else 2025
    years = range(args.start_year, end_year + 1)

    results = []
    for y in years:
        r = compute_year_metrics(df, y, eps, equity)
        if r:
            r["_eps"] = f"{eps.get(y, 0):.2f}" if eps.get(y) else "-"
            results.append(r)

    if not results:
        print("无数据", file=sys.stderr)
        sys.exit(1)

    if args.csv:
        print_csv(results, eps)
    else:
        print_table(results)


if __name__ == "__main__":
    main()
