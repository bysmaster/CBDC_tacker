# -*- coding: utf-8 -*-
import os
import smtplib
from datetime import datetime
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from src.utils import to_chinese_numeral

# Configuration for Email
EMAIL_HOST = "smtp.qq.com"
EMAIL_PORT = 465
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
EMAIL_TO = os.environ.get("EMAIL_TO")

ROOT_DIR = Path(__file__).resolve().parents[2] # src/pipeline/ -> src/ -> root
DATA_DIR = ROOT_DIR / "data"
TEMPLATE_PATH = ROOT_DIR / "memo" / "模板.docx"
OUTPUT_DOC_DIR = DATA_DIR / "reports"
OUTPUT_DOC_DIR.mkdir(exist_ok=True, parents=True)

def inspect_template_paragraphs(docx_path: str) -> List[str]:
    """Return a list of text from all paragraphs in the document."""
    try:
        doc = Document(docx_path)
        return [p.text for p in doc.paragraphs]
    except Exception as e:
        print(f"Error reading docx: {e}")
        return []

def validate_template_integrity(docx_path: str) -> Tuple[bool, str]:
    path = Path(docx_path)
    if not path.exists():
        return False, f"Template file not found: {docx_path}"

    paragraphs = inspect_template_paragraphs(str(path))
    
    required_markers = [
        "新疆维吾尔自治区分行",
        "编译："
    ]
    
    missing = []
    for marker in required_markers:
        if not any(marker in p_text for p_text in paragraphs):
            missing.append(marker)
            
    if missing:
        return False, f"Missing critical markers in template: {missing}"
        
    return True, "Template is valid."

def set_run_font(run, font_name, size_pt, bold=False):
    run.font.name = font_name
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    r = run._element
    rPr = r.get_or_add_rPr()
    fonts = rPr.get_or_add_rFonts()
    fonts.set(qn('w:eastAsia'), font_name)
    fonts.set(qn('w:ascii'), font_name)
    fonts.set(qn('w:hAnsi'), font_name)
    fonts.set(qn('w:cs'), font_name)

def generate_word_report(articles: List[Dict], date_str: str) -> Path:
    # Handle "ERROR" entries in articles list if any slipped through
    # Filter only truly relevant ones
    valid_articles = [a for a in articles if a.get('is_relevant') is True]
    
    if not valid_articles:
        print("⚠️ No valid articles to report.")
        return None

    is_valid, val_msg = validate_template_integrity(str(TEMPLATE_PATH))
    if not is_valid:
        raise ValueError(f"Template validation failed: {val_msg}")
    
    doc = Document(TEMPLATE_PATH)
    
    def format_paragraph_text(paragraph, text, font_name, size_pt, bold=False, align=None):
        paragraph.clear()
        run = paragraph.add_run(text)
        set_run_font(run, font_name, size_pt, bold)
        if align is not None:
            paragraph.alignment = align
        return run

    target_font_fs = "FangSong_GB2312"
    target_font_hei = "SimHei"
    
    # 1. Set Date
    for p in doc.paragraphs:
        if "2026年" in p.text and "月" in p.text:
            dt = datetime.now()
            parts = p.text.split("2026年")
            prefix = parts[0] if parts else "新疆维吾尔自治区分行········································"
            new_date_str = f"{dt.year}年{dt.month}月{dt.day}日"
            full_text = prefix + new_date_str
            format_paragraph_text(p, full_text, target_font_fs, 16)
            break
            
    # 2. Identify Sections
    date_idx = -1
    footer_idx = -1
    
    for i, p in enumerate(doc.paragraphs):
        if "新疆维吾尔自治区分行" in p.text:
            date_idx = i
        elif "编译：" in p.text:
            footer_idx = i
            break
            
    if date_idx != -1 and footer_idx != -1 and footer_idx > date_idx:
        # Clear content
        to_remove = []
        for i in range(date_idx + 1, footer_idx):
            to_remove.append(doc.paragraphs[i])
        for p in to_remove:
            p.clear()
            if p._element.getparent() is not None:
                p._element.getparent().remove(p._element)

        # Find footer again
        ref_p = None
        for p in doc.paragraphs:
            if "编译：" in p.text:
                ref_p = p
                break
        
        if ref_p:
            for i, art in enumerate(valid_articles):
                num_str = to_chinese_numeral(i + 1)
                
                # Title
                p_title = ref_p.insert_paragraph_before()
                title_text = f"{num_str}、{art['title_cn']}"
                format_paragraph_text(p_title, title_text, target_font_hei, 16, bold=True)
                p_title.paragraph_format.space_before = Pt(12)
                p_title.paragraph_format.space_after = Pt(6)
                
                # Content
                p_content = ref_p.insert_paragraph_before()
                format_paragraph_text(p_content, art['summary'], target_font_fs, 16)
                p_content.paragraph_format.first_line_indent = Pt(32)
                p_content.paragraph_format.line_spacing = 1.5
                p_content.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                
                # Source
                source_text = f"（{art.get('entity', 'Source')}：{art.get('url', '')}）"
                p_source = ref_p.insert_paragraph_before()
                format_paragraph_text(p_source, source_text, target_font_fs, 16, align=WD_ALIGN_PARAGRAPH.LEFT)
                p_source.paragraph_format.left_indent = Pt(0)
                p_source.paragraph_format.first_line_indent = Pt(0)
                p_source.paragraph_format.space_after = Pt(12)

            if "编译：" in ref_p.text:
                format_paragraph_text(ref_p, ref_p.text, target_font_fs, 16)
            for p in doc.paragraphs:
                if "编审：" in p.text:
                    format_paragraph_text(p, p.text, target_font_fs, 16)
    
    filename = f"CBDC_Report_{datetime.now().strftime('%Y%m%d')}.docx"
    out_path = OUTPUT_DOC_DIR / filename
    doc.save(out_path)
    return out_path

def send_email_with_attachment(filepath: Path, csv_content_html: str = "", stats: Dict = None):
    if not all([EMAIL_USER, EMAIL_PASS, EMAIL_TO]):
        print("⚠️ Email credentials missing. Skipping email.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_TO
    msg['Subject'] = Header(f"数字货币国际资讯日报 - {datetime.now().strftime('%Y-%m-%d')}", 'utf-8')
    
    body_str = "<p>附件为今日数字货币国际资讯日报，请查收。</p>"
    
    if stats:
        body_str += f"""
        <h3>=== 今日数据统计 ===</h3>
        <ul>
            <li>历史总条数 (All): {stats.get('total_all', 0)}</li>
            <li>今日新增条数 (New): {stats.get('total_new', 0)}</li>
            <li>CBDC相关条数 (Relevant): {stats.get('total_relevant', 0)}</li>
            <li>异常条数 (Errors): {stats.get('total_errors', 0)}</li>
        </ul>
        """
        
    if csv_content_html:
        body_str += "<h3>=== 今日新增资讯列表 ===</h3>"
        body_str += csv_content_html
        
    body = MIMEText(body_str, 'html', 'utf-8')
    msg.attach(body)
    
    if filepath and filepath.exists():
        with open(filepath, 'rb') as f:
            part = MIMEApplication(f.read(), Name=filepath.name)
            part['Content-Disposition'] = f'attachment; filename="{filepath.name}"'
            msg.attach(part)
        
    try:
        server = smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT)
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_TO, msg.as_string())
        server.quit()
        print(f"✅ Email sent successfully to {EMAIL_TO}")
    except Exception as e:
        print(f"❌ Email failed: {e}")
