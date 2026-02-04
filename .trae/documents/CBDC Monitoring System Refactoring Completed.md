# CBDC Monitoring System Refactoring Plan - Completed

## 1. Project Restructuring (Industrial-Grade)

* Created `src/` directory as the main package.

* Created `src/utils.py` containing unified logic for:

  * Standard CSV schema definition (`STANDARD_FIELDS`).

  * Text sanitization and UID generation.

  * Date calculation (`get_lookback_date_range`: Today + Yesterday).

  * Incremental CSV writing (`write_incremental_csv`).

  * Standardized logging (`log_item`, `log_summary`).

* Created `src/scrapers/` package to house all individual scraper modules.

* Created `src/main.py` as the unified entry point for running the pipeline.

* Moved all original flat scripts to `legacy/` folder for archival.

## 2. Scraper Migration

Migrated 14 individual scrapers to `src/scrapers/` with the following standardizations:

* **Imports**: Updated to use `src.utils`.

* **Date Logic**: Enforced strict lookback period (Current Day + Previous Day).

* **Output**: Writes to `data/{source}_standard_new.csv` and `data/{source}_standard_all.csv`.

* **Logging**: Replaced raw `print` with `log_item` (Module/Status/Time/Title/Link) and `log_summary`.

**Migrated Modules:**

1. `rss` (RSS Aggregator)
2. `weiyang` (WeiyangX)
3. `imf` (IMF News)
4. `ecb` (ECB Press)
5. `tcmb` (Turkey)
6. `cbr` (Russia)
7. `boj` (Japan)
8. `mas` (Singapore)
9. `bi` (Indonesia)
10. `sama` (Saudi Arabia)
11. `bcra` (Argentina)
12. `bahamas` (Bahamas)
13. `bdf` (France)
14. `mnb` (Hungary)

## 3. Unified Runner (`src/main.py`)

* Implemented a subprocess-based runner to execute scrapers in isolation.

* Supports arguments: `--only`, `--skip`, `--merge-only`.

* Implemented `merge_results()` to combine all `*_standard_new.csv` files into `data/GLOBAL_standard_new.csv` and `data/GLOBAL_standard_all.csv` at the end of the run.

## 4. Documentation

* Updated `docs/CBDC监测系统技术文档.md` to reflect the new architecture.

* Added sections for "Architecture Overview", "Running & Arguments", "Console Output Standard", and "Migration Details".

* Updated file references to point to the new `src/` locations.

## 5. Verification

* Verified directory structure (`src`, `src/scrapers`, `data`, `legacy`).

* Verified content of migrated files (e.g., `boj.py`, `cbr.py`) to ensure correct logic and no cross-contamination.

