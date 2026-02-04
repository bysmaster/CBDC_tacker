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
BASE_URL = "https://www2.bcra.gob.ar"
LIST_URL = BASE_URL + "/Noticias/Noticias_i.asp"

RETRY_TIMES = 3
TIMEOUT = 120000

SOURCE = "bcra"
ENTITY = "阿根廷"
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
    if not date_raw:
        return datetime.now().strftime("%Y-%m-%d")
    date_raw = date_raw.strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", date_raw)
    if m:
        mm, dd, yy = m.groups()
        return f"{int(yy):04d}-{int(mm):02d}-{int(dd):02d}"
    return datetime.now().strftime("%Y-%m-%d")

async def fetch_detail_content(page, link):
    for attempt in range(RETRY_TIMES):
        try:
            await page.goto(link, timeout=TIMEOUT, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            content_div = soup.select_one("div.clearfix.pagina-interior")
            if content_div:
                paragraphs = []
                h2 = content_div.select_one("h2")
                if h2:
                    paragraphs.append(h2.get_text(strip=True))
                for p in content_div.select("p.post-pagina-interior"):
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

        await page.wait_for_timeout(2000)
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        rows = soup.select("tbody tr")
        if not rows:
            print("未检测到文章块，停止。")

        count = 0
        for row in rows:
            if count >= MAX_ARTICLES or stop_early:
                break

            date_span = row.select_one("span.fecha-tabla")
            if not date_span:
                continue

            article_date = parse_date_text(date_span.get_text(strip=True))
            
            # STRICT DATE CHECK
            if article_date < min_date_str:
                stop_early = True
                break

            link_tag = row.select_one("a")
            if not link_tag:
                continue

            relative_link = (link_tag.get("href", "") or "").strip()
            link = BASE_URL + "/Noticias/" + relative_link

            if not link or link in visited_links:
                continue

            title = link_tag.get_text(strip=True)
            list_abstract = ""

            detail_page = await context.new_page()
            content_text = await fetch_detail_content(detail_page, link)
            await detail_page.close()

            if not content_text:
                content_text = sanitize_text(title, one_line=True)

            log_item(SOURCE, "NEW", article_date, title, link)

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

        await browser.close()

    new_count = write_incremental_csv(all_csv=GLOBAL_ALL_CSV, new_csv=GLOBAL_NEW_CSV, rows=std_rows, append_new=True)
    log_summary(SOURCE, len(std_rows), new_count)

if __name__ == "__main__":
    asyncio.run(main())
