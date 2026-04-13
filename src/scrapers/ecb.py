# -*- coding: utf-8 -*-
import csv
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from ..utils import (
    STANDARD_FIELDS, env_int, make_uid,
    sanitize_text, utc_now_str, write_incremental_csv,
    log_item, log_summary, get_lookback_date_range, GLOBAL_ALL_CSV, GLOBAL_NEW_CSV
)

# ======================== 输出配置 ========================
SOURCE = "ecb"
ENTITY = "欧央行"
CATEGORY = "press"

# 回填开关
BACKFILL_EMPTY_CONTENT = env_int("CBDC_BACKFILL_EMPTY_CONTENT", 1)
BACKFILL_MAX = env_int("CBDC_BACKFILL_MAX", 20)

# ======================== ECB 正文提取 ========================
def extract_ecb_content(html):
    soup = BeautifulSoup(html, "lxml")
    unwanted = [
        "header", "footer", "nav", "aside", "sup", ".ecb-doc-header", ".ecb-doc-footer",
        ".ecb-social-sharing", ".related-topics", ".address-box", ".ecb-breadcrumbscontainer",
        ".ecb-publicationDate", ".ecb-authors", ".info-box", "#cookieConsent", "#feedback",
    ]
    
    def _clean_container(container_html: str) -> str:
        sub = BeautifulSoup(container_html, "lxml")
        root = sub
        for sel in unwanted:
            for t in root.select(sel):
                t.decompose()
        texts = []
        for el in root.select("h1,h2,h3,h4,p,li"):
            txt = el.get_text(" ", strip=True)
            if not txt:
                continue
            if el.name == "li" or len(txt) >= 20:
                texts.append(txt)
        return "\n\n".join(texts).strip()

    candidates = []
    main = soup.find("main")
    if main is not None:
        candidates.append(main)
        candidates.extend(main.select("div.section"))
    candidates.extend(soup.select("div.section"))
    if not candidates:
        if soup.body is None:
            return ""
        candidates = [soup.body]

    best = ""
    for c in candidates:
        text = _clean_container(str(c))
        if len(text) > len(best):
            best = text
    return best

def extract_full_content(html):
    return extract_ecb_content(html)

# ======================== Playwright ========================
def extract_text_with_playwright(page, link):
    try:
        page.goto(link, timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)
        
        # Try to close cookie popup
        try:
            accept_btn = page.locator('button:has-text("Accept")').first
            if accept_btn.is_visible(timeout=2000):
                accept_btn.click()
                page.wait_for_timeout(1000)
        except:
            pass
        
        # Wait for content
        page.wait_for_selector("div.section, main, article, p", timeout=15000)
        html = page.content()
        content = extract_full_content(html)
        return content
    except Exception as e:
        print(f"[ECB] Error extracting content from {link}: {e}")
        return ""

# ======================== 日期解析 ========================
def parse_date_text(text):
    if not text:
        return None
    text = text.split(",")[0].strip()
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass
    return None

# ======================== 跳过规则 ========================
SKIP_EXT = [".pdf", ".xlsx", ".xls", ".doc", ".docx", ".zip", ".rar"]
def should_skip_link(link, title):
    if any(link.lower().endswith(ext) for ext in SKIP_EXT):
        return True
    skip_words = ["annex", "attachment", "chart", "figure", "table"]
    return any(w in (title or "").lower() for w in skip_words)

# ======================== ECB 专用滚动 ========================
def scroll_to_bottom_ecb(page, max_scroll=35):
    last_dt_count = 0
    for i in range(max_scroll):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        dts = page.locator("dl dt").count()
        if dts == last_dt_count:
            break
        last_dt_count = dts

# ======================== 主抓取逻辑 ========================
def main():
    start_dt, end_dt = get_lookback_date_range()
    
    # Load existing for dedupe check during run to save time
    from ..utils import load_existing_keys
    existing_uids, existing_urls = load_existing_keys(GLOBAL_ALL_CSV)
    
    # Missing content check for backfill
    missing_content_urls = set()
    if BACKFILL_EMPTY_CONTENT and GLOBAL_ALL_CSV.exists():
        with GLOBAL_ALL_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                for row in reader:
                    u = (row.get("url") or "").strip()
                    if u and not row.get("content"):
                        missing_content_urls.add(u)

    results = []
    backfilled = 0
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        
        try:
            page.goto("https://www.ecb.europa.eu/press/pubbydate/html/index.en.html", 
                     timeout=60000, wait_until="networkidle")
            
            # Close cookie popup if present
            try:
                accept_btn = page.locator('button:has-text("Accept")').first
                if accept_btn.is_visible(timeout=5000):
                    accept_btn.click()
                    page.wait_for_timeout(1000)
            except:
                pass
            
            # Wait for content to load
            page.wait_for_selector(".title a", timeout=30000)
            
            # Scroll to load more content
            scroll_to_bottom_ecb(page)

            html = page.content()
            soup = BeautifulSoup(html, "lxml")
            current_date_str = None
            
            for tag in soup.select("dl > dt, dl > dd"):
                if tag.name == "dt":
                    current_date_str = None
                    
                    raw = tag.get_text(strip=True)
                    d = parse_date_text(raw)
                    if d:
                        current_date_str = d.strftime("%Y-%m-%d")
                        # STRICT DATE CHECK
                        if d < start_dt:
                            break
                    else:
                        print(f"[ECB] Failed to parse date: {raw}")
                    continue

                if tag.name == "dd" and current_date_str:
                    a = tag.select_one(".title a")
                    if not a:
                        continue
                    title = a.get_text(strip=True)
                    link = "https://www.ecb.europa.eu" + a["href"]

                    if should_skip_link(link, title):
                        continue

                    if link in existing_urls:
                        # Backfill logic
                        if BACKFILL_EMPTY_CONTENT and link in missing_content_urls and backfilled < BACKFILL_MAX:
                            detail_page = context.new_page()
                            full_content = extract_text_with_playwright(detail_page, link)
                            detail_page.close()
                            time.sleep(1)
                            backfilled += 1
                            results.append({
                                "uid": make_uid(SOURCE, link),
                                "source": SOURCE,
                                "entity": ENTITY,
                                "category": CATEGORY,
                                "published_at": current_date_str,
                                "title": sanitize_text(title, one_line=True),
                                "url": link,
                                "abstract": sanitize_text(full_content[:5000], one_line=True),
                                "content": sanitize_text(full_content, one_line=True),
                                "content_type": "html",
                                "crawl_time": utc_now_str(),
                            })
                            log_item(SOURCE, "BACKFILL", current_date_str, title, link)
                        continue

                    detail_page = context.new_page()
                    full_content = extract_text_with_playwright(detail_page, link)
                    detail_page.close()
                    time.sleep(1)
                    
                    log_item(SOURCE, "NEW", current_date_str, title, link)

                    results.append({
                        "uid": make_uid(SOURCE, link),
                        "source": SOURCE,
                        "entity": ENTITY,
                        "category": CATEGORY,
                        "published_at": current_date_str,
                        "title": sanitize_text(title, one_line=True),
                        "url": link,
                        "abstract": sanitize_text(full_content[:5000], one_line=True),
                        "content": sanitize_text(full_content, one_line=True),
                        "content_type": "html",
                        "crawl_time": utc_now_str(),
                    })

        finally:
            browser.close()

    new_count = write_incremental_csv(all_csv=GLOBAL_ALL_CSV, new_csv=GLOBAL_NEW_CSV, rows=results, dedupe_by="uid", append_new=True)
    log_summary(SOURCE, len(results), new_count)

if __name__ == "__main__":
    main()
