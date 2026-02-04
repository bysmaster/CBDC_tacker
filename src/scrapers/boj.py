# -*- coding: utf-8 -*-
import csv
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

from ..utils import (
    STANDARD_FIELDS, make_uid, sanitize_text, utc_now_str, write_incremental_csv,
    log_item, log_summary, get_lookback_date_range, GLOBAL_ALL_CSV, GLOBAL_NEW_CSV
)

# ================= 配置区 =================
LIST_BASE_URL = "https://www.boj.or.jp/en/whatsnew/index.htm/"

SOURCE = "boj"
ENTITY = "日本"
CATEGORY = "whatsnew"

# ==========================================

def parse_boj_date(date_text):
    date_text = (date_text or "").replace("&nbsp;", " ").strip()
    match = re.match(r"([A-Za-z]+\.\s*\d{1,2},\s*\d{4})", date_text)
    if not match:
        return None, None
    raw = match.group(1)
    try:
        dt = datetime.strptime(raw, "%b. %d, %Y")
        return dt, dt.strftime("%Y-%m-%d")
    except Exception:
        return None, None

def clean_text_to_single_line(text):
    if not text:
        return ""
    return " ".join(str(text).replace("\n", " ").replace("\r", " ").replace("\t", " ").split())

def get_article_content(browser, url):
    if not url or not url.startswith("http"):
        return ""
    context = browser.new_context()
    page = context.new_page()
    try:
        page.goto(url, timeout=90000, wait_until="networkidle")
        page.wait_for_timeout(5000)
        if url.lower().endswith(".pdf"):
            return clean_text_to_single_line(f"[PDF] {url}")
        full_text_parts = []
        content_container = page.locator("div.outline.mod_outer, div#content, div.main, article, body > div").first
        if content_container.count() > 0:
            elements = content_container.locator("h1, h2, h3, p, li, ul.link-list01 a").all()
            for elem in elements:
                t = elem.inner_text().strip()
                if t and len(t) > 5:
                    full_text_parts.append(t)
        else:
            elements = page.locator("p, h2, h3").all()
            for elem in elements:
                t = elem.inner_text().strip()
                if t and len(t) > 10:
                    full_text_parts.append(t)
        full_text = "\n\n".join(full_text_parts) if full_text_parts else page.inner_text("body")
        return clean_text_to_single_line(full_text)
    except Exception as e:
        return clean_text_to_single_line(f"[Error] {e}")
    finally:
        page.close()
        context.close()

def extract_list_page(page):
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(8000)
    full_text = page.inner_text("body")
    lines = [line.strip() for line in full_text.split("\n") if line.strip()]
    results = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^(\+?\s*[A-Za-z]+\.\s*\d{1,2},\s*\d{4})", line):
            dt, date_str = parse_boj_date(line)
            if not dt:
                i += 1
                continue
            title = ""
            category = ""
            link = ""
            j = i + 1
            while j < len(lines) and not re.match(r"^(\+?\s*[A-Za-z]+\.\s*\d{1,2},\s*\d{4})", lines[j]):
                candidate = lines[j]
                if "[PDF" in candidate or candidate.endswith("]"):
                    title = candidate
                elif len(candidate) > 10 and not category:
                    category = candidate
                j += 1
            if not title:
                title = lines[i + 1] if i + 1 < len(lines) else ""
            try:
                link_elem = page.locator(f'a:has-text("{title[:50]}")').first
                if link_elem.count() > 0:
                    link = link_elem.get_attribute("href")
                    if link and not link.startswith("http"):
                        link = "https://www.boj.or.jp" + link
            except Exception:
                link = ""
            if title and date_str:
                results.append({
                    "date_obj": dt,
                    "date_str": date_str,
                    "category": category,
                    "link": link,
                    "title": title,
                })
            i = j - 1
        i += 1
    results.sort(key=lambda x: x["date_obj"], reverse=True)
    return results

def main():
    start_dt, end_dt = get_lookback_date_range()
    
    std_rows = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(LIST_BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(10000)

        news_list = extract_list_page(page)
        if news_list:
            for item in news_list:
                link = (item.get("link") or "").strip()
                if not link:
                    continue

                dt = item["date_obj"]
                # STRICT DATE CHECK
                if dt and dt < start_dt:
                    break

                title = item.get("title", "")
                cat = item.get("category") or CATEGORY
                
                full_content = get_article_content(browser, link)
                
                log_item(SOURCE, "NEW", item["date_str"], title, link)

                std_rows.append({
                    "uid": make_uid(SOURCE, link),
                    "source": SOURCE,
                    "entity": ENTITY,
                    "category": sanitize_text(cat, one_line=True) or CATEGORY,
                    "published_at": item["date_str"],
                    "title": sanitize_text(title, one_line=True),
                    "url": sanitize_text(link, one_line=True),
                    "abstract": sanitize_text((full_content[:300] if full_content else ""), one_line=True),
                    "content": sanitize_text(full_content, one_line=True),
                    "content_type": "pdf" if link.lower().endswith(".pdf") else "html",
                    "crawl_time": utc_now_str(),
                })
                time.sleep(2)

        browser.close()

    new_count = write_incremental_csv(all_csv=GLOBAL_ALL_CSV, new_csv=GLOBAL_NEW_CSV, rows=std_rows, append_new=True)
    log_summary(SOURCE, len(std_rows), new_count)

if __name__ == "__main__":
    main()
