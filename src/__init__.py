"""
CBDC Project Source Package
Exposes key components for easier import.
"""

from .utils import (
    DATA_DIR,
    GLOBAL_NEW_CSV,
    STANDARD_FIELDS,
    utc_now_str,
    make_uid,
    sanitize_text,
    write_incremental_csv,
    log_item,
    log_summary
)

# Lazy import to avoid circular deps or heavy init if not needed immediately
# from .processor import AIProcessor
