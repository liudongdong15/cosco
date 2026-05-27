#!/usr/bin/env python3
"""test_pipeline.py — 管线关键函数的自动化单测 + 已知回归点。"""

import csv
import io
import os
import re
import sys
import tempfile
import unittest

# 将 scripts/ 加入路径，以便导入同目录脚本
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import extract_metrics as em
import validate_metrics as vm
import build_value_line as bvl
import extract_ccfi_weekly as ecw
import validate_ccfi_weekly as vcw


# ============================================================
# extract_metrics.py 单元测试
# ============================================================

class TestParseChineseNumber(unittest.TestCase):
    def test_plain_integer(self):
        self.assertEqual(em.parse_chinese_number("3840"), 3840.0)

    def test_thousands_comma(self):
        self.assertEqual(em.parse_chinese_number("3,840.36"), 3840.36)

    def test_chinese_comma(self):
        self.assertEqual(em.parse_chinese_number("2，107.31"), 2107.31)

    def test_internal_spaces(self):
        self.assertEqual(em.parse_chinese_number("1 096 844.57"), 1096844.57)

    def test_decimal(self):
        self.assertEqual(em.parse_chinese_number("12.30"), 12.30)

    def test_negative(self):
        self.assertEqual(em.parse_chinese_number("-103.25"), -103.25)

    def test_invalid_returns_none(self):
        self.assertIsNone(em.parse_chinese_number("abc"))

    def test_empty_returns_none(self):
        self.assertIsNone(em.parse_chinese_number(""))


class TestNormalizeText(unittest.TestCase):
    def test_collapses_whitespace(self):
        self.assertEqual(em.normalize_text("集装箱  航运\n业务  收入"), "集装箱 航运 业务 收入")

    def test_strips_edges(self):
        self.assertEqual(em.normalize_text("  中远海控  "), "中远海控")


class TestMakeCjkFlex(unittest.TestCase):
    def test_inserts_ws_between_cjk(self):
        result = em.make_cjk_flex("集装箱航运业务收入")
        self.assertIn(r"\s*", result)

    def test_preserves_regex_tokens(self):
        result = em.make_cjk_flex("(?:业务)?")
        self.assertIn("(?:", result)

    def test_no_ws_between_cjk_and_non_cjk(self):
        # "CCFI" 开头不是中文，后面 "综合指数" 是中文
        result = em.make_cjk_flex("CCFI综合指数")
        # CCFI 和 综 之间不应插入 \s* (因为 C 和 F 不是 CJK)
        self.assertFalse(result.startswith(r"\s*"))


class TestToYi(unittest.TestCase):
    def test_basic_conversion(self):
        self.assertEqual(em.to_yi(100_000_000), 1.0)

    def test_large_value(self):
        self.assertEqual(em.to_yi(219_504_000_000), 2195.04)

    def test_rounding(self):
        self.assertEqual(em.to_yi(123456789), 1.23)


class TestNumRe(unittest.TestCase):
    """回归测试：NUM_RE 必须支持千分位逗号和内部空格（Finding 2）。"""

    def test_comma_number_3840(self):
        m = re.search(em.NUM_RE, "业务收入3,840.36 亿元")
        self.assertIsNotNone(m)
        self.assertEqual(em.parse_chinese_number(m.group(1)), 3840.36)

    def test_comma_number_2107(self):
        m = re.search(em.NUM_RE, "业务收入2,107.31 亿元")
        self.assertIsNotNone(m)
        self.assertEqual(em.parse_chinese_number(m.group(1)), 2107.31)

    def test_plain_decimal(self):
        m = re.search(em.NUM_RE, "收入867.51 亿元")
        self.assertIsNotNone(m)
        self.assertEqual(em.parse_chinese_number(m.group(1)), 867.51)

    def test_integer_only(self):
        m = re.search(em.NUM_RE, "净利润1096 亿元")
        self.assertIsNotNone(m)
        self.assertEqual(em.parse_chinese_number(m.group(1)), 1096.0)

    def test_spaced_number(self):
        m = re.search(em.NUM_RE, "现金流量净额45 582 613 711.66 元")
        self.assertIsNotNone(m)
        self.assertEqual(em.parse_chinese_number(m.group(1)), 45582613711.66)


