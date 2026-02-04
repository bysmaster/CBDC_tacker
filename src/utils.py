# -*- coding: utf-8 -*-
"""Common utilities for CBDC/central-bank scraping scripts.

Goals:
- Unified standard CSV schema
- Incremental append with UID dedupe
- Minimal dependencies (stdlib only)
- Standardized console output
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

# ==========================================
# Standard Fields Definition
# ==========================================

STANDARD_FIELDS: Sequence[str] = (
    "uid",
    "source",
    "entity",
    "category",
    "published_at",
    "title",
    "url",
    "abstract",
    "content",
    "content_type",
    "crawl_time",
    "is_relevant",
)

# ==========================================
# Global Paths
# ==========================================
# Unified data directory and CSV paths
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(exist_ok=True)

GLOBAL_ALL_CSV = DATA_DIR / "GLOBAL_standard_all.csv"
GLOBAL_NEW_CSV = DATA_DIR / "GLOBAL_standard_new.csv"

# ==========================================
# Time & Date Helpers
# ==========================================

def utc_now_str() -> str:
    """Return current UTC time as YYYY-MM-DD HH:MM:SS."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def get_lookback_date_range() -> Tuple[datetime, datetime]:
    """
    Return the start and end datetime for the lookback period.
    Default: Today (00:00:00) to Now, plus Yesterday (00:00:00 to 23:59:59).
    Effectively covers [Yesterday 00:00:00, Now].
    """
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    # User requested: "current day + previous day" (2 days total)
    return yesterday_start, now

# ==========================================
# Text & ID Helpers
# ==========================================

def make_uid(source: str, url: str) -> str:
    """Generate a consistent UID based on source and URL."""
    raw = f"{source}|{url}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def sanitize_text(text: object, *, one_line: bool = True) -> str:
    """Clean and normalize text content."""
    if text is None:
        return ""
    s = str(text)
    # Remove zero-width and similar unicode controls
    s = re.sub(r"[\u200b\u200c\u200d\u2028\u2029]+", " ", s)
    if one_line:
        s = re.sub(r"[\r\n\t]+", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
    else:
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        s = re.sub(r"\n\s*\n+", "\n\n", s).strip()
    return s

# ==========================================
# CSV & File Helpers
# ==========================================

def ensure_csv_field_size_limit() -> None:
    """Increase per-field CSV limit to support long `content` fields."""
    max_size = getattr(sys, "maxsize", 2**31 - 1)
    while max_size > 0:
        try:
            csv.field_size_limit(max_size)
            return
        except OverflowError:
            max_size = int(max_size / 10)

def _read_header(csv_path: Path) -> Optional[List[str]]:
    ensure_csv_field_size_limit()
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return None
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            return next(reader)
        except StopIteration:
            return None

def load_existing_keys(csv_path: Path) -> Tuple[Set[str], Set[str]]:
    """Return (uids, urls) from an existing CSV."""
    ensure_csv_field_size_limit()
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return set(), set()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return set(), set()

        fields = set(reader.fieldnames)
        has_uid = "uid" in fields
        url_field = "url" if "url" in fields else ("link" if "link" in fields else None)

        uids: Set[str] = set()
        urls: Set[str] = set()

        for row in reader:
            if has_uid:
                uid = (row.get("uid") or "").strip()
                if uid:
                    uids.add(uid)
            if url_field:
                url = (row.get(url_field) or "").strip()
                if url:
                    urls.add(url)
        return uids, urls

def write_incremental_csv(
    *,
    all_csv: Path,
    new_csv: Path,
    rows: List[Dict[str, str]],
    fields: Sequence[str] = STANDARD_FIELDS,
    dedupe_by: str = "uid",
    append_new: bool = False,
) -> int:
    """
    Write standard incremental output.
    - new_csv: 
        If append_new=False (default): overwritten each run with ONLY the new items from this run.
        If append_new=True: appended with the new items (useful when multiple scrapers write to same new_csv).
    - all_csv: appended with deduping (historical record)
    
    Returns number of NEW rows written.
    """
    ensure_csv_field_size_limit()
    all_csv = Path(all_csv)
    new_csv = Path(new_csv)

    # 1. Load existing keys to dedupe
    existing_uids, existing_urls = load_existing_keys(all_csv)

    # 2. Filter rows
    filtered: List[Dict[str, str]] = []
    for r in rows:
        # Ensure all standard fields exist, default to empty string
        # User requested preserving newlines for text fields.
        clean_row = {}
        for k in fields:
            val = r.get(k, "")
            # Preserve newlines for content/abstract/title, but sanitize others
            if k in ("content", "abstract", "title"):
                clean_row[k] = sanitize_text(val, one_line=False)
            else:
                clean_row[k] = sanitize_text(val, one_line=True)
        
        uid = clean_row.get("uid", "")
        url = clean_row.get("url", "")

        # Dedupe check
        if dedupe_by == "uid" and uid and uid in existing_uids:
            continue
        if dedupe_by == "url" and url and url in existing_urls:
            continue
        
        filtered.append(clean_row)
        if uid:
            existing_uids.add(uid)
        if url:
            existing_urls.add(url)

    if not filtered:
        return 0

    # 3. Write new_csv
    # If append_new is True, we append to new_csv, else we overwrite
    new_mode = "a" if append_new and new_csv.exists() and new_csv.stat().st_size > 0 else "w"
    
    # Check if we need header for new_csv
    new_need_header = True
    if new_mode == "a":
        # If appending, only write header if file is empty or doesn't exist (handled by new_mode logic mostly, but let's be safe)
        if new_csv.exists() and new_csv.stat().st_size > 0:
            new_need_header = False

    with new_csv.open(new_mode, encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fields), quoting=csv.QUOTE_ALL, extrasaction="ignore")
        if new_need_header:
            writer.writeheader()
        for r in filtered:
            writer.writerow(r)
            
    # Validate new_csv immediately
    validate_csv_format(new_csv, fields)

    # 4. Append to all_csv
    need_header = not all_csv.exists() or all_csv.stat().st_size == 0
    # Check if header matches if file exists
    if not need_header:
        header = _read_header(all_csv)
        if header and [h.strip() for h in header] != list(fields):
            # Header mismatch backup
            all_csv = all_csv.with_name(all_csv.stem + "_v2" + all_csv.suffix)
            need_header = not all_csv.exists() or all_csv.stat().st_size == 0

    mode = "a" if all_csv.exists() and not need_header else "w"
    with all_csv.open(mode, encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fields), quoting=csv.QUOTE_ALL, extrasaction="ignore")
        if need_header:
            writer.writeheader()
        for r in filtered:
            writer.writerow(r)
            
    # Validate all_csv immediately
    validate_csv_format(all_csv, fields)

    return len(filtered)

