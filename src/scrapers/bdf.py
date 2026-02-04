# -*- coding: utf-8 -*-
import asyncio
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup
from dateutil import parser
from playwright.async_api import async_playwright

from ..utils import (
    STANDARD_FIELDS, make_uid, sanitize_text, utc_now_str, write_incremental_csv,
    log_item, log_summary, get_lookback_date_range, GLOBAL_ALL_CSV, GLOBAL_NEW_CSV
)

# ================= 配置区 =================
MAX_ARTICLES = 200
BASE_URL = "https://www.banque-france.fr"
LIST_URL = BASE_URL + "/en/recherche"

RETRY_TIMES = 3
TIMEOUT = 120000

SOURCE = "bdf"
ENTITY = "法国"
CATEGORY = "search"

# ==========================================

async def safe_goto(page, url, timeout=TIMEOUT, retries=RETRY_TIMES):
    for i in range(retries):
        try:
            await page.goto(url, timeout=timeout, wait_until="networkidle")
            await page.wait_for_timeout(3000)
            return True
        except Exception:
            await asyncio.sleep(3)
    return False

def parse_date_text(date_raw: str):
    if not date_raw:
        return None
    date_raw = re.sub(r"(\d+)(st|nd|rd|th)\s+of\s+", r"\1 ", date_raw, flags=re.I)
    try:
        return parser.parse(date_raw, fuzzy=True)
    except Exception:
        return None

async def fetch_detail_content(page, link):
    for attempt in range(RETRY_TIMES):
        try:
            await page.goto(link, timeout=TIMEOUT, wait_until="networkidle")
            await page.wait_for_timeout(3000)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            content_div = soup.select_one("div.rich-text") or soup.select_one("div.field__item")
            if content_div:
                paragraphs = []
                for p in content_div.find_all(["p", "h1", "h2", "h3", "h4", "strong"]):
                    t = p.get_text(separator=" ", strip=True)
                    if t:
                        paragraphs.append(t)
                content_text = "\n\n".join(paragraphs)
            else:
                content_text = ""
            return sanitize_text(content_text, one_line=True)
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
            try:
                await page.wait_for_selector("li.news-list-item", timeout=30000)
            except Exception:
                pass

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            posts = soup.select("div.views-row")
            if not posts:
                break

            for post in posts:
                if count >= MAX_ARTICLES or stop_early:
                    break

                date_small = post.select_one("small.text-grey-l6")
                if not date_small:
                    continue

                dt = parse_date_text(date_small.get_text(strip=True))
                if dt is None:
                    continue

                # STRICT DATE CHECK
                if dt < start_dt:
                    stop_early = True
                    break

                card_a = post.select_one("a.search-result-card")
                if not card_a:
                    continue

                link = (card_a.get("href", "") or "").strip()
                if not link.startswith("http"):
                    link = BASE_URL + link

                if not link or link in visited_links:
                    continue

                title_h3 = post.select_one("h3.title")
                title = title_h3.get_text(strip=True) if title_h3 else ""
                abs_p = post.select_one("p.card-text")
                list_abstract = abs_p.get_text(strip=True) if abs_p else ""

                detail_page = await context.new_page()
                content_text = await fetch_detail_content(detail_page, link)
                await detail_page.close()

                if not content_text:
                    content_text = sanitize_text(list_abstract or title, one_line=True)

                article_date_str = dt.strftime("%Y-%m-%d")
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

            try:
                next_btn = await page.query_selector("li.pager__item--next a")
                if next_btn and await next_btn.is_visible() and await next_btn.is_enabled():
                    await next_btn.click()
                    await page.wait_for_load_state("networkidle")
                    await page.wait_for_timeout(4000)
                else:
                    break
            except Exception:
                break

        await browser.close()

    new_count = write_incremental_csv(all_csv=GLOBAL_ALL_CSV, new_csv=GLOBAL_NEW_CSV, rows=std_rows, append_new=True)
    log_summary(SOURCE, len(std_rows), new_count)

if __name__ == "__main__":
    asyncio.run(main())
