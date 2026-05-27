# 中远海控 Value Line 技术落地方案

## 1. 背景与目标

本方案目标是在本地生成一份中远海控 Value Line 风格的单页研究报告，将 2017-2025 年年报中的关键事实数据压缩到一个可离线打开的 HTML 页面中。报告重点不是给出投资建议或估值目标价，而是把长期经营数据、周期特征、业务拆分、分红和 CCFI 运价指标放到同一张可追溯的数据视图里。

方案参考雪球文章中的工作流：先把年报变成可检索语料，再从语料中抽取结构化指标，最后渲染成一页 HTML。AI 的定位是研究助理，负责辅助检索、抽取候选值、发现缺口和生成说明文案；所有数字必须来自本地年报或明确标记的外部公开来源，不能让 AI 凭空补数。

V1 覆盖范围：

- 年份：2017-2025。
- 公司：中远海控，A 股代码 `601919`。
- 数据源：本地年报 PDF 为主，CCFI 缺口用交通运输部或上海航运交易所公开数据补齐。
- 输出：`reports/cosco_value_line.html`。
- 不包含：实时股价、市值、PE/PB、目标价、买卖建议。

## 2. 目录结构

建议最终目录结构如下：

```text
cosco/
  annual/
    中远海控2017年报.pdf
    中远海控2018年报.pdf
    ...
    中远海控2025年报.pdf
  data/
    cosco_annuals.sqlite
    value_line_metrics.csv
    value_line_metrics_reviewed.csv
    external_ccfi.csv
  scripts/
    build_corpus.py
    extract_metrics.py
    validate_metrics.py
    build_value_line.py
  reports/
    cosco_value_line.html
  doc/
    cosco_value_line_technical_plan.md
```

各目录职责：

- `annual/`：只放原始年报 PDF，不放中间产物。
- `data/`：保存语料库、结构化指标、人工校验后的指标和外部补充数据。
- `scripts/`：保存可重复运行的数据处理和报告生成脚本。
- `reports/`：保存最终 HTML 报告。
- `doc/`：保存技术方案、指标口径说明、后续复盘记录。

## 3. 数据管线设计

### 3.1 年报 PDF 抽取

实现 `scripts/build_corpus.py`，读取 `annual/` 下所有年报 PDF，生成本地 SQLite 语料库。

输入约定：

- 文件名包含年份，例如 `中远海控2024年报.pdf`。
- 年份范围默认 `2017-2025`。
- 缺少某年年报时，脚本应提示缺失文件，但允许通过参数生成部分年份语料库。

抽取逻辑：

- 使用 Python PDF 文本库逐页抽取文本。
- 每页保留 `year`、`source_file`、`page`。
- 将页面文本按自然段、换行密度或固定长度切成 chunk。
- 每个 chunk 生成稳定 `chunk_id`，便于后续溯源。
- 对空页、目录页、页眉页脚不做强删除，先保留原始信息，避免误删证据。

SQLite 建议表结构：

```sql
CREATE TABLE annual_chunks (
  chunk_id TEXT PRIMARY KEY,
  year INTEGER NOT NULL,
  source_file TEXT NOT NULL,
  page INTEGER NOT NULL,
  text TEXT NOT NULL
);

CREATE VIRTUAL TABLE annual_chunks_fts USING fts5(
  text,
  content='annual_chunks',
  content_rowid='rowid'
);
```

检索能力：

- 支持按关键词检索，例如“营业收入”“归属于上市公司股东的净利润”“经营活动产生的现金流量净额”“分红”“CCFI”。
- 返回结果必须包含年份、文件名、页码、原文片段。
- 后续指标抽取只允许基于检索结果或明确外部数据源。

### 3.2 指标抽取

实现 `scripts/extract_metrics.py`，从 SQLite 语料库中生成候选指标表。V1 可以先采用规则检索 + 人工复核的方式，不必追求全自动。

指标范围：

| metric_key | 指标名称 | 默认单位 | 说明 |
| --- | --- | --- | --- |
| revenue | 营业收入 | 亿元 | 合并口径营业收入 |
| net_profit_parent | 归母净利润 | 亿元 | 归属于上市公司股东的净利润 |
| operating_cash_flow | 经营现金流 | 亿元 | 经营活动产生的现金流量净额 |
| total_assets | 总资产 | 亿元 | 期末合并资产总计 |
| equity_parent | 归母净资产 | 亿元 | 归属于上市公司股东的净资产 |
| eps | EPS | 元/股 | 基本每股收益 |
| roe | ROE | % | 加权平均净资产收益率优先 |
| container_shipping_revenue | 集装箱航运收入 | 亿元 | 分业务或主营业务口径 |
| terminal_revenue | 码头业务收入 | 亿元 | 分业务或主营业务口径 |
| dividend_total | 分红总额 | 亿元 | 当年利润分配对应现金分红 |
| dividend_per_share | 每股股利 | 元/股 | 税前现金股利 |
| ccfi_average | CCFI 年均值 | 点 | 年报披露或外部计算 |