# ============================================================
# validate_metrics.py 单元测试
# ============================================================

class TestValidateMetrics(unittest.TestCase):
    def setUp(self):
        self.base_row = {
            "metric_key": "revenue",
            "metric_name": "营业收入",
            "year": "2022",
            "value": "3910.58",
            "unit": "亿元",
            "source_type": "annual_report",
            "source_file": "中远海控2022年报.pdf",
            "page": "6",
            "source_url": "",
            "evidence_text": "营业收入3910.58亿元",
            "confidence": "high",
            "status": "candidate",
            "note": "",
        }

    def _make_row(self, **overrides):
        r = dict(self.base_row)
        r.update(overrides)
        return r

    def test_core_metric_missing_value_error(self):
        rows = [self._make_row(metric_key="revenue", value="", status="candidate")]
        reviewed, errors, warnings = vm.validate_metrics(rows, 2022, 2022)
        self.assertTrue(any("核心指标缺失值" in e for e in errors))

    def test_non_core_missing_value_warning(self):
        rows = [self._make_row(metric_key="dividend_total", value="", status="candidate")]
        reviewed, errors, warnings = vm.validate_metrics(rows, 2022, 2022)
        self.assertTrue(any("非核心指标缺失值" in w for w in warnings))

    def test_duplicate_key_error(self):
        rows = [
            self._make_row(year="2022", value="100"),
            self._make_row(year="2022", value="200"),
        ]
        reviewed, errors, _ = vm.validate_metrics(rows, 2022, 2022)
        self.assertTrue(any("重复候选记录" in e for e in errors))

    def test_sanity_range_downgrades_confidence(self):
        """值超出 SANITY_RANGES 时应降级 confidence 并警告。"""
        rows = [self._make_row(metric_key="eps", value="9999", confidence="high")]
        reviewed, _, warnings = vm.validate_metrics(rows, 2022, 2022)
        self.assertTrue(any("超出预期范围" in w for w in warnings))
        self.assertEqual(reviewed[0]["confidence"], "medium")

    def test_missing_unit_error(self):
        rows = [self._make_row(unit="")]
        reviewed, errors, _ = vm.validate_metrics(rows, 2022, 2022)
        self.assertTrue(any("缺少单位" in e for e in errors))

    def test_annual_report_without_source_file_error(self):
        rows = [self._make_row(source_file="", page="")]
        reviewed, errors, _ = vm.validate_metrics(rows, 2022, 2022)
        self.assertTrue(any("年报来源缺少文件或页码" in e for e in errors))

    def test_external_without_reproducible_source_url_error(self):
        rows = [self._make_row(
            metric_key="ccfi_average",
            source_type="external",
            source_file="",
            page="",
            source_url="上海国际海事信息与文献网(SIMIC)",
            unit="点",
            value="2792.14",
            confidence="high",
            status="reviewed",
        )]
        reviewed, errors, _ = vm.validate_metrics(rows, 2022, 2022)
        self.assertTrue(any("source_url 不可复核" in e for e in errors))
        self.assertEqual(reviewed[0]["status"], "candidate")

    def test_external_with_file_source_url_passes(self):
        rows = [self._make_row(
            metric_key="ccfi_average",
            source_type="external",
            source_file="",
            page="",
            source_url="file://data/external_sources/ccfi_annual_sources.md#2022",
            unit="点",
            value="2792.14",
            confidence="high",
            status="reviewed",
        )]
        reviewed, errors, _ = vm.validate_metrics(rows, 2022, 2022)
        self.assertFalse(any("source_url 不可复核" in e for e in errors))
        self.assertEqual(reviewed[0]["status"], "reviewed")

    def test_core_high_confidence_auto_reviewed(self):
        rows = [self._make_row(metric_key="revenue", confidence="high")]
        reviewed, errors, _ = vm.validate_metrics(rows, 2022, 2022)
        self.assertEqual(reviewed[0]["status"], "reviewed")

    def test_non_core_high_confidence_stays_candidate(self):
        rows = [self._make_row(metric_key="dividend_total", confidence="high")]
        reviewed, errors, _ = vm.validate_metrics(rows, 2022, 2022)
        self.assertEqual(reviewed[0]["status"], "candidate")

    def test_unparseable_value_error(self):
        rows = [self._make_row(value="N/A")]
        reviewed, errors, _ = vm.validate_metrics(rows, 2022, 2022)
        self.assertTrue(any("无法解析数值" in e for e in errors))


