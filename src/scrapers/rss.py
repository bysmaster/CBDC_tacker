# -*- coding: utf-8 -*-
"""
Industrial-grade RSS Polling Engine
"""

import csv
import hashlib
import io
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
import PyPDF2

from ..utils import (
    STANDARD_FIELDS, sanitize_text, utc_now_str, write_incremental_csv, 
    make_uid, log_item, log_summary, get_lookback_date_range,
    GLOBAL_ALL_CSV, GLOBAL_NEW_CSV
)

# ========================
# RSS SOURCES
# ========================
RSS_SOURCES = [
    {"entity": "美国", "entity_type": "工作论文", "rss_type": "工作论文", "url": "https://www.federalreserve.gov/feeds/working_papers.xml"},
    {"entity": "美国", "entity_type": "董事会议", "rss_type": "董事会议", "url": "https://www.federalreserve.gov/feeds/boardmeetings.xml"},
    {"entity": "美国", "entity_type": "演讲", "rss_type": "演讲", "url": "https://www.federalreserve.gov/feeds/speeches.xml"},
    {"entity": "美国", "entity_type": "新闻稿", "rss_type": "新闻稿", "url": "https://www.federalreserve.gov/feeds/press_all.xml"},
    {"entity": "加拿大", "entity_type": "数字货币和金融科技", "rss_type": "数字货币和金融科技", "url": "https://www.bankofcanada.ca/topic/digital-currencies/feed/"},
    {"entity": "加拿大", "entity_type": "加密货币", "rss_type": "加密货币", "url": "https://www.bankofcanada.ca/topic/cryptocurrencies/feed/"},
    {"entity": "加拿大", "entity_type": "央行研究", "rss_type": "央行研究", "url": "https://www.bankofcanada.ca/topic/central-bank-research/feed/"},
    {"entity": "加拿大", "entity_type": "工作人员分析笔记", "rss_type": "工作人员分析笔记", "url": "https://www.bankofcanada.ca/content_type/staff-analytical-notes/feed/"},
    {"entity": "加拿大", "entity_type": "工作人员讨论文件", "rss_type": "工作人员讨论文件", "url": "https://www.bankofcanada.ca/content_type/discussion-papers/feed/"},
    {"entity": "加拿大", "entity_type": "工作人员工作文件", "rss_type": "工作人员工作文件", "url": "https://www.bankofcanada.ca/content_type/working-papers/feed/"},
    {"entity": "加拿大", "entity_type": "技术报告", "rss_type": "技术报告", "url": "https://www.bankofcanada.ca/content_type/technical-reports/feed/"},
    {"entity": "加拿大", "entity_type": "其他", "rss_type": "其他", "url": "https://www.bankofcanada.ca/content_type/other/feed/"},
    {"entity": "加拿大", "entity_type": "新闻稿", "rss_type": "新闻稿", "url": "https://www.bankofcanada.ca/content_type/press-releases/feed/"},
    {"entity": "加拿大", "entity_type": "公告", "rss_type": "公告", "url": "https://www.bankofcanada.ca/content_type/announcements/feed/"},
    {"entity": "加拿大", "entity_type": "新闻", "rss_type": "新闻", "url": "https://www.bankofcanada.ca/utility/news/feed/"},
    {"entity": "加拿大", "entity_type": "年报", "rss_type": "年报", "url": "https://www.bankofcanada.ca/content_type/annual-report/feed/"},
    {"entity": "加拿大", "entity_type": "金融系统中心", "rss_type": "金融系统中心", "url": "https://www.bankofcanada.ca/content_type/financial-system-hub/feed/"},
    {"entity": "欧元区", "entity_type": "新闻稿演讲稿", "rss_type": "新闻稿演讲稿", "url": "https://www.ecb.europa.eu/rss/press.html"},
    {"entity": "欧元区", "entity_type": "博客文章", "rss_type": "博客文章", "url": "https://www.ecb.europa.eu/rss/blog.html"},
    {"entity": "欧元区", "entity_type": "出版物", "rss_type": "出版物", "url": "https://www.ecb.europa.eu/rss/pub.html"},
    {"entity": "欧元区", "entity_type": "工作文件，PDF格式", "rss_type": "工作文件，pdf格式", "url": "https://www.ecb.europa.eu/rss/wppub.html"},
    {"entity": "欧元区", "entity_type": "研究简报", "rss_type": "研究简报", "url": "https://www.ecb.europa.eu/rss/rbu.html"},
    {"entity": "瑞典", "entity_type": "新闻稿", "rss_type": "新闻稿", "url": "https://www.riksbank.se/en-gb/rss/press-releases/"},
    {"entity": "瑞典", "entity_type": "通知", "rss_type": "通知", "url": "https://www.riksbank.se/en-gb/rss/notices/"},
    {"entity": "瑞典", "entity_type": "演讲", "rss_type": "演讲", "url": "https://www.riksbank.se/en-gb/rss/speeches/"},
    {"entity": "丹麦", "entity_type": "分析", "rss_type": "分析", "url": "https://www.nationalbanken.dk/api/rssfeed?topic=Analysis&lang=zh-CN"},
    {"entity": "丹麦", "entity_type": "报告", "rss_type": "报告", "url": "https://www.nationalbanken.dk/api/rssfeed?topic=Report&lang=zh-CN"},
    {"entity": "丹麦", "entity_type": "经济备忘录", "rss_type": "经济备忘录", "url": "https://www.nationalbanken.dk/api/rssfeed?topic=Economic+Memo&lang=zh-CN"},
    {"entity": "丹麦", "entity_type": "工作文件", "rss_type": "工作文件", "url": "https://www.nationalbanken.dk/api/rssfeed?topic=Working+Paper&lang=zh-CN"},
    {"entity": "丹麦", "entity_type": "消息", "rss_type": "消息", "url": "https://www.nationalbanken.dk/api/rssfeed?topic=News&lang=zh-CN"},
    {"entity": "丹麦", "entity_type": "其他出版物", "rss_type": "其他出版物", "url": "https://www.nationalbanken.dk/api/rssfeed?topic=Other+publications&lang=zh-CN"},
    {"entity": "英国", "entity_type": "事件", "rss_type": "事件", "url": "https://www.bankofengland.co.uk/rss/events"},
    {"entity": "英国", "entity_type": "消息", "rss_type": "消息", "url": "https://www.bankofengland.co.uk/rss/news"},
    {"entity": "英国", "entity_type": "出版物", "rss_type": "出版物", "url": "https://www.bankofengland.co.uk/rss/publications"},
    {"entity": "英国", "entity_type": "演讲", "rss_type": "演讲", "url": "https://www.bankofengland.co.uk/rss/speeches"},
    {"entity": "瑞士", "entity_type": "新闻稿", "rss_type": "新闻稿", "url": "https://www.snb.ch/public/en/rss/pressrel"},
    {"entity": "瑞士", "entity_type": "演讲", "rss_type": "演讲", "url": "https://www.snb.ch/public/en/rss/speeches"},
    {"entity": "瑞士", "entity_type": "季度公告", "rss_type": "季度公告", "url": "https://www.snb.ch/public/en/rss/quartbul"},
    {"entity": "瑞士", "entity_type": "年报", "rss_type": "年报", "url": "https://www.snb.ch/public/en/rss/annrep"},
    {"entity": "瑞士", "entity_type": "研究报告", "rss_type": "研究报告", "url": "https://www.snb.ch/public/en/rss/researchreports"},
    {"entity": "瑞士", "entity_type": "工作论文", "rss_type": "工作论文", "url": "https://www.snb.ch/public/en/rss/papers"},
    {"entity": "土耳其", "entity_type": "出版物", "rss_type": "出版物", "url": "https://www.tcmb.gov.tr/wps/wcm/connect/EN/TCMB+EN/Bottom+Menu/Other/RSS/Publications"},
    {"entity": "土耳其", "entity_type": "演讲", "rss_type": "演讲", "url": "https://www.tcmb.gov.tr/wps/wcm/connect/EN/TCMB+EN/Bottom+Menu/Other/RSS/Remarks+by+Governor"},
    {"entity": "土耳其", "entity_type": "新闻稿", "rss_type": "新闻稿", "url": "https://www.tcmb.gov.tr/wps/wcm/connect/EN/TCMB+EN/Bottom+Menu/Other/RSS/Press+Releases"},
    {"entity": "日本", "entity_type": "all", "rss_type": "all", "url": "https://www.boj.or.jp/en/rss/whatsnew.xml"},
    {"entity": "韩国", "entity_type": "支付和结算系统年度报告", "rss_type": "支付和结算系统年度报告", "url": "https://www.bok.or.kr/eng/bbs/E0000866/news.rss?menuNo=400047"},
    {"entity": "韩国", "entity_type": "统计数据和出版物", "rss_type": "统计数据和出版物", "url": "https://www.bok.or.kr/eng/bbs/E0000654/news.rss?menuNo=400048"},
    {"entity": "韩国", "entity_type": "季度简报", "rss_type": "季度简报", "url": "https://www.bok.or.kr/eng/bbs/E0000829/news.rss?menuNo=400216"},
    {"entity": "韩国", "entity_type": "年度报告", "rss_type": "年度报告", "url": "https://www.bok.or.kr/eng/bbs/E0000740/news.rss?menuNo=400221"},
    {"entity": "韩国", "entity_type": "新闻稿", "rss_type": "新闻稿", "url": "https://www.bok.or.kr/eng/bbs/E0000634/news.rss?menuNo=400069"},
    {"entity": "韩国", "entity_type": "演讲", "rss_type": "演讲", "url": "https://www.bok.or.kr/eng/bbs/E0002382/news.rss?menuNo=400074"},
    {"entity": "印度", "entity_type": "新闻稿", "rss_type": "新闻稿", "url": "https://rbi.org.in/pressreleases_rss.xml"},
    {"entity": "印度", "entity_type": "通知", "rss_type": "通知", "url": "https://rbi.org.in/notifications_rss.xml"},
    {"entity": "印度", "entity_type": "演讲", "rss_type": "演讲", "url": "https://rbi.org.in/speeches_rss.xml"},
    {"entity": "印度", "entity_type": "出版物", "rss_type": "出版物", "url": "https://rbi.org.in/Publication_rss.xml"},
    {"entity": "阿联酋", "entity_type": "出版物", "rss_type": "出版物", "url": "https://www.centralbank.ae/en/rss-feed/publications-rss-feed/"},
    {"entity": "阿联酋", "entity_type": "事件", "rss_type": "事件", "url": "https://www.centralbank.ae/en/rss-feed/events-rss-feed/"},
    {"entity": "阿联酋", "entity_type": "新闻", "rss_type": "新闻", "url": "https://www.centralbank.ae/en/rss-feed/news-and-insights/"},
    {"entity": "澳大利亚", "entity_type": "媒体发布", "rss_type": "媒体发布", "url": "https://www.rba.gov.au/rss/rss-cb-media-releases.xml"},
    {"entity": "澳大利亚", "entity_type": "演讲", "rss_type": "演讲", "url": "https://www.rba.gov.au/rss/rss-cb-speeches.xml"},
    {"entity": "澳大利亚", "entity_type": "演讲网络直播", "rss_type": "演讲网络直播", "url": "https://www.rba.gov.au/rss/rss-cb-speeches-webcast.xml"},
    {"entity": "澳大利亚", "entity_type": "公告", "rss_type": "公告", "url": "https://www.rba.gov.au/rss/rss-cb-bulletin.xml"},
    {"entity": "南非", "entity_type": "all", "rss_type": "all", "url": "https://www.resbank.co.za/bin/sarb/solr/publications/rss"},
    {"entity": "bis", "entity_type": "all", "rss_type": "all", "url": "https://www.bis.org/doclist/rss_all_categories.rss"},
    
    {"entity": "意大利", "entity_type": "all", "rss_type": "all", "url": "https://www.bancaditalia.it/util/index.rss.html?lingua=en"}
]