候选指标表字段：

| 字段 | 含义 |
| --- | --- |
| metric_key | 指标唯一键 |
| metric_name | 中文指标名 |
| year | 年份 |
| value | 数值 |
| unit | 单位 |
| source_type | `annual_report`、`external_public`、`computed_external`、`manual_review`、`missing` |
| source_file | 年报文件名或外部数据文件名 |
| page | 页码；外部来源可为空 |
| evidence_text | 支撑该数字的原文片段 |
| confidence | `high`、`medium`、`low` |
| status | `candidate`、`reviewed`、`missing`、`conflict` |
| note | 口径说明、冲突说明或人工备注 |

抽取原则：

- 优先抽取年报“主要会计数据和财务指标”表。
- 分业务收入优先使用年报披露的分部信息或主营业务分析。
- 分红优先使用利润分配预案或年度权益分派实施相关披露。
- 同一指标同一年出现多个候选值时，保留候选记录并标记 `conflict`，等待人工复核。
- AI 可以辅助判断候选片段是否匹配指标，但不得直接生成没有证据的数字。

### 3.3 CCFI 补源

CCFI 是中远海控周期判断的重要指标，需要单独处理。

口径：

- 指标名称：中国出口集装箱运价综合指数，CCFI。
- 年度值：全年简单平均值。
- 2017-2021 优先使用年报披露值。
- 年报未披露完整均值的年份，使用交通运输部或上海航运交易所公开数据补齐。

外部数据文件 `data/external_ccfi.csv` 建议字段：

| 字段 | 含义 |
| --- | --- |
| date | 指数日期 |
| ccfi | CCFI 综合指数 |
| source_name | 来源名称 |
| source_url | 来源链接 |
| source_note | 备注 |

年度均值计算：

- 按自然年筛选 `date`。
- 对该年所有可用 CCFI 综合指数做简单平均。
- 结果写入 `ccfi_average`，`source_type` 标记为 `computed_external`。
- 报告中明确标注该值为外部公开数据计算值，不与年报披露值混淆。

可接受来源：

- 交通运输部出口集装箱运价指数页面。
- 上海航运交易所 CCFI 页面。
- 若使用第三方整理数据，只能作为辅助定位，最终仍需追溯到官方来源。

### 3.4 数据校验

实现 `scripts/validate_metrics.py`，在生成报告前做硬性校验。

校验规则：

- 每个 `metric_key + year` 最多只能有一条 `reviewed` 记录。
- 所有 `reviewed` 数值必须有 `source_type`、`unit`、`evidence_text` 或外部来源说明。
- 年报来源指标必须有 `source_file` 和 `page`。
- 金额单位统一为亿元；从元、千元、万元抽取的数值必须统一换算。
- 百分比统一为 `%`，例如 ROE 存 `12.34` 而不是 `0.1234`。
- 缺失值必须显式保留一条 `status=missing` 记录，并说明原因。
- 存在 `conflict`、`candidate` 或低置信度核心指标时，默认阻止生成最终报告。

输出：

- 校验通过：生成 `data/value_line_metrics_reviewed.csv`。
- 校验失败：输出错误列表，包含指标、年份、问题类型和建议处理方式。

## 4. 报告生成设计

实现 `scripts/build_value_line.py`，读取校验后的指标表和 CCFI 外部数据，生成 `reports/cosco_value_line.html`。

命令入口：

```bash
python scripts/build_value_line.py \
  --metrics data/value_line_metrics_reviewed.csv \
  --output reports/cosco_value_line.html \
  --start-year 2017 \
  --end-year 2025
```

HTML 要求：

- 单文件输出，离线可打开。
- CSS 内联。
- 图表优先使用内联 SVG，避免依赖外部 CDN。
- 页面适配桌面宽屏和打印/PDF 导出。
- 所有关键数字附近必须能看到来源提示，至少包含年份、来源类型、文件和页码。

页面模块：

1. 头部摘要
   - 公司名称、股票代码、覆盖年份、报告生成日期。
   - 三到五条快速观察，例如周期高点、利润回落、现金流、分红、CCFI 关系。

2. 核心指标九年表
   - 年份横向排列。
   - 行包括收入、归母净利润、经营现金流、总资产、归母净资产、EPS、ROE。
   - 缺失值用 `--`，并显示缺口说明。

