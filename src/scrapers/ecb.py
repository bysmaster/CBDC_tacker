# -*- coding: utf-8 -*-
import csv
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    import undetected_chromedriver as uc
    _USE_UC = True
except Exception:
    uc = None
    _USE_UC = False
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from ..utils import (
    STANDARD_FIELDS, ensure_csv_field_size_limit, env_int, make_uid,
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

# ======================== Selenium ========================
def open_driver():
    options = uc.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    driver = uc.Chrome(options=options)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
    )
    return driver

def close_popups(driver):
    try:
        btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'accept')]"))
        )
        btn.click()
        time.sleep(1)
    except Exception:
        pass

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

# ======================== 正文抓取 ========================
def extract_text_with_selenium(driver, link):
    try:
        driver.get(link)
        time.sleep(3)
        close_popups(driver)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.section, main, article, p"))
        )
        html = driver.page_source
        content = extract_full_content(html)
        return content
    except Exception:
        return ""

# ======================== ECB 专用滚动 ========================
def scroll_to_bottom_ecb(driver, max_scroll=35):
    last_dt_count = 0
    for i in range(max_scroll):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        dts = driver.find_elements(By.CSS_SELECTOR, "dl dt")
        curr_count = len(dts)
        if curr_count == last_dt_count:
            break
        last_dt_count = curr_count

# ======================== 主抓取逻辑 ========================
def main():
    start_dt, end_dt = get_lookback_date_range()
    
    # We won't use load_existing_urls here because write_incremental_csv handles it.
    # But for backfill, we might need it. 
    # For now, let's stick to standard flow. If backfill is critical, we can read it.
    # To keep it simple and standard, I'll omit backfill logic unless it's easy to add.
    # The original script had backfill. I will keep it if possible.
    
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
    
    driver = open_driver()
    try:
        driver.get("https://www.ecb.europa.eu/press/pubbydate/html/index.en.html")
        close_popups(driver)
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".title a")))
        
        # Scroll logic: we might not need to scroll to bottom if we only want last 2 days.
        # But ECB page loads dynamically. We scroll a bit.
        # If strict lookback, we can stop scrolling when we see old dates?
        # The scroll function scrolls to bottom. Let's limit it if we can check dates.
        # For simplicity, we use the existing scroll function.
        scroll_to_bottom_ecb(driver)

        soup = BeautifulSoup(driver.page_source, "lxml")
        current_date_str = None
        
        for tag in soup.select("dl > dt, dl > dd"):
            if tag.name == "dt":
                # Reset date for new section to avoid carrying over previous date if parsing fails
                current_date_str = None
                
                raw = tag.get_text(strip=True)
                d = parse_date_text(raw)
                if d:
                    current_date_str = d.strftime("%Y-%m-%d")
                    # STRICT DATE CHECK
                    if d < start_dt:
                        # Found a date older than lookback window
                        # Since list is ordered, we can stop parsing
                        break
                else:
                    # Log warning if date parsing fails but we are in a date tag
                    # This prevents assigning old news to previous date
                    print(f"⚠️ [ECB] Failed to parse date: {raw}")
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
                        full_content = extract_text_with_selenium(driver, link)
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

                full_content = extract_text_with_selenium(driver, link)
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
        driver.quit()

    new_count = write_incremental_csv(all_csv=GLOBAL_ALL_CSV, new_csv=GLOBAL_NEW_CSV, rows=results, dedupe_by="uid", append_new=True)
    log_summary(SOURCE, len(results), new_count)

if __name__ == "__main__":
    main()