# ============================================================
# build_value_line.py 单元测试
# ============================================================

class TestGetValue(unittest.TestCase):
    """回归测试：get_value 只返回 reviewed 状态的数值（Finding 1）。"""

    def setUp(self):
        self.metrics = {
            ("revenue", 2022): {"status": "reviewed", "value": "3910.58"},
            ("net_profit_parent", 2022): {"status": "candidate", "value": "1096.84"},
            ("dividend_total", 2022): {"status": "missing", "value": ""},
            ("revenue", 2023): {"status": "reviewed", "value": ""},
        }

    def test_reviewed_returns_value(self):
        self.assertEqual(bvl.get_value(self.metrics, "revenue", 2022), 3910.58)

    def test_candidate_returns_none(self):
        self.assertIsNone(bvl.get_value(self.metrics, "net_profit_parent", 2022))

    def test_missing_returns_none(self):
        self.assertIsNone(bvl.get_value(self.metrics, "dividend_total", 2022))

    def test_reviewed_but_empty_value_returns_none(self):
        self.assertIsNone(bvl.get_value(self.metrics, "revenue", 2023))

    def test_nonexistent_metric_returns_none(self):
        self.assertIsNone(bvl.get_value(self.metrics, "revenue", 2017))


class TestChartEmptyData(unittest.TestCase):
    """回归测试：图表函数在空数据时返回 '暂无数据'（最新 code review）。"""

    def test_line_chart_empty(self):
        svg = bvl.build_line_chart({})
        self.assertIn("暂无数据", svg)

    def test_dual_axis_empty(self):
        svg = bvl.build_dual_axis_chart({}, {})
        self.assertIn("暂无数据", svg)

    def test_bar_chart_empty(self):
        svg = bvl.build_bar_chart({})
        self.assertIn("暂无数据", svg)

    def test_render_dual_svg_empty(self):
        svg = bvl._render_dual_svg([2022], {}, {}, "", "", "", "")
        self.assertIn("暂无数据", svg)

    def test_render_business_bars_empty(self):
        svg = bvl._render_business_bars([2022], {}, {})
        self.assertIn("暂无分部收入数据", svg)


class TestObservationsCorrelation(unittest.TestCase):
    """回归测试：CCFI 观察不硬编码'高度正相关'（Finding 3）。"""

    def test_no_ccfi_no_claim(self):
        obs = bvl._generate_observations(
            revenue={2022: 3910},
            net_profit={2022: 1096},
            op_cf={2022: 500},
            roe={2022: 50},
            ccfi={},  # 无 CCFI 数据
            years=[2022],
        )
        # 不应包含任何 CCFI 相关断言
        self.assertNotIn("CCFI", obs)
        self.assertNotIn("高度正相关", obs)

    def test_ccfi_without_overlap_netprofit(self):
        """CCFI 有值但无对应年份净利润时，不出现强断言。"""
        obs = bvl._generate_observations(
            revenue={2022: 3910},
            net_profit={},  # 无净利润
            op_cf={},
            roe={},
            ccfi={2022: 1200},
            years=[2022],
        )
        self.assertNotIn("高度正相关", obs)


