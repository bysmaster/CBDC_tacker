# -*- coding: utf-8 -*-
import csv
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

from ..utils import (
    STANDARD_FIELDS, make_uid, sanitize_text, utc_now_str, write_incremental_csv,
    log_item, log_summary, get_lookback_date_range, env_int, load_existing_keys, GLOBAL_ALL_CSV, GLOBAL_NEW_CSV
)

# ================= 配置区 =================
SEARCH_URL = "https://www.imf.org/en/news/searchnews#q=%20&sortCriteria=%40imfdate%20descending"
MAX_PAGES = env_int("CBDC_MAX_PAGES", 50)

# Playwright 导航/等待超时与重试（避免偶发网络/站点响应慢导致失败）
NAV_TIMEOUT_MS = env_int("CBDC_NAV_TIMEOUT_MS", 120_000)
NAV_RETRIES = env_int("CBDC_NAV_RETRIES", 2)

SOURCE = "imf"
ENTITY = "IMF"
CATEGORY = "news"

# 有历史 all.csv 时：连续遇到多少条已抓取链接就停止（列表通常按时间倒序）
SEEN_HIT_LIMIT = env_int("CBDC_SEEN_HIT_LIMIT", 30)

# ==========================================

def clean_text_to_single_line(text):
    if not text:
        return ""
    return " ".join(str(text).replace("\n", " ").replace("\r", " ").replace("\t", " ").split())

def get_article_content(browser, url):
    if not url or "http" not in url:
        return ""
    context = browser.new_context()
    detail_page = context.new_page()
    raw_content = ""
    try:
        detail_page.goto(url, timeout=60000, wait_until="domcontentloaded")
        selectors = [".article-body", ".news-article", "article", "main"]
        for selector in selectors:
            container = detail_page.locator(selector).first
            if container.count() > 0:
                p_texts = container.locator("p").all_inner_texts()
                if p_texts:
                    raw_content = " ".join(p_texts)
                    if len(raw_content.strip()) > 100:
                        break
        if not raw_content:
            raw_content = " ".join(detail_page.locator("p").all_inner_texts())
    except Exception:
        pass
    finally:
        detail_page.close()
        context.close()
    return clean_text_to_single_line(raw_content)

def extract_list_page(page):
    page.wait_for_selector("atomic-result", timeout=NAV_TIMEOUT_MS)
    page.wait_for_timeout(5000)  # Increased wait time for Shadow DOM
    cards = page.locator("atomic-result").all()
    results = []
    for card in cards:
        data = card.evaluate(
            """(element) => {
            function getAllElements(root, list = []) {
                list.push(root);
                if (root.shadowRoot) getAllElements(root.shadowRoot, list);
                let children = root.querySelectorAll('*');
                for (let child of children) { getAllElements(child, list); }
                return list;
            }
            const allNodes = getAllElements(element);
            const aTag = allNodes.find(n => n.tagName === 'A' && n.href && n.href.includes('/news/articles/'));
            const dateNode = allNodes.find(n => n.tagName === 'ATOMIC-TEXT' && n.getAttribute('value') && n.getAttribute('value').includes(','));
            const abstractNode = allNodes.find(n => n.className && n.className.includes('excerpt'));
            return {
                title: aTag ? aTag.innerText : '',
                link: aTag ? aTag.href : '',
                dateStr: dateNode ? dateNode.getAttribute('value') : '',
                abstract: abstractNode ? abstractNode.innerText : ''
            };
        }"""
        )
        try:
            current_item_date = datetime.strptime(data["dateStr"], "%B %d, %Y")
        except Exception:
            current_item_date = None
        
        if data["title"] and data["link"]:
            results.append({
                "date_obj": current_item_date,
                "date_str": current_item_date.strftime("%Y-%m-%d") if current_item_date else data["dateStr"],
                "link": data["link"],
                "title": data["title"].strip(),
                "abstract": data["abstract"].strip(),
            })
    return results