# ========================
# PATHS
# ========================
# Using GLOBAL_ALL_CSV and GLOBAL_NEW_CSV from utils

# ========================
# UTILITIES
# ========================
def safe_parse_date(d):
    """
    Parses a date string from an RSS entry using dateutil.parser.
    Returns YYYY-MM-DD HH:MM:SS or empty string.
    """
    if not d:
        return ""
    try:
        dt = dateparser.parse(d)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""

def try_extract_date_from_text(text: str) -> str:
    """
    Attempts to extract a date from arbitrary text using heuristics and regex.
    Returns YYYY-MM-DD string or empty string.
    
    Strategies:
    1. Regex for standard formats (YYYY-MM-DD, DD/MM/YYYY, etc.)
    2. Regex for textual dates (Jan 1, 2026)
    """
    if not text:
        return ""
    
    # 1. YYYY-MM-DD or YYYY/MM/DD
    match = re.search(r"\b(202[2-9])[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12]\d|3[01])\b", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        
    # 2. DD-MM-YYYY or DD/MM/YYYY
    match = re.search(r"\b(0[1-9]|[12]\d|3[01])[-/.](0[1-9]|1[0-2])[-/.](202[2-9])\b", text)
    if match:
        return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
        
    # 3. Textual dates: Month DD, YYYY or DD Month YYYY
    try:
        # dateutil fuzzy parsing is powerful but can be aggressive.
        # We limit the text length or pre-filter to avoid false positives?
        # Instead, let's look for Year 202X explicitly in the text first.
        if re.search(r"\b202[2-9]\b", text):
            dt = dateparser.parse(text, fuzzy=True)
            # Sanity check: Year must be in reasonable range
            if 2020 <= dt.year <= 2030:
                return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
        
    return ""

def check_year_heuristic(text: str) -> str:
    """
    Checks if text contains specific year signals.
    - If 2026 is found: Returns '2026-01-01' (treated as new/current year)
    - If 2025, 2024, etc are found: Returns '2025-01-01' (treated as old)
    - Returns empty string if no year signal found.
    """
    # Exclude URLs from check? Text passed here should ideally be title/summary, not URL.
    # But just in case, we assume text is safe.
    
    if "2026" in text:
        return "2026-01-01"
    
    # Check for older years to explicitly reject
    # We scan for 2020-2025
    match = re.search(r"\b(202[0-5])\b", text)
    if match:
        return f"{match.group(1)}-01-01"
        
    return ""

def normalize_link(link, base):
    if not link:
        return ""
    if link.startswith("http"):
        return link
    if base:
        return base.rstrip("/") + "/" + link.lstrip("/")
    return link

def content_type_from_link(link):
    if not link:
        return "unknown"
    return "pdf" if link.lower().endswith(".pdf") else "html"

def html_to_text(html: str) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(" ", strip=True)
    except Exception:
        return str(html)

def extract_content(link, content_type):
    if not link:
        return ""

    try:
        headers = {"User-Agent": "Mozilla/5.0 (RSSBot/1.0)"}
        r = requests.get(link, headers=headers, timeout=40)
        r.raise_for_status()

        # ---- PDF ----
        if content_type == "pdf":
            reader = PyPDF2.PdfReader(io.BytesIO(r.content))
            pages = []
            for p in reader.pages:
                t = p.extract_text()
                if t:
                    pages.append(t)
            text = "\n\n".join(pages)
            return re.sub(r"\\n\\s*\\n+", "\\n\\n", text.strip())

        # ---- HTML ----
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in ["script","style","header","footer","nav","aside","iframe","noscript","form","button","svg","img","figcaption","table","hr","meta","link","input","select","textarea"]:
            for e in soup.find_all(tag):
                e.decompose()

        for cls in ["disclaimer","footer","copyright","share","social","related","sidebar","advert","breadcrumb","cookies"]:
            for e in soup.find_all(class_=re.compile(cls, re.I)):
                e.decompose()

        main = (
            soup.find("main") or
            soup.find("article") or
            soup.find("div", id=re.compile("content|article|body|text", re.I)) or
            soup.find("div", class_=re.compile("content|article|body|text|speech|press", re.I)) or
            soup.body
        )

        if not main:
            return ""

        blocks = []
        for e in main.find_all(["h1","h2","h3","h4","p","li","blockquote"]):
            t = e.get_text(" ", strip=True)
            if t and len(t) > 5:
                blocks.append(t)

        text = "\n\n".join(blocks)
        text = re.sub(r"\\n\\s*\\n+", "\\n\\n", text)
        text = re.sub(r"\\s{2,}", " ", text)
        return text.strip()

    except Exception as ex:
        return ""

def parse_rss(src, min_date_str):
    feed = feedparser.parse(src["url"])

    base = ""
    if src["entity"] == "土耳其":
        base = "https://www.tcmb.gov.tr"
    elif src["entity"] == "南非":
        base = "https://www.resbank.co.za"

    items = []
    for e in feed.entries:
        # 1. Try standard RSS fields
        raw_date = e.get("published") or e.get("updated") or e.get("created") or ""
        published_at = safe_parse_date(raw_date)
        
        # 2. If no standard date, try extracting from title/summary
        if not published_at:
            # Combine title and summary for search
            search_text = (e.get("title", "") + " " + e.get("summary", ""))
            
            # Try fuzzy date extraction
            extracted_date = try_extract_date_from_text(search_text)
            if extracted_date:
                published_at = extracted_date + " 00:00:00"
            else:
                # Try Year Heuristic (2026 vs others)
                year_date = check_year_heuristic(search_text)
                if year_date:
                    published_at = year_date + " 00:00:00"

        # Date Filter
        if published_at:
            if published_at[:10] < min_date_str:
                continue
        else:
            continue
        
        link = normalize_link(e.get("link", ""), base)
        items.append({
            "entity": src["entity"],
            "entity_type": src["entity_type"],
            "rss_type": src["rss_type"],
            "title": e.get("title", ""),
            "link": link,
            "published": published_at,
            "summary": e.get("summary", ""),
            "content_type": content_type_from_link(link),
            "content": "",
            "crawl_time": utc_now_str()
        })
    return items

def main():
    # 1. Determine Date Range
    start_dt, end_dt = get_lookback_date_range()
    min_date_str = start_dt.strftime("%Y-%m-%d")
    
    std_rows = []
    total_new = 0

    for src in RSS_SOURCES:
        try:
            items = parse_rss(src, min_date_str)
        except Exception as e:
            print(f"[WARN] RSS failed: {src['url']} | {e}")
            continue

        for item in items:
            uid = make_uid("rss", item["link"])
            
            # Extract content
            item["content"] = extract_content(item["link"], item["content_type"])
            
            # Log
            status = "NEW" # We assume new for now, write_incremental_csv handles dedupe
            log_item("RSS", status, item["published"], item["title"], item["link"])

            std_rows.append(
                {
                    "uid": uid,
                    "source": "rss",
                    "entity": sanitize_text(item.get("entity", ""), one_line=True),
                    "category": sanitize_text(item.get("rss_type") or item.get("entity_type") or "", one_line=True),
                    "published_at": sanitize_text(item.get("published", ""), one_line=True),
                    "title": sanitize_text(item.get("title", ""), one_line=True),
                    "url": sanitize_text(item.get("link", ""), one_line=True),
                    "abstract": sanitize_text(html_to_text(item.get("summary", "")), one_line=True),
                    "content": sanitize_text(item.get("content", ""), one_line=True),
                    "content_type": sanitize_text(item.get("content_type", ""), one_line=True),
                    "crawl_time": sanitize_text(item.get("crawl_time", "") or utc_now_str(), one_line=True),
                }
            )

    # Write
    new_count = write_incremental_csv(all_csv=GLOBAL_ALL_CSV, new_csv=GLOBAL_NEW_CSV, rows=std_rows, append_new=True)
    log_summary("RSS", len(std_rows), new_count)

if __name__ == "__main__":
    main()
