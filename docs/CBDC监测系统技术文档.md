# CBDC 央行资讯监测系统技术文档（工业级重构版）

本文档汇总并系统化梳理项目内所有抓取脚本的架构设计、标准数据模型、增量写入策略、运行合并流程、依赖环境与常见问题排查，并对每个中央银行/资讯源的采集技术方法进行逐项说明。

**最新更新**：2026-01-07
- **架构升级**：采用工业级模块化结构（`src/` 目录），分离工具库与业务逻辑。
- **采集策略**：统一首次回看时间为“运行当日 + 前一日”（共2天），确保时效性。
- **输出优化**：控制台输出精简（模块/状态/时间/标题/链接），CSV 输出统一全字段（空值填充）。

---

## 索引总览

- **项目入口**：[`src/main.py`](file:///d:/code/cbdc20260105/src/main.py)
- **通用工具**：[`src/utils.py`](file:///d:/code/cbdc20260105/src/utils.py)
- **数据目录**：`data/`（所有 CSV 产出）
- **抓取模块**（`src/scrapers/`）：
  - RSS 聚合：[`rss.py`](file:///d:/code/cbdc20260105/src/scrapers/rss.py)
  - 未央国际：[`weiyang.py`](file:///d:/code/cbdc20260105/src/scrapers/weiyang.py)
  - IMF 新闻：[`imf.py`](file:///d:/code/cbdc20260105/src/scrapers/imf.py)
  - 欧央行（ECB）：[`ecb.py`](file:///d:/code/cbdc20260105/src/scrapers/ecb.py)
  - 土耳其央行（TCMB）：[`tcmb.py`](file:///d:/code/cbdc20260105/src/scrapers/tcmb.py)
  - 俄罗斯央行（CBR）：[`cbr.py`](file:///d:/code/cbdc20260105/src/scrapers/cbr.py)
  - 日本央行（BOJ）：[`boj.py`](file:///d:/code/cbdc20260105/src/scrapers/boj.py)
  - 新加坡金管局（MAS）：[`mas.py`](file:///d:/code/cbdc20260105/src/scrapers/mas.py)
  - 印度尼西亚央行（BI）：[`bi.py`](file:///d:/code/cbdc20260105/src/scrapers/bi.py)
  - 沙特央行（SAMA）：[`sama.py`](file:///d:/code/cbdc20260105/src/scrapers/sama.py)
  - 阿根廷央行（BCRA）：[`bcra.py`](file:///d:/code/cbdc20260105/src/scrapers/bcra.py)
  - 巴哈马央行：[`bahamas.py`](file:///d:/code/cbdc20260105/src/scrapers/bahamas.py)
  - 法国央行（BdF）：[`bdf.py`](file:///d:/code/cbdc20260105/src/scrapers/bdf.py)
  - 匈牙利央行（MNB）：[`mnb.py`](file:///d:/code/cbdc20260105/src/scrapers/mnb.py)

---

## 架构概览

- **模块化设计**：
  - `src/scrapers/`：独立业务逻辑，每个文件对应一个采集源，实现 `main()` 入口。
  - `src/utils.py`：复用核心逻辑（日期计算、CSV读写、日志标准化、字段清洗）。
  - `src/main.py`：统一调度器，支持子进程隔离运行、参数控制与结果合并。

- **标准数据模型**：
  - 所有模块输出统一字段集合：`uid`, `source`, `entity`, `category`, `published_at`, `title`, `url`, `abstract`, `content`, `content_type`, `crawl_time`。
  - 空字段统一填充空字符串，确保 CSV 结构对齐。

- **增量策略**：
  - 采集时加载 `standard_all.csv` 历史 UID/URL 进行去重。
  - 每次运行生成 `standard_new.csv`（仅含本轮新增）。
  - 管线结束时合并所有 `new` 文件至全局 `GLOBAL_standard_new.csv` 和 `GLOBAL_standard_all.csv`。

---

## 运行与参数

### 启动方式
在项目根目录下运行：

```bash
# 全量运行
python src/main.py

# 指定运行特定模块
python src/main.py --only rss,imf

# 跳过特定模块
python src/main.py --skip ecb

# 仅执行合并步骤
python src/main.py --merge-only
```

### 控制台输出规范
输出经过优化，仅保留关键信息：
```text
[rss] [NEW] [2026-01-07 10:00:00] 标题示例... (https://...)
...
[rss] [SUMMARY] Total Collected: 20 | New Items: 5
```

---

## 采集策略说明

### 统一回看时间
所有脚本默认回看时间为 **运行当日 + 前一日**（共 2 天）。
- 实现：`src.utils.get_lookback_date_range()`
- 逻辑：若采集到的文章日期早于昨日 00:00:00，则停止采集（对于有序列表）或跳过（对于无序列表）。

### 单脚本技术细节

#### 1. RSS 聚合
- **源**：多国央行 RSS Feed。
- **逻辑**：解析 XML，提取 link 与 published。
- **过滤**：严格按日期过滤。

#### 2. 未央国际（WeiyangX）
- **列表**：Playwright 异步加载 `/category/international`。
- **翻页**：点击“加载更多”。
- **正文**：去除干扰元素，保留核心文本。

#### 3. IMF 新闻
- **技术**：Shadow DOM 穿透（`atomic-result`）。
- **翻页**：模拟点击 Shadow Root 内的 Next 按钮。

#### 4. 欧央行（ECB）
- **技术**：`undetected_chromedriver` 绕过反爬。
- **策略**：滚动加载列表。
- **特例**：支持回填历史空正文（Upsert 模式，视配置开启）。

#### 5. 土耳其央行（TCMB）
- **列表**：`div.block-collection-box`。
- **翻页**：`Load More` 按钮。

#### 6. 俄罗斯央行（CBR）
- **列表**：动态加载 `div.news`。
- **翻页**：`Load more` 按钮。

#### 7. 日本央行（BOJ）
- **解析**：纯文本行分析日期与标题（非标准 HTML 结构）。
- **内容**：兼容 PDF 直接标记。

#### 8. 新加坡金管局（MAS）
- **列表**：`article.mas-search-card`。
- **翻页**：页码按钮点击。

#### 9. 印度尼西亚央行（BI）
- **列表**：ASP.NET 分页控件（`input.next`）。

#### 10. 沙特央行（SAMA）
- **列表**：SharePoint 列表结构。
- **翻页**：`pageNextButton`。

#### 11. 阿根廷央行（BCRA）
- **列表**：单页表格结构。
- **解析**：正则提取日期。

#### 12. 巴哈马央行
- **列表**：月/年 分离的 `span` 标签组合日期。

#### 13. 法国央行（BdF）
- **列表**：Drupal 视图结构。
- **日期**：处理序数词（st/nd/th）。

#### 14. 匈牙利央行（MNB）
- **入口**：按年份动态构造 URL。

---

## 维护与扩展

1. **新增源**：
   - 在 `src/scrapers/` 下新建 `.py` 文件。
   - 导入 `src.utils` 标准工具。
   - 实现 `main()` 函数，遵循 `log_item` 与 `write_incremental_csv` 规范。
   - 在 `src/main.py` 的 `JOBS` 列表中注册。

2. **环境依赖**：
   - Python 3.8+
   - Playwright (`pip install playwright && playwright install`)
   - Selenium / undetected-chromedriver
   - BeautifulSoup4, feedparser, requests, python-dateutil