class TestBuildHtmlEntryGuard(unittest.TestCase):
    """回归测试：传入无 reviewed 核心指标的 CSV 时，入口校验应报错退出。"""

    def _write_csv(self, rows):
        """写入临时 CSV 并返回路径。"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8-sig", newline=""
        )
        writer = csv.DictWriter(tmp, fieldnames=[
            "metric_key", "metric_name", "year", "value", "unit",
            "source_type", "source_file", "page", "source_url", "evidence_text",
            "confidence", "status", "note",
        ])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
        tmp.close()
        return tmp.name

    def test_all_candidate_should_exit(self):
        rows = [
            {"metric_key": "revenue", "metric_name": "营业收入", "year": "2022",
             "value": "3910.58", "unit": "亿元", "source_type": "annual_report",
             "source_file": "test.pdf", "page": "6", "source_url": "", "evidence_text": "test",
             "confidence": "high", "status": "candidate", "note": ""},
        ]
        csv_path = self._write_csv(rows)
        try:
            with self.assertRaises(SystemExit) as cm:
                bvl.build_html(csv_path, "/tmp/test.html", 2022, 2022)
            self.assertNotEqual(cm.exception.code, 0)
        finally:
            os.unlink(csv_path)

    def test_some_reviewed_should_pass(self):
        rows = [
            {"metric_key": "revenue", "metric_name": "营业收入", "year": "2022",
             "value": "3910.58", "unit": "亿元", "source_type": "annual_report",
             "source_file": "test.pdf", "page": "6", "source_url": "", "evidence_text": "test",
             "confidence": "high", "status": "reviewed", "note": ""},
        ]
        csv_path = self._write_csv(rows)
        try:
            output = tempfile.NamedTemporaryFile(suffix=".html", delete=False)
            output.close()
            bvl.build_html(csv_path, output.name, 2022, 2022)
            self.assertTrue(os.path.getsize(output.name) > 0)
            os.unlink(output.name)
        finally:
            os.unlink(csv_path)


class TestWeeklyCcfi(unittest.TestCase):
    """CCFI 周均值数据表、OCR 清洗和 SVG 渲染测试。"""

    def _write_weekly_csv(self, rows):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8-sig", newline=""
        )
        writer = csv.DictWriter(tmp, fieldnames=ecw.FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        tmp.close()
        return tmp.name

    def _row(self, **overrides):
        row = {
            "date": "2026-05-22",
            "year": "2026",
            "iso_week": "2026-W21",
            "week_of_year": "21",
            "ccfi": "1317.36",
            "source_image": "sample.jpg",
            "source_row": "1",
            "ocr_text": "20260522 1,317.36",
            "status": "reviewed",
            "review_note": "",
        }
        row.update(overrides)
        return row

    def test_parse_ccfi_row_cleans_date_and_value(self):
        parsed = ecw.parse_ccfi_row("20260522 / 1,317.36")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["date"], "2026-05-22")
        self.assertEqual(parsed["ccfi"], "1317.36")

    def test_weekly_loader_filters_reviewed_and_sorts(self):
        path = self._write_weekly_csv([
            self._row(date="2026-05-22", year="2026", iso_week="2026-W21", week_of_year="21", ccfi="1317.36", status="candidate"),
            self._row(date="2026-05-15", year="2026", iso_week="2026-W20", week_of_year="20", ccfi="1280.46"),
            self._row(date="2026-05-08", year="2026", iso_week="2026-W19", week_of_year="19", ccfi="1278.79"),
        ])
        try:
            rows = bvl.load_weekly_ccfi(path)
            self.assertEqual([r["date"] for r in rows], ["2026-05-08", "2026-05-15"])
            self.assertEqual(rows[0]["ccfi"], 1278.79)
        finally:
            os.unlink(path)

    def test_weekly_loader_duplicate_conflict_errors(self):
        path = self._write_weekly_csv([
            self._row(ccfi="1317.36"),
            self._row(ccfi="1318.00", source_row="2"),
        ])
        try:
            with self.assertRaises(ValueError):
                bvl.load_weekly_ccfi(path)
        finally:
            os.unlink(path)

    def test_week_validation_rejects_mismatched_week(self):
        rows = [self._row(iso_week="2026-W20")]
        errors, _ = vcw.validate_rows(rows)
        self.assertTrue(any("iso_week 与 date 不一致" in err for err in errors))

    def test_weekly_chart_renders_year_lines(self):
        rows = [
            self._row(date="2025-01-03", year="2025", iso_week="2025-W01", week_of_year="1", ccfi="1547.74"),
            self._row(date="2025-01-10", year="2025", iso_week="2025-W02", week_of_year="2", ccfi="1560.87"),
            self._row(date="2026-05-22", year="2026", iso_week="2026-W21", week_of_year="21", ccfi="1317.36"),
        ]
        path = self._write_weekly_csv(rows)
        try:
            records = bvl.load_weekly_ccfi(path)
            svg = bvl._build_weekly_ccfi_chart(records)
            self.assertIn("CCFI周均值年内曲线", svg)
            self.assertIn('data-year="2025"', svg)
            self.assertIn('data-year="2026"', svg)
            self.assertGreaterEqual(svg.count("weekly-ccfi-line"), 2)
        finally:
            os.unlink(path)


class TestDualSvgEdgeCases(unittest.TestCase):
    """_render_dual_svg 边界情况测试。"""

    def test_one_side_has_data(self):
        """data1 有数据、data2 为空时不应崩溃。"""
        svg = bvl._render_dual_svg(
            [2022], {2022: 100}, {}, "left", "right", "#000", "#111"
        )
        self.assertNotIn("暂无数据", svg)  # 至少有一侧有数据

    def test_both_empty_returns_placeholder(self):
        svg = bvl._render_dual_svg(
            [2022], {}, {}, "left", "right", "#000", "#111"
        )
        self.assertIn("暂无数据", svg)


# ============================================================
# 集成测试
# ============================================================

class TestPipelineIntegration(unittest.TestCase):
    """端到端测试：从候选 CSV 到报告生成。"""

    @classmethod
    def setUpClass(cls):
        cls.data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
        )
        cls.candidate_csv = os.path.join(cls.data_dir, "value_line_metrics.csv")
        cls.reviewed_csv = os.path.join(cls.data_dir, "value_line_metrics_reviewed.csv")
        cls.corpus_db = os.path.join(cls.data_dir, "cosco_annuals.sqlite")

    def test_candidate_csv_exists(self):
        self.assertTrue(os.path.exists(self.candidate_csv),
                        f"候选 CSV 不存在: {self.candidate_csv}")

    def test_reviewed_csv_exists(self):
        self.assertTrue(os.path.exists(self.reviewed_csv),
                        f"审核版 CSV 不存在: {self.reviewed_csv}")

    def test_corpus_db_exists(self):
        self.assertTrue(os.path.exists(self.corpus_db),
                        f"语料库不存在: {self.corpus_db}")

    def test_candidate_csv_has_108_records(self):
        rows = vm.load_rows(self.candidate_csv)
        self.assertGreaterEqual(len(rows), 108)

    def test_core_metrics_all_9_years(self):
        """核心指标 9/9 覆盖。"""
        rows = vm.load_rows(self.reviewed_csv)
        for mk in vm.CORE_METRICS:
            for y in range(2017, 2026):
                found = [r for r in rows if r["metric_key"] == mk and int(r["year"]) == y]
                self.assertTrue(found, f"[{mk}] {y} 年缺失")

    def test_all_years_in_reviewed_csv(self):
        """审核版 CSV 涵盖 2017-2025。"""
        rows = vm.load_rows(self.reviewed_csv)
        years = sorted(set(int(r["year"]) for r in rows))
        self.assertIn(2017, years)
        self.assertIn(2025, years)

    def test_no_value_traceback_with_candidate_csv(self):
        """使用候选 CSV 调用 get_value 应全部返回 None（不报错）。"""
        metrics = bvl.load_metrics(self.reviewed_csv)
        for mk in vm.CORE_METRICS:
            for y in range(2017, 2026):
                v = bvl.get_value(metrics, mk, y)
                # 核心指标在审核版 CSV 中应该是 reviewed 并有值
                self.assertIsNotNone(v, f"[{mk}] {y} 应为 reviewed")

    def test_container_2022_value_correct(self):
        """回归测试 Finding 2：2022 集装箱航运收入 = 3840.36。"""
        rows = vm.load_rows(self.candidate_csv)
        for r in rows:
            if r["metric_key"] == "container_shipping_revenue" and r["year"] == "2022":
                if r["value"]:
                    self.assertEqual(float(r["value"]), 3840.36)
                return
        self.fail("未找到 2022 container_shipping_revenue 记录")

    def test_container_2025_value_correct(self):
        """回归测试 Finding 2：2025 集装箱航运收入 = 2107.31。"""
        rows = vm.load_rows(self.candidate_csv)
        for r in rows:
            if r["metric_key"] == "container_shipping_revenue" and r["year"] == "2025":
                if r["value"]:
                    self.assertEqual(float(r["value"]), 2107.31)
                return
        self.fail("未找到 2025 container_shipping_revenue 记录")

    def test_html_report_generates(self):
        """报告正常生成。"""
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
            output_path = tmp.name
        try:
            bvl.build_html(self.reviewed_csv, output_path, 2017, 2025)
            self.assertGreater(os.path.getsize(output_path), 5000,
                               "生成的 HTML 太小，可能为空")
            with open(output_path, encoding="utf-8") as f:
                html = f.read()
            self.assertNotIn("前复权", html)
            self.assertIn("不复权", html)
            annual_idx = html.index("收入、归母净利润、经营现金流 &amp; CCFI均值趋势")
            weekly_idx = html.index("CCFI周均值年内曲线")
            valuation_idx = html.index("A股估值带（601919.SH）")
            self.assertLess(annual_idx, weekly_idx)
            self.assertLess(weekly_idx, valuation_idx)
            self.assertIn("weekly-ccfi-svg", html)
            self.assertGreaterEqual(html.count("weekly-ccfi-line"), 4)
        finally:
            os.unlink(output_path)

    def test_html_without_weekly_csv_still_generates(self):
        """无周度 CCFI CSV 时仍生成年度报表。"""
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
            output_path = tmp.name
        try:
            bvl.build_html(self.reviewed_csv, output_path, 2017, 2025, "/tmp/not-exist-ccfi-weekly.csv")
            with open(output_path, encoding="utf-8") as f:
                html = f.read()
            self.assertIn("收入、归母净利润、经营现金流 &amp; CCFI均值趋势", html)
            self.assertIn("A股估值带（601919.SH）", html)
            self.assertNotIn("CCFI周均值年内曲线", html)
        finally:
            os.unlink(output_path)

    def test_external_sources_are_reproducible(self):
        """外部来源必须是可复核 URL、快照或本地拉取命令。"""
        rows = vm.load_rows(self.reviewed_csv)
        external = [r for r in rows if r["source_type"] == "external"]
        self.assertTrue(external, "应至少有外部来源数据")
        for r in external:
            self.assertTrue(
                vm.is_valid_source_url(r.get("source_url", "")),
                f"[{r['metric_key']}] {r['year']} source_url 不可复核: {r.get('source_url')}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
