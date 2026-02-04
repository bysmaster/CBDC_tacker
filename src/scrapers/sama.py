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
BASE_URL = "https://www.sama.gov.sa"
LIST_URL = BASE_URL + "/en-US/News/Pages/allnews.aspx"

RETRY_TIMES = 3
TIMEOUT = 120000

SOURCE = "sama"
ENTITY = "沙特"
CATEGORY = "news"

# ==========================================

async def safe_goto(page, url, timeout=TIMEOUT, retries=RETRY_TIMES):
    for i in range(retries):
        try:
            await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            return True
        except Exception as e:
            await asyncio.sleep(3)
    return False

def parse_date_text(date_raw: str) -> str:
    now = datetime.now()
    if not date_raw:
        return now.strftime("%Y-%m-%d")
    date_raw = date_raw.strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", date_raw)
    if m:
        a, b, yy = m.groups()
        # SAMA usually DD/MM
        dd, mm = a, b
        return f"{int(yy):04d}-{int(mm):02d}-{int(dd):02d}"
    return now.strftime("%Y-%m-%d")

async def fetch_detail_content(page, link):
    for attempt in range(RETRY_TIMES):
        try:
            await page.goto(link, timeout=TIMEOUT, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            content_div = soup.select_one("div.pagecontent div.ms-rtestate-field") or soup.select_one("div.pagecontent")
            if content_div:
                paragraphs = []
                for elem in content_div.find_all(["p", "h4", "h3", "div", "strong"]):
                    t = elem.get_text(separator=" ", strip=True)
                    if t:
                        paragraphs.append(t)
                content_text = "\n\n".join(paragraphs)
            else:
                content_text = ""
            return sanitize_text(content_text, one_line=True)
        except Exception as e:
            await asyncio.sleep(3)
    return ""

async def main():
    start_dt, end_dt = get_lookback_date_range()
    min_date_str = start_dt.strftime("%Y-%m-%d")
    
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

            posts = soup.select("li.dfwp-item")
            if not posts:
                break

            new_added = 0
            for post in posts:
                if count >= MAX_ARTICLES or stop_early:
                    break

                title_tag = post.select_one("h2.newsitem-title a")
                if not title_tag:
                    continue
                link = (title_tag.get("href", "") or "").strip()
                if not link.startswith("http"):
                    link = BASE_URL + link

                if not link or link in visited_links:
                    continue

                date_div = post.select_one("div.year.item-date")
                date_raw = date_div.get_text(strip=True) if date_div else ""
                article_date = parse_date_text(date_raw)

                # STRICT DATE CHECK
                if article_date < min_date_str:
                    stop_early = True
                    break

                title = title_tag.get_text(strip=True)
                abs_div = post.select_one("div.description.hidden-xs")
                list_abstract = abs_div.get_text(strip=True) if abs_div else ""

                detail_page = await context.new_page()
                content_text = await fetch_detail_content(detail_page, link)
                await detail_page.close()

                if not content_text:
                    content_text = sanitize_text(list_abstract, one_line=True)

                std_rows.append({
                    "uid": make_uid(SOURCE, link),
                    "source": SOURCE,
                    "entity": ENTITY,
                    "category": CATEGORY,
                    "published_at": sanitize_text(article_date, one_line=True),
                    "title": sanitize_text(title, one_line=True),
                    "url": sanitize_text(link, one_line=True),
                    "abstract": sanitize_text(list_abstract, one_line=True),
                    "content": sanitize_text(content_text, one_line=True),
                    "content_type": "html",
                    "crawl_time": utc_now_str(),
                })

                visited_links.add(link)
                count += 1
                new_added += 1
                
                log_item(SOURCE, "NEW", article_date, title, link)

            if stop_early or new_added == 0:
                break

            # Pagination
            try:
                next_button = await page.query_selector("a.pageNextButton")
                if next_button and await next_button.is_visible() and await next_button.is_enabled():
                    await next_button.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=60000)
                    await page.wait_for_timeout(8000)
                    await page.wait_for_selector("li.dfwp-item", state="visible", timeout=30000)
                else:
                    break
            except Exception:
                break

        await browser.close()

    new_count = write_incremental_csv(all_csv=GLOBAL_ALL_CSV, new_csv=GLOBAL_NEW_CSV, rows=std_rows, append_new=True)
    log_summary(SOURCE, len(std_rows), new_count)

if __name__ == "__main__":
    asyncio.run(main())
