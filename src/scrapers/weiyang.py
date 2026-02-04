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
BASE_URL = "https://www.weiyangx.com"
LIST_URL = BASE_URL + "/category/international"

RETRY_TIMES = 3
TIMEOUT = 120000

SOURCE = "weiyang"
ENTITY = "未央"
CATEGORY = "international"

# ==========================================

async def safe_goto(page, url, timeout=TIMEOUT, retries=RETRY_TIMES):
    for i in range(retries):
        try:
            # print(f"打开页面：{url}（尝试 {i + 1}/{retries}）")
            await page.goto(url, timeout=timeout, wait_until="networkidle")
            await page.wait_for_timeout(1500)
            return True
        except Exception as e:
            # print(f"⚠️ 第 {i + 1} 次尝试失败：{e}")
            await asyncio.sleep(3)
    return False

def parse_date_text(date_raw: str) -> str:
    now = datetime.now()
    if not date_raw:
        return now.strftime("%Y-%m-%d")
    date_raw = date_raw.strip()

    m = re.search(r"(\d+)\s*天前", date_raw)
    if m:
        d = now - timedelta(days=int(m.group(1)))
        return d.strftime("%Y-%m-%d")

    m = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", date_raw)
    if m:
        y, mm, dd = m.groups()
        return f"{int(y):04d}-{int(mm):02d}-{int(dd):02d}"

    m = re.search(r"(\d{1,2})[./-](\d{1,2})$", date_raw)
    if m:
        mm, dd = m.groups()
        return f"{now.year:04d}-{int(mm):02d}-{int(dd):02d}"

    return now.strftime("%Y-%m-%d")

async def fetch_detail_content(page, link: str):
    for attempt in range(RETRY_TIMES):
        try:
            await page.goto(link, timeout=TIMEOUT, wait_until="networkidle")
            await page.wait_for_timeout(1500)

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            date_tag = soup.select_one(".uk-margin-remove.uk-text-small span")
            date_text = date_tag.get_text(strip=True) if date_tag else ""
            date_final = parse_date_text(date_text)

            content_div = soup.select_one(".wyt-single-output")
            content_text = ""
            if content_div:
                for bad in content_div.select("div[uk-grid], .wyt-single-author, .wyt-single-tag, p[class*='uk-text-small']"):
                    bad.decompose()

                paragraphs = []
                for p in content_div.find_all(["p", "h2", "h3"]):
                    t = p.get_text(strip=True)
                    if t and not re.match(r"(本文共\d+字|预计阅读时间)", t):
                        paragraphs.append(t)
                content_text = "\n".join(paragraphs)

            return date_final, sanitize_text(content_text, one_line=True)
        except Exception as e:
            await asyncio.sleep(2)

    return "", ""

async def main():
    start_dt, end_dt = get_lookback_date_range()
    min_date_str = start_dt.strftime("%Y-%m-%d")
    
    results = []
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
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            posts = soup.select(".wyt-tag-post")
            if not posts:
                break

            new_added = 0
            for post in posts:
                if count >= MAX_ARTICLES or stop_early:
                    break

                link_tag = post.select_one("a")
                if not link_tag:
                    continue
                link = (link_tag.get("href", "") or "").strip()
                if not link.startswith("http"):
                    link = BASE_URL + link

                if not link or link in visited_links:
                    continue

                date_raw_tag = post.select_one(".wyt-tag-post-info-meta span:first-child")
                date_raw = date_raw_tag.get_text(strip=True) if date_raw_tag else ""
                article_date_list = parse_date_text(date_raw)

                # STRICT DATE CHECK
                if article_date_list < min_date_str:
                    stop_early = True
                    break

                title_tag = post.select_one("h4")
                title = title_tag.get_text(strip=True) if title_tag else ""
                abs_tag = post.select_one(".wyt-tag-post-info-brief")
                list_abstract = abs_tag.get_text(" ", strip=True) if abs_tag else ""

                detail_page = await context.new_page()
                article_date_detail, content_text = await fetch_detail_content(detail_page, link)
                await detail_page.close()

                final_date = article_date_detail or article_date_list
                if final_date < min_date_str:
                    # If detail date is older, skip and stop if strictly ordered
                    # Assuming list date is reliable for stopping
                    pass

                if not content_text:
                    content_text = sanitize_text(list_abstract, one_line=True)

                row = {
                    "uid": make_uid(SOURCE, link),
                    "source": SOURCE,
                    "entity": ENTITY,
                    "category": CATEGORY,
                    "published_at": sanitize_text(final_date, one_line=True),
                    "title": sanitize_text(title, one_line=True),
                    "url": sanitize_text(link, one_line=True),
                    "abstract": sanitize_text(list_abstract, one_line=True),
                    "content": sanitize_text(content_text, one_line=True),
                    "content_type": "html",
                    "crawl_time": utc_now_str(),
                }

                results.append(row)
                visited_links.add(link)
                count += 1
                new_added += 1
                
                log_item(SOURCE, "NEW", final_date, title, link)

            if stop_early or new_added == 0:
                break

            try:
                load_more = await page.query_selector("a.wyt-loadmore")
                if load_more and await load_more.is_visible():
                    await load_more.click()
                    await page.wait_for_timeout(3500)
                else:
                    break
            except Exception:
                break

        await browser.close()

    new_count = write_incremental_csv(all_csv=GLOBAL_ALL_CSV, new_csv=GLOBAL_NEW_CSV, rows=results, append_new=True)
    log_summary(SOURCE, len(results), new_count)

if __name__ == "__main__":
    asyncio.run(main())
