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
BASE_URL = "https://www.centralbankbahamas.com"
LIST_URL = BASE_URL + "/news"

RETRY_TIMES = 3
TIMEOUT = 120000

SOURCE = "bahamas"
ENTITY = "巴哈马"
CATEGORY = "news"

# ==========================================

async def safe_goto(page, url, timeout=TIMEOUT, retries=RETRY_TIMES):
    for i in range(retries):
        try:
            await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            return True
        except Exception:
            await asyncio.sleep(3)
    return False

def parse_date_text(dd: str, yy_span) -> datetime:
    dd = (dd or "").strip()
    month_year = yy_span.get_text(separator=" ").strip()
    match = re.match(r"([A-Za-z]+)\s+(\d{4})", month_year)
    if not match:
        return None
    month_str, year_str = match.groups()
    date_str = f"{dd} {month_str} {year_str}"
    try:
        return datetime.strptime(date_str, "%d %b %Y")
    except ValueError:
        return None

async def fetch_detail_content(page, link: str):
    for attempt in range(RETRY_TIMES):
        try:
            await page.goto(link, timeout=TIMEOUT, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            content_div = soup.select_one("div.right_content")
            if not content_div:
                return ""
            paragraphs = []
            h1 = content_div.select_one("h1.cms_detail_h2")
            if h1:
                paragraphs.append(h1.get_text(strip=True))
            for p in content_div.find_all("p"):
                t = p.get_text(separator=" ", strip=True)
                if t:
                    paragraphs.append(t)
            return sanitize_text("\n\n".join(paragraphs), one_line=True)
        except Exception:
            await asyncio.sleep(3)
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

        if not await safe_goto(page, LIST_URL):
            print(f"[{SOURCE}] List page failed.")
            return

        count = 0
        while count < MAX_ARTICLES and not stop_early:
            await page.wait_for_timeout(2000)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            news_boxes = soup.select("div.news_box")
            if not news_boxes:
                break

            for box in news_boxes:
                if count >= MAX_ARTICLES or stop_early:
                    break

                dd_span = box.select_one("span.dd")
                yy_span = box.select_one("span.yy")
                if not dd_span or not yy_span:
                    continue

                article_dt = parse_date_text(dd_span.get_text(strip=True), yy_span)
                if article_dt is None:
                    continue

                # STRICT DATE CHECK
                if article_dt < start_dt:
                    stop_early = True
                    break

                link_tag = box.select_one("a.title_div")
                if not link_tag:
                    continue
                link = (link_tag.get("href", "") or "").strip()
                if link and not link.startswith("http"):
                    link = BASE_URL + link
                if not link or link in visited_links:
                    continue

                title = link_tag.get_text(strip=True)
                abs_p = box.select_one("div.info_cell > p:not(.category_div)")
                list_abstract = abs_p.get_text(strip=True) if abs_p else ""

                detail_page = await context.new_page()
                content_text = await fetch_detail_content(detail_page, link)
                await detail_page.close()

                if not content_text:
                    content_text = sanitize_text(list_abstract or title, one_line=True)

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
                    "abstract": sanitize_text(list_abstract, one_line=True),
                    "content": sanitize_text(content_text, one_line=True),
                    "content_type": "html",
                    "crawl_time": utc_now_str(),
                })

                visited_links.add(link)
                count += 1

            if stop_early:
                break

            # Pagination
            try:
                next_a = await page.query_selector('ul.ac-pagination a:has-text("»")')
                if not next_a or not await next_a.is_visible() or not await next_a.is_enabled():
                    next_a = await page.query_selector('ul.ac-pagination li:not(.active) a')

                if next_a:
                    await next_a.click()
                    await page.wait_for_load_state("domcontentloaded")
                    await page.wait_for_timeout(4000)
                    continue
                break
            except Exception:
                break

        await browser.close()

    new_count = write_incremental_csv(all_csv=GLOBAL_ALL_CSV, new_csv=GLOBAL_NEW_CSV, rows=std_rows, append_new=True)
    log_summary(SOURCE, len(std_rows), new_count)

if __name__ == "__main__":
    asyncio.run(main())