def main():
    # Load existing history for deduplication optimization
    existing_uids, existing_urls = load_existing_keys(GLOBAL_ALL_CSV)
    
    start_dt, end_dt = get_lookback_date_range()
    min_date_str = start_dt.strftime("%Y-%m-%d")
    
    std_rows = []
    visited = set()
    consecutive_seen = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(NAV_TIMEOUT_MS)
        page.set_default_navigation_timeout(NAV_TIMEOUT_MS)

        last_err = None
        for attempt in range(1, NAV_RETRIES + 1):
            try:
                page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                last_err = None
                break
            except Exception as e:
                last_err = e
                print(f"⚠️ IMF 列表页打开失败（{attempt}/{NAV_RETRIES}）：{e}")
                page.wait_for_timeout(1500)
        
        if last_err is not None:
            browser.close()
            raise last_err

        page_num = 1
        while page_num <= MAX_PAGES:
            print(f"\n📂 扫描第 {page_num} 页...")
            list_items = extract_list_page(page)
            if not list_items:
                print("❌ 未能获取列表，结束。")
                break

            for item in list_items:
                link = (item.get("link") or "").strip()
                if not link or link in visited:
                    continue

                d = item.get("date_obj")
                # STRICT DATE CHECK
                if d:
                    item_date = d.replace(tzinfo=None) # ensure naive comparison if needed
                    # Note: start_dt from utils is naive or local, ensure consistency
                    if item_date < start_dt:
                        # IMF list is ordered, so we can stop
                        print(f"🛑 发现历史日期 {item.get('date_str')} 早于窗口期，停止。")
                        browser.close()
                        new_count = write_incremental_csv(all_csv=GLOBAL_ALL_CSV, new_csv=GLOBAL_NEW_CSV, rows=std_rows, append_new=True)
                        log_summary(SOURCE, len(std_rows), new_count)
                        return

                # Deduplication Optimization
                if link in existing_urls:
                    visited.add(link)
                    consecutive_seen += 1
                    if consecutive_seen >= SEEN_HIT_LIMIT:
                        print(f"🛑 连续遇到已抓取 {SEEN_HIT_LIMIT} 条，停止。")
                        browser.close()
                        new_count = write_incremental_csv(all_csv=GLOBAL_ALL_CSV, new_csv=GLOBAL_NEW_CSV, rows=std_rows, append_new=True)
                        log_summary(SOURCE, len(std_rows), new_count)
                        return
                    continue

                consecutive_seen = 0
                visited.add(link)
                title = item.get("title", "")
                abstract = item.get("abstract", "")

                print(f"   🔍 抓取正文: [{item.get('date_str')}] {title[:40]}...")
                full_text = get_article_content(browser, link)
                
                log_item(SOURCE, "NEW", item.get("date_str", ""), title, link)

                std_rows.append({
                    "uid": make_uid(SOURCE, link),
                    "source": SOURCE,
                    "entity": ENTITY,
                    "category": CATEGORY,
                    "published_at": sanitize_text(item.get("date_str", ""), one_line=True),
                    "title": sanitize_text(title, one_line=True),
                    "url": sanitize_text(link, one_line=True),
                    "abstract": sanitize_text(abstract, one_line=True),
                    "content": sanitize_text(full_text, one_line=True),
                    "content_type": "html",
                    "crawl_time": utc_now_str(),
                })

            success = page.evaluate(
                """() => {
                const btn = document.querySelector('atomic-pager')?.shadowRoot?.querySelector('button[aria-label="Next"]');
                if(btn && btn.getAttribute('aria-disabled') !== 'true') {
                    btn.click();
                    return true;
                }
                return false;
            }"""
            )
            if not success:
                print("🏁 已到达最后一页。")
                break
            page_num += 1
            page.wait_for_timeout(4000)

        browser.close()

    new_count = write_incremental_csv(all_csv=GLOBAL_ALL_CSV, new_csv=GLOBAL_NEW_CSV, rows=std_rows, append_new=True)
    log_summary(SOURCE, len(std_rows), new_count)

if __name__ == "__main__":
    main()