3. 趋势图
   - 收入、归母净利润、经营现金流折线图。
   - CCFI 与归母净利润对照图，采用双轴或标准化指数。
   - 分红总额和每股股利图。

4. 业务拆分
   - 集装箱航运收入与码头业务收入趋势。
   - 如年报口径变化，需要在图下注明。

5. 分红信息
   - 每年现金分红总额、每股股利。
   - 不做股息率，除非后续引入股价数据。

6. 快速阅读结论
   - 使用已校验数据生成简短文字。
   - 文案必须引用页面已有指标，不引入新数字。

7. 数据来源索引
   - 列出所有年报文件。
   - 列出外部 CCFI 来源。
   - 列出缺失项和人工修订项。

## 5. AI 使用边界

AI 可以做：

- 根据关键词从 SQLite 检索候选段落。
- 从候选段落中提取候选数字。
- 对候选数字做口径解释。
- 发现指标缺口、冲突和异常。
- 基于已审核数据生成报告文案。

AI 不可以做：

- 在没有证据片段时补数字。
- 把同比增速反推为绝对值后伪装成年报披露值。
- 混用不同单位或不同口径而不标记。
- 输出买卖建议、目标价或确定性预测。

所有 AI 生成的候选值必须经过 `reviewed` 状态确认后才能进入最终报告。

## 6. 实施 Milestones

### Milestone 1：年报语料库

目标：把 2017-2025 年报 PDF 转成可检索 SQLite。

交付：

- `scripts/build_corpus.py`
- `data/cosco_annuals.sqlite`
- 基础检索示例和运行说明

验收：

- 九份年报均可识别年份、页数和文本。
- 检索“营业收入”“归母净利润”“CCFI”能返回相关页码。

### Milestone 2：候选指标抽取

目标：生成核心指标候选表。

交付：

- `scripts/extract_metrics.py`
- `data/value_line_metrics.csv`

验收：

- 核心财务指标覆盖 2017-2025。
- 每条候选值都有来源文件、页码和证据片段。
- 冲突和缺失被显式标记。

### Milestone 3：人工复核与校验

目标：形成可用于报告生成的审核版指标表。

交付：

- `scripts/validate_metrics.py`
- `data/value_line_metrics_reviewed.csv`

验收：

- 没有未处理的 `candidate` 或 `conflict` 核心指标。
- 单位统一。
- 缺失项有明确说明。

### Milestone 4：HTML Value Line 报告

目标：生成离线单页报告。

交付：

- `scripts/build_value_line.py`
- `reports/cosco_value_line.html`

验收：

- 页面离线打开正常。
- 核心表格、趋势图、业务拆分、分红和来源索引完整。
- 打印预览主要内容不截断。

### Milestone 5：润色与可复现

目标：提升报告可读性和重跑稳定性。

交付：

- 运行说明。
- 指标口径说明。
- 异常值和缺口说明。

验收：

- 从空 `data/` 到最终 HTML 的命令链可重复执行。
- 修改某个指标后重跑报告能稳定反映变化。
- 页面能清楚区分年报来源、外部来源和缺失数据。

## 7. 验收清单

实现完成后，按以下清单验收：

- `annual/` 下 2017-2025 年报文件齐全。
- `data/cosco_annuals.sqlite` 可按关键词检索年报原文。
- `data/value_line_metrics_reviewed.csv` 覆盖全部核心指标。
- 每个核心数字可追溯到年报页码或外部公开数据来源。
- CCFI 年均值口径清楚，外部计算值有来源链接或来源文件。
- `reports/cosco_value_line.html` 可离线打开。
- 报告没有实时行情依赖。
- 报告没有目标价、买卖建议或无法溯源的新数字。

## 8. 风险与处理

| 风险 | 影响 | 处理 |
| --- | --- | --- |
| PDF 表格抽取错位 | 数字错误 | 抽取结果只作为候选，必须保留证据片段并人工复核 |
| 年报指标口径变化 | 跨年不可比 | 在 `note` 字段和报告图下注明 |
| CCFI 年报缺失 | 周期图不完整 | 使用官方外部数据计算，并标记 `computed_external` |
| 单位混乱 | 趋势图失真 | 校验阶段统一亿元、元/股、百分比 |
| AI 幻觉 | 错误结论 | AI 只能基于 reviewed 数据生成文本 |

## 9. 后续扩展

V1 稳定后可以考虑：

- 加入 SCFI、运力、箱量等行业指标。
- 增加港股口径或 H 股相关行情。
- 增加估值页，但需要单独设计股价、市值和复权口径。
- 将 HTML 报告导出为 PDF。
- 做成多公司模板，让同一套管线支持其他周期股。
