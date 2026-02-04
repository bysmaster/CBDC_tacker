# -*- coding: utf-8 -*-
import csv
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
LIST_BASE_URL = "https://www.tcmb.gov.tr/wps/wcm/connect/EN/TCMB+EN/Main+Menu/Announcements/Press+Releases/"
MAX_PAGES = 50

SOURCE = "tcmb"
ENTITY = "土耳其"
CATEGORY = "press_releases"

# ==========================================

def clean_text_to_single_line(text):
    if not text:
        return ""
    return " ".join(str(text).replace("\n", " ").replace("\r", " ").replace("\t", " ").split())

def get_article_content(browser, url):
    if not url or not url.startswith("http"):
        return ""
    context = browser.new_context()
    page = context.new_page()
    full_text = ""
    try:
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        content_selector = page.locator("div.tcmb-content.type-prg").first
        if content_selector.count() > 0:
            paragraphs = content_selector.locator("p, h2, h3").all_inner_texts()
            full_text = " ".join(paragraphs)
        else:
            full_text = " ".join(page.locator("p").all_inner_texts())
    except Exception:
        pass
    finally:
        page.close()
        context.close()
    return clean_text_to_single_line(full_text)

def extract_list_page(page):
    page.wait_for_selector(".block-collection-box", timeout=30000)
    page.wait_for_timeout(1500)
    items = page.locator("div.block-collection-box").all()
    results = []
    for item in items:
        try:
            title_elem = item.locator("a.collection-title").first
            title = title_elem.inner_text().strip() if title_elem.count() > 0 else ""
            link = title_elem.get_attribute("href") if title_elem.count() > 0 else ""
            if link and not link.startswith("http"):
                link = "https://www.tcmb.gov.tr" + link
            date_elem = item.locator("div.collection-tag").first
            date_str = date_elem.inner_text().strip() if date_elem.count() > 0 else ""
            date_obj = None
            try:
                if date_str:
                    for fmt in ["%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y"]:
                        try:
                            date_obj = datetime.strptime(date_str, fmt)
                            break
                        except ValueError:
                            continue
            except Exception:
                date_obj = None
            if title and link and date_obj:
                results.append({
                    "date_obj": date_obj,
                    "date_str": date_obj.strftime("%Y-%m-%d"),
                    "link": link,
                    "title": title,
                })
        except Exception:
            continue
    results.sort(key=lambda x: x["date_obj"], reverse=True)
    return results

def main():
    start_dt, end_dt = get_lookback_date_range()
    
    std_rows = []
    visited_links = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(LIST_BASE_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        page_num = 1
        keep_scraping = True

        while keep_scraping and page_num <= MAX_PAGES:
            news_list = extract_list_page(page)
            if not news_list:
                break

            for item in news_list:
                link = item["link"]
                if link in visited_links:
                    continue

                dt = item["date_obj"]
                # STRICT DATE CHECK
                if dt and dt < start_dt:
                    keep_scraping = False
                    break

                title = item["title"]
                full_content = get_article_content(browser, link)
                
                log_item(SOURCE, "NEW", item["date_str"], title, link)

                std_rows.append({
                    "uid": make_uid(SOURCE, link),
                    "source": SOURCE,
                    "entity": ENTITY,
                    "category": CATEGORY,
                    "published_at": item["date_str"],
                    "title": sanitize_text(title, one_line=True),
                    "url": sanitize_text(link, one_line=True),
                    "abstract": sanitize_text((full_content[:300] if full_content else ""), one_line=True),
                    "content": sanitize_text(full_content, one_line=True),
                    "content_type": "html",
                    "crawl_time": utc_now_str(),
                })
                visited_links.add(link)

            if keep_scraping:
                has_next = page.locator("a.load-more-button:not(.disabled)").count() > 0
                if has_next:
                    try:
                        page.click("a.load-more-button")
                        page.wait_for_timeout(4000)
                        page_num += 1
                    except Exception:
                        break
                else:
                    break

        browser.close()

    new_count = write_incremental_csv(all_csv=GLOBAL_ALL_CSV, new_csv=GLOBAL_NEW_CSV, rows=std_rows, append_new=True)
    log_summary(SOURCE, len(std_rows), new_count)

if __name__ == "__main__":
    main()
