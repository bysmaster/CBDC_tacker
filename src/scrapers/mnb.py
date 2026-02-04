# -*- coding: utf-8 -*-
import asyncio
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from ..utils import (
    STANDARD_FIELDS, make_uid, sanitize_text, utc_now_str, write_incremental_csv,
    log_item, log_summary, get_lookback_date_range, GLOBAL_ALL_CSV, GLOBAL_NEW_CSV
)

# ================= 配置区 =================
MAX_ARTICLES = 200
BASE_URL = "https://www.mnb.hu"
NOW = datetime.now()

CANDIDATE_LIST_URLS = [
    f"{BASE_URL}/en/pressroom/news/news-{NOW.year}",
    f"{BASE_URL}/en/pressroom/news/news-{NOW.year - 1}",
    f"{BASE_URL}/en/pressroom/news",
]

RETRY_TIMES = 3
TIMEOUT = 120000

SOURCE = "mnb"
ENTITY = "匈牙利"
CATEGORY = "news"

# ==========================================

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

async def safe_goto(page, url, timeout=TIMEOUT, retries=RETRY_TIMES):
    for i in range(retries):
        try:
            await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)
            return True
        except Exception:
            await asyncio.sleep(3)
    return False

def parse_date_text(date_raw: str) -> datetime:
    if not date_raw:
        return None
    date_raw = date_raw.strip().rstrip(".").strip()
    parts = re.split(r"\s+", date_raw)
    if len(parts) != 3:
        return None
    try:
        day = int(parts[0])
        month = MONTH_MAP.get(parts[1].lower())
        year = int(parts[2])
        if not month:
            return None
        return datetime(year, month, day)
    except Exception:
        return None

async def fetch_detail_content(page, link: str):
    for attempt in range(RETRY_TIMES):
        try:
            await page.goto(link, timeout=TIMEOUT, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            content_div = soup.select_one("div.c-ph")
            if not content_div:
                return ""
            paragraphs = []
            for p in content_div.find_all("p"):
                t = p.get_text(separator=" ", strip=True)
                if t:
                    paragraphs.append(t)
            return sanitize_text("\n\n".join(paragraphs), one_line=True)
        except Exception:
            await asyncio.sleep(3)
    return ""

async def _goto_first_working_list(page) -> str:
    for url in CANDIDATE_LIST_URLS:
        ok = await safe_goto(page, url)
        if not ok:
            continue
        try:
            await page.wait_for_selector("li.news-list-item", timeout=8000)
            return url
        except Exception:
            continue
    return ""

async def main():
    start_dt, end_dt = get_lookback_date_range()
    
    std_rows = []
    visited_links = set()
    stop_early = False

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        list_url = await _goto_first_working_list(page)
        if not list_url:
            print(f"[{SOURCE}] Failed to find working list URL.")
            return

        count = 0
        while count < MAX_ARTICLES and not stop_early:
            try:
                await page.wait_for_selector("li.news-list-item", timeout=30000)
            except Exception:
                break

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            items = soup.select("li.news-list-item")
            if not items:
                break

            for item in items:
                if count >= MAX_ARTICLES or stop_early:
                    break

                date_p = item.select_one("p.news-list-item-date")
                if not date_p:
                    continue
                date_raw = date_p.get_text(strip=True)
                article_dt = parse_date_text(date_raw)
                if article_dt is None:
                    continue

                # STRICT DATE CHECK
                if article_dt < start_dt:
                    stop_early = True
                    break

                link_a = item.select_one("p.news-list-item-title a")
                if not link_a:
                    continue

                link = (link_a.get("href", "") or "").strip()
                if link.startswith("//"):
                    link = "https:" + link
                elif link and not link.startswith("http"):
                    link = BASE_URL + link

                if not link or link in visited_links:
                    continue

                title = link_a.get_text(strip=True)

                detail_page = await context.new_page()
                content_text = await fetch_detail_content(detail_page, link)
                await detail_page.close()

                if not content_text:
                    content_text = sanitize_text(title, one_line=True)

                article_date_str = article_dt.strftime("%Y-%m-%d")
                log_item(SOURCE, "NEW", article_date_str, title, link)

                std_rows.append({
                    "uid": make_uid(SOURCE, link),
                    "source": SOURCE,
                    "entity": ENTITY,
                    "category": CATEGORY,
                    "published_at": article_date_str,
                    "title": sanitize_text(title, one_line=True),
                    "url": sanitize_text(link, one_line=True),
                    "abstract": "",
                    "content": sanitize_text(content_text, one_line=True),
                    "content_type": "html",
                    "crawl_time": utc_now_str(),
                })

                visited_links.add(link)
                count += 1

            if stop_early:
                break

            try:
                next_btn = await page.query_selector("a._next")
                if next_btn and await next_btn.is_visible() and await next_btn.is_enabled():
                    await next_btn.click()
                    await page.wait_for_load_state("networkidle")
                    await page.wait_for_timeout(5000)
                else:
                    break
            except Exception:
                break

        await browser.close()

    new_count = write_incremental_csv(all_csv=GLOBAL_ALL_CSV, new_csv=GLOBAL_NEW_CSV, rows=std_rows, append_new=True)
    log_summary(SOURCE, len(std_rows), new_count)

if __name__ == "__main__":
    asyncio.run(main())
