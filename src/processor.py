# -*- coding: utf-8 -*-
import pandas as pd
import time
import sys
import argparse
from pathlib import Path
from datetime import datetime

# Add project root to path if needed
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.utils import GLOBAL_NEW_CSV, GLOBAL_ALL_CSV, load_dotenv
from src.services.relevance_service import RelevanceService
from src.pipeline.post_process import generate_word_report, send_email_with_attachment

load_dotenv()

def main(input_path=None, output_path=None):
    print("🚀 Starting CBDC News Processor (Dual-Path)...")
    
    # 1. Load Data
    if input_path:
        input_file = Path(input_path)
    else:
        input_file = GLOBAL_NEW_CSV
        
    if not input_file.exists() or input_file.stat().st_size == 0:
        print(f"📭 No data found at {input_file}.")
        return

    try:
        if str(input_file).endswith('.json'):
            df = pd.read_json(input_file)
        else:
            df = pd.read_csv(input_file)
            
        # Initialize columns
        for col in ['is_relevant', 'zai_is_relevant', 'zai_reason', 'or_is_relevant', 'or_reason']:
            if col not in df.columns:
                df[col] = ""
    except Exception as e:
        print(f"❌ Error reading input file: {e}")
        return
        
    if df.empty:
        print("📭 No new rows in CSV.")
        return

    # 2. Initialize Service
    service = RelevanceService()
    
    processing_results = []
    relevant_articles = []
    alert_triggered = False
    alert_details = []
    
    print(f"🔍 Analyzing {len(df)} articles...")
    
    for index, row in df.iterrows():
        title = str(row.get('title', ''))
        abstract = str(row.get('abstract', ''))
        content = str(row.get('content', ''))
        url = str(row.get('url', ''))
        entity = str(row.get('entity', 'Source'))
        
        print(f"  Processing: {title[:50]}...")
        
        # Call Service
        try:
            result = service.assess_relevance(title, abstract, content)
        except Exception as e:
            print(f"  ❌ Service Error: {e}")
            result = {
                "is_relevant": "ERROR",
                "reasoning": f"Exception: {str(e)}",
                "confidence": 0.0,
                "details": {},
                "alert_needed": True
            }

        # Handle Result
        is_rel = result.get('is_relevant')
        confidence = result.get('confidence', 0.0)
        reason = result.get('reasoning', '')
        details = result.get('details', {})
        
        # Check for Alert
        if result.get('alert_needed'):
            alert_triggered = True
            alert_details.append(f"Title: {title}\nReason: {reason}")
        
        # Extract individual model results
        zai_det = details.get('zai', {})
        or_det = details.get('or', {})
        
        # Update DataFrame
        if is_rel is True:
            df.at[index, 'is_relevant'] = "TRUE"
            print(f"    ✅ RELEVANT ({confidence})")
            result['url'] = url
            result['entity'] = entity
            relevant_articles.append(result)
        elif is_rel == "ERROR":
            df.at[index, 'is_relevant'] = "ERROR"
            print(f"    ⚠️ ERROR: {reason}")
        else:
            df.at[index, 'is_relevant'] = "FALSE"
            print(f"    x Irrelevant")
        
        # Record detailed columns
        df.at[index, 'zai_is_relevant'] = str(zai_det.get('is_relevant'))
        df.at[index, 'zai_reason'] = str(zai_det.get('reason', ''))
        df.at[index, 'or_is_relevant'] = str(or_det.get('is_relevant'))
        df.at[index, 'or_reason'] = str(or_det.get('reason', ''))

        # Add to summary list
        processing_results.append({
            "title": title,
            "url": url,
            "is_relevant": is_rel,
            "reason": reason,
            "confidence": confidence,
            "zai_status": zai_det.get('status'),
            "or_status": or_det.get('status')
        })
        
        time.sleep(1) # Rate limit politeness

    # 3. Save Updated CSV/JSON
    try:
        save_path = Path(output_path) if output_path else input_file
        if str(save_path).endswith('.json'):
            df.to_json(save_path, orient='records', force_ascii=False, indent=4)
        else:
            df.to_csv(save_path, index=False, encoding='utf-8-sig')
        print(f"💾 Updated data saved to {save_path}.")
    except Exception as e:
        print(f"⚠️ Failed to update file: {e}")

    # 4. Update Global History CSV
    if not input_path and GLOBAL_ALL_CSV.exists():
        try:
            df_all = pd.read_csv(GLOBAL_ALL_CSV)
            # Ensure new columns exist in global history
            for col in ['is_relevant', 'zai_is_relevant', 'zai_reason', 'or_is_relevant', 'or_reason']:
                if col not in df_all.columns:
                    df_all[col] = ""
            
            if 'uid' in df.columns and 'uid' in df_all.columns:
                # Update map for all columns
                for col in ['is_relevant', 'zai_is_relevant', 'zai_reason', 'or_is_relevant', 'or_reason']:
                    status_map = dict(zip(df['uid'], df[col]))
                    df_all[col] = df_all['uid'].map(status_map).fillna(df_all[col])
                
                df_all.to_csv(GLOBAL_ALL_CSV, index=False, encoding='utf-8-sig')
                print("💾 Updated GLOBAL_standard_all.csv with detailed status.")
        except Exception as e:
             print(f"⚠️ Failed to update GLOBAL_ALL_CSV: {e}")

    # 5. Generate Email HTML
    html_table = """
    <table border="1" style="border-collapse: collapse; width: 100%; font-size: 12px;">
        <thead>
            <tr style="background-color: #f2f2f2;">
                <th>No.</th>
                <th>Title</th>
                <th>Status</th>
                <th>Z.AI</th>
                <th>OpenRouter</th>
            </tr>
        </thead>
        <tbody>
    """
    
    for i, res in enumerate(processing_results):
        status = res['is_relevant']
        if status is True:
            color = "green"
            text = "Relevant"
        elif status == "ERROR":
            color = "red"
            text = "ERROR"
        else:
            color = "gray"
            text = "Irrelevant"
            
        html_table += f"""
            <tr>
                <td>{i+1}</td>
                <td><a href="{res['url']}">{res['title']}</a></td>
                <td style="color: {color}; font-weight: bold;">{text}</td>
                <td>{res.get('zai_status')}</td>
                <td>{res.get('or_status')}</td>
            </tr>
        """
    html_table += "</tbody></table>"

    # 6. Generate Report Doc
    doc_path = None
    if relevant_articles:
        print(f"📝 Generating report with {len(relevant_articles)} articles...")
        try:
            doc_path = generate_word_report(relevant_articles, datetime.now().strftime("%Y-%m-%d"))
            print(f"📄 Report saved: {doc_path}")
        except Exception as e:
            print(f"❌ Failed to generate report: {e}")

    # 7. Send Email (Normal or Alert)
    print("📧 Sending email...")
    
    # Stats
    total_all_count = 0
    if GLOBAL_ALL_CSV.exists():
        try:
             with open(GLOBAL_ALL_CSV, 'r', encoding='utf-8') as f:
                 total_all_count = sum(1 for _ in f) - 1
        except:
             pass
    
    stats = {
        "total_all": total_all_count if total_all_count > 0 else 0,
        "total_new": len(df),
        "total_relevant": len(relevant_articles),
        "total_errors": sum(1 for r in processing_results if r['is_relevant'] == "ERROR")
    }

    # If alert triggered, modify subject or add warning
    if alert_triggered:
        print("⚠️ Sending ALERT email due to API failures.")
        # We can append alert details to HTML
        html_table = f"<h2>⚠️ API Critical Failure Alert</h2><pre>{chr(10).join(alert_details[:10])}</pre>" + html_table
    
    send_email_with_attachment(doc_path, csv_content_html=html_table, stats=stats)
    print("🏁 Done.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="Input file path")
    parser.add_argument("--output", help="Output file path")
    args = parser.parse_args()
    
    main(input_path=args.input, output_path=args.output)