def validate_csv_format(csv_path: Path, expected_fields: Sequence[str]) -> bool:
    """
    Validate CSV format: check header and row lengths.
    Returns True if valid, False otherwise.
    """
    ensure_csv_field_size_limit()
    if not csv_path.exists():
        return False
        
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                # Empty file is valid if it was just created empty? Or invalid? 
                # Assuming empty file with no header is effectively invalid for data purposes, but valid CSV.
                return True
                
            if len(header) != len(expected_fields):
                print(f"❌ [CSV Validation] Header length mismatch in {csv_path.name}. Expected {len(expected_fields)}, got {len(header)}")
                return False
                
            line_num = 1
            for row in reader:
                line_num += 1
                if len(row) != len(expected_fields):
                    print(f"❌ [CSV Validation] Row {line_num} length mismatch in {csv_path.name}. Expected {len(expected_fields)}, got {len(row)}")
                    return False
        # print(f"✅ [CSV Validation] {csv_path.name} is valid.")
        return True
    except Exception as e:
        print(f"❌ [CSV Validation] Error reading {csv_path.name}: {e}")
        return False

# ==========================================
# Console Output Standard
# ==========================================

def log_item(module_name: str, status: str, published_at: str, title: str, link: str):
    """
    Standardized console log for a scraped item.
    Format: [Module] [Status] [Time] Title (Link)
    """
    # Truncate title if too long for console
    display_title = title if len(title) < 50 else title[:47] + "..."
    print(f"[{module_name}] [{status}] [{published_at}] {display_title} ({link})")

def log_summary(module_name: str, total_collected: int, new_count: int):
    """
    Standardized summary log at end of module run.
    """
    print(f"[{module_name}] [SUMMARY] Total Collected: {total_collected} | New Items: {new_count}")

def env_int(key: str, default: int = 0) -> int:
    val = os.getenv(key, "")
    try:
        return int(val)
    except ValueError:
        return default

def load_dotenv(dotenv_path: Optional[Path] = None) -> None:
    path = dotenv_path
    if path is None:
        path = Path(__file__).resolve().parents[1] / ".env"
    path = Path(path)
    if not path.exists():
        return

    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'").strip()
            if not key:
                continue
            if os.environ.get(key) is None:
                os.environ[key] = value
    except Exception:
        return

def to_chinese_numeral(n: int) -> str:
    """
    Convert integer to Chinese numeral (Simplified).
    Supports 1-99 for now as per requirements.
    """
    chars = ["〇", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
    units = ["", "十", "百"]
    
    if n <= 0:
        return str(n)
    if n < 10:
        return chars[n]
    if n < 20:
        return "十" + (chars[n % 10] if n % 10 != 0 else "")
    if n < 100:
        tens = n // 10
        rem = n % 10
        return chars[tens] + "十" + (chars[rem] if rem != 0 else "")
    
    return str(n) # Fallback for >= 100
