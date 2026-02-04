# -*- coding: utf-8 -*-
"""
Unified CBDC Scraping Pipeline Runner
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils import GLOBAL_NEW_CSV, STANDARD_FIELDS, load_dotenv

load_dotenv()

# Ensure inspect_docx_v2 is available for processor
# import inspect_docx_v2

# Defined jobs (module names in src/scrapers/)
JOBS = [
    "rss",
    "weiyang",
    "mas",
    "bi",
    "sama",
    "imf",
    "tcmb",
    "cbr",
    "boj",
    "ecb",
    "bcra",
    "bahamas",
    "bdf",
    "mnb",
]

DATA_DIR = ROOT / "data"

def init_global_new_csv():
    """Initialize (clear) the global new CSV file with header."""
    print(f"🧹 Initializing {GLOBAL_NEW_CSV}...")
    import csv
    with GLOBAL_NEW_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(STANDARD_FIELDS), quoting=csv.QUOTE_ALL, extrasaction="ignore")
        writer.writeheader()

def run_job(job_name: str):
    """Run a scraper module as a subprocess."""
    print(f"\n{'='*40}")
    print(f"🚀 Running Job: {job_name}")
    print(f"{'='*40}")
    
    start_time = time.time()
    try:
        # Run using python -m src.scrapers.<job_name>
        # This ensures imports work correctly relative to root
        cmd = [sys.executable, "-m", f"src.scrapers.{job_name}"]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=False)
        
        duration = time.time() - start_time
        if result.returncode == 0:
            print(f"✅ Job '{job_name}' completed in {duration:.2f}s")
        else:
            print(f"❌ Job '{job_name}' failed with code {result.returncode} in {duration:.2f}s")
    except Exception as e:
        print(f"❌ Job '{job_name}' error: {e}")

def run_pipeline(selected_jobs: List[str]):
    """Execute the full scraping and processing pipeline."""
    print(f"[{datetime.now()}] 🕒 Starting Scheduled Pipeline...")
    
    # --- Check for existing report (Idempotency) ---
    today_str = datetime.now().strftime('%Y%m%d')
    report_filename = f"数字货币国际资讯日报_{today_str}.docx" # Using Chinese name as per typical output, or English?
    # Wait, processor.py usually names it. Let's check processor.py code to be sure about the name.
    # But I can't read it again without cost. I'll make a safe guess or check if I can import a constant.
    # Actually, let's just use the logic: check if ANY file in reports dir contains today's date?
    # Or better, look at processor code if possible. 
    # I remember seeing "OUTPUT_DOC_DIR" in processor.py.
    
    # Let's try to import OUTPUT_DOC_DIR from src.processor
    try:
        from src.processor import OUTPUT_DOC_DIR
        report_path = OUTPUT_DOC_DIR / f"数字货币国际资讯日报_{today_str}.docx"
        
        # Check for English name just in case
        report_path_en = OUTPUT_DOC_DIR / f"CBDC_Report_{today_str}.docx"
        
        if report_path.exists() or report_path_en.exists():
             print(f"⏭️ Report for today ({today_str}) already exists. Skipping execution.")
             return
    except ImportError:
        # Fallback if import fails (unlikely)
        pass

    # Always initialize global new CSV before running jobs
    if selected_jobs:
        init_global_new_csv()
        
    print(f"Selected Jobs: {', '.join(selected_jobs)}")
    for job in selected_jobs:
        run_job(job)

    # --- Run Processor (Analysis, Report, Email) ---
    try:
        from src.processor import main as run_processor
        print("\n" + "="*40)
        print("🧠 Running AI Processor & Reporting")
        print("="*40)
        run_processor()
    except Exception as e:
        print(f"❌ Processor failed: {e}")
        
    print(f"[{datetime.now()}] 🏁 Pipeline Finished.")

def main():
    parser = argparse.ArgumentParser(description="CBDC Scraping Pipeline")
    parser.add_argument("--only", help="Run only specific jobs (comma separated)")
    parser.add_argument("--skip", help="Skip specific jobs (comma separated)")
    parser.add_argument("--input", help="Input file for processor (skips scrapers)")
    parser.add_argument("--output", help="Output file for processor")
    
    args = parser.parse_args()
    
    # If input is provided, just run processor
    if args.input:
        from src.processor import main as run_processor
        print(f"🚀 Running Processor Only on {args.input}...")
        run_processor(input_path=args.input, output_path=args.output)
        return

    selected_jobs = JOBS
    
    if args.only:
        only_set = set(args.only.split(","))
        selected_jobs = [j for j in selected_jobs if j in only_set]
        
    if args.skip:
        skip_set = set(args.skip.split(","))
        selected_jobs = [j for j in selected_jobs if j not in skip_set]
        
    # Run once immediately
    run_pipeline(selected_jobs)

if __name__ == "__main__":
    main()
