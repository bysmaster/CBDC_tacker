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
BASE_URL = "https://www.bi.go.id"
LIST_URL = BASE_URL + "/en/publikasi/ruang-media/news-release/default.aspx"

RETRY_TIMES = 3
TIMEOUT = 120000

SOURCE = "bi"
ENTITY = "印度尼西亚"
CATEGORY = "news_release"

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
    if "•" in date_raw:
        date_part = date_raw.split("•")[0].strip()
    else:
        date_part = date_raw

    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            dt = datetime.strptime(date_part, fmt)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    return now.strftime("%Y-%m-%d")

async def fetch_detail_content(page, link):
    for attempt in range(RETRY_TIMES):
        try:
            await page.goto(link, timeout=TIMEOUT, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            content_wrapper = soup.select_one("div.page-description") or soup.select_one("div.col-md-8")
            if content_wrapper:
                paragraphs = []
                for elem in content_wrapper.find_all(["p", "h4", "table", "strong"]):
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
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            ignore_https_errors=True
        )
        page = await context.new_page()

        if not await safe_goto(page, LIST_URL):
            print(f"[{SOURCE}] List page failed.")
            return

        count = 0
        while count < MAX_ARTICLES and not stop_early:
            await page.wait_for_timeout(2000)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            posts = soup.select("div.media.media--pers")
            if not posts:
                break

            new_added = 0
            for post in posts:
                if count >= MAX_ARTICLES or stop_early:
                    break

                link_tag = post.select_one("a.media__title")
                if not link_tag:
                    continue
                link = (link_tag.get("href", "") or "").strip()
                if not link.startswith("http"):
                    link = BASE_URL + link

                if not link or link in visited_links:
                    continue

                subtitle_div = post.select_one("div.media__subtitle")
                date_raw = subtitle_div.get_text(strip=True) if subtitle_div else ""
                article_date = parse_date_text(date_raw)

                # STRICT DATE CHECK
                if article_date < min_date_str:
                    stop_early = True
                    break

                title = link_tag.get_text(strip=True)
                abs_p = post.select_one("p.ellipsis--three-line")
                list_abstract = abs_p.get_text(strip=True) if abs_p else ""

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
                next_button = await page.query_selector("input.next:not(.aspNetDisabled)")
                if next_button and await next_button.is_visible():
                    await next_button.click()
                    await page.wait_for_load_state("domcontentloaded")
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
