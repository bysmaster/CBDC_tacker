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
LIST_BASE_URL = "https://www.cbr.ru/eng/"
MAX_PAGES = 50

SOURCE = "cbr"
ENTITY = "俄罗斯"
CATEGORY = "news"

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
        page.wait_for_timeout(3000)
        content_selector = page.locator("div.full_text, div.article_body, div.content").first
        if content_selector.count() > 0:
            paragraphs = content_selector.locator("p, h2, h3, div.paragraph").all_inner_texts()
            full_text = " ".join(paragraphs)
        else:
            all_p = page.locator("p").all_inner_texts()
            if len(all_p) > 5:
                full_text = " ".join(all_p[2:-3])
            else:
                full_text = " ".join(all_p)
    except Exception:
        pass
    finally:
        page.close()
        context.close()
    return clean_text_to_single_line(full_text)

def extract_list_page(page):
    page.wait_for_selector("#events_tab100", timeout=30000)
    page.wait_for_timeout(1500)
    items = page.locator("div.news").all()
    results = []
    for item in items:
        try:
            date_elem = item.locator("div.news_date").first
            date_str = date_elem.inner_text().strip() if date_elem.count() > 0 else ""
            category_elem = item.locator("div.news_category").first
            category = category_elem.inner_text().strip() if category_elem.count() > 0 else ""
            title_elem = item.locator("a.news_title").first
            title = title_elem.inner_text().strip() if title_elem.count() > 0 else ""
            link = title_elem.get_attribute("href") if title_elem.count() > 0 else ""
            if link and not link.startswith("http"):
                link = "https://www.cbr.ru" + link
            date_obj = None
            try:
                if date_str:
                    date_obj = datetime.strptime(date_str, "%d %B %Y")
            except Exception:
                date_obj = None
            if title and link and date_obj:
                results.append({
                    "date_obj": date_obj,
                    "date_str": date_obj.strftime("%Y-%m-%d"),
                    "category": category,
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
        page.wait_for_timeout(5000)

        keep_scraping = True
        page_num = 1

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
                category = item.get("category") or CATEGORY
                
                full_content = get_article_content(browser, link)
                
                log_item(SOURCE, "NEW", item["date_str"], title, link)

                std_rows.append({
                    "uid": make_uid(SOURCE, link),
                    "source": SOURCE,
                    "entity": ENTITY,
                    "category": sanitize_text(category, one_line=True) or CATEGORY,
                    "published_at": item["date_str"],
                    "title": sanitize_text(title, one_line=True),
                    "url": sanitize_text(link, one_line=True),
                    "abstract": sanitize_text((full_content[:300] if full_content else ""), one_line=True),
                    "content": sanitize_text(full_content, one_line=True),
                    "content_type": "html",
                    "crawl_time": utc_now_str(),
                })
                visited_links.add(link)
                time.sleep(1)

            if keep_scraping:
                load_more_button = page.locator("button#_buttonLoadNextEvt.more-button._small._home-news").first
                if load_more_button.count() > 0 and load_more_button.is_visible() and load_more_button.is_enabled():
                    try:
                        load_more_button.click()
                        page.wait_for_timeout(5000)
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
