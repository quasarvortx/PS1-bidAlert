"""
eprocure.gov.in Tender Scraper
================================
Scrapes open tenders from eprocure.gov.in (Central Public Procurement Portal)
and generates DIRECT document download links — no captcha, no manual click.

How it works:
  - Opens a real Chrome browser (Selenium) to bypass bot protection
  - Navigates to advanced search, sets date range + "Open" status
  - Extracts tender list with metadata
  - Constructs direct document download URLs using the known URL pattern
  - Saves results to Excel sorted by closing date

Usage:
  python eprocure_scraper.py --from_date 01/01/2024 --to_date 31/03/2025
"""

import time
import re
import argparse
import logging
from urllib.parse import urljoin
from datetime import datetime
from pathlib import Path


import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, StaleElementReferenceException
)

# ─────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# Constants — eprocure URL patterns
# ─────────────────────────────────────────────────────────────────
BASE_URL = "https://eprocure.gov.in/eprocure/app"

# Tender detail page: ?component=...&page=FrontEndTenderCorrigendum&service=page&id=<TENDER_ID>
DETAIL_URL = (
    BASE_URL
    + "?component=%24DirectLink_0&page=FrontEndTenderCorrigendum"
    + "&service=page&id={tender_id}"
)

# NIT (Notice Inviting Tender) document — the primary tender document
# Pattern confirmed from site inspection: /downloadNIT?FileType=...&Id=<DOC_ID>
NIT_DOWNLOAD_URL = (
    "https://eprocure.gov.in/eprocure/app"
    "?component=%24DirectLink&page=FrontEndDownloadNIT"
    "&service=page&id={nit_id}"
)

# BOQ (Bill of Quantities) document download
BOQ_DOWNLOAD_URL = (
    "https://eprocure.gov.in/eprocure/app"
    "?component=%24DirectLink&page=FrontEndDownloadBoq"
    "&service=page&id={boq_id}"
)

# Pre-bid documents
PREBID_DOWNLOAD_URL = (
    "https://eprocure.gov.in/eprocure/app"
    "?component=%24DirectLink&page=FrontEndDownloadPrebid"
    "&service=page&id={prebid_id}"
)

# Search result page
SEARCH_URL = (
    BASE_URL
    + "?page=FrontEndAdvancedSearch&service=page"
)

WAIT = 15  # seconds


# ─────────────────────────────────────────────────────────────────
# Browser setup
# ─────────────────────────────────────────────────────────────────
def make_driver(headless: bool = False) -> webdriver.Chrome:
    """Create a Chrome WebDriver. Set headless=True for server environments."""
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    # Automatic download settings — files go to ./downloads/
    download_dir = str(Path("downloads").resolve())
    Path(download_dir).mkdir(exist_ok=True)
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True,
    }
    opts.add_experimental_option("prefs", prefs)
    driver = webdriver.Chrome(options=opts)
    # Remove navigator.webdriver flag
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
    )
    return driver


def wait_for(driver, by, selector, timeout=WAIT):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by, selector))
    )


def safe_text(el) -> str:
    try:
        return el.text.strip()
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────
# Step 1 — Search for open tenders by date range
# ─────────────────────────────────────────────────────────────────
def search_open_tenders(driver, from_date: str, to_date: str) -> list[dict]:
    """
    Manual-captcha mode.

    eprocure advanced search currently requires captcha.
    So Selenium opens the page, you manually fill the form + captcha,
    click Search, then press Enter in terminal. After that the script
    scrapes the result table.
    """
    log.info("Opening eprocure.gov.in advanced search page...")
    driver.get(SEARCH_URL)
    time.sleep(3)

    print("\n" + "=" * 70)
    print("MANUAL STEP REQUIRED")
    print("=" * 70)
    print("In the Chrome window:")
    print("1. Select Tender Type = Open Tender")
    print("2. Select Date Criteria = Published Date")
    print(f"3. Enter From Date = {from_date}")
    print(f"4. Enter To Date   = {to_date}")
    print("5. Enter captcha")
    print("6. Click Search")
    print("7. Wait until results table is visible")
    print("=" * 70)
    input("After clicking Search and seeing results, press ENTER here... ")

    all_tenders = []
    page_num = 1

    while True:
        log.info(f"Scraping page {page_num}...")
        tenders = extract_tender_rows(driver)
        all_tenders.extend(tenders)
        log.info(f"  Found {len(tenders)} tenders on page {page_num}")

        # TEST MODE: only collect first 10 tenders
        if len(all_tenders) >= 10:
            log.info("Test mode: collected 10 tenders, stopping search.")
            return all_tenders[:10]

        if not tenders:
            log.warning("No tenders parsed on this page. Stopping pagination.")
            log.warning("Saved debug HTML to debug/eprocure_current_page.html")
            break

        try:
            next_btn = driver.find_element(
                By.XPATH,
                "//a[contains(text(),'Next') or contains(text(),'>')]"
            )

            cls = next_btn.get_attribute("class") or ""
            if "disabled" in cls.lower():
                break

            next_btn.click()
            time.sleep(3)
            page_num += 1

        except NoSuchElementException:
            log.info("No more pages.")
            break
        except Exception as e:
            log.warning(f"Pagination stopped: {e}")
            break

    log.info(f"Total tenders collected: {len(all_tenders)}")
    return all_tenders


# ─────────────────────────────────────────────────────────────────
# Step 2 — Parse tender table rows
# ─────────────────────────────────────────────────────────────────
def extract_tender_rows(driver) -> list[dict]:
    """
    Parser for current eprocure result table.

    Current table:
      <table id="table" class="list_table">
    Columns:
      0 S.No
      1 e-Published Date
      2 Closing Date
      3 Opening Date
      4 Title and Ref.No./Tender ID
      5 Organisation Chain
    """
    rows = []

    try:
        Path("debug").mkdir(exist_ok=True)
        Path("debug/eprocure_current_page.html").write_text(
            driver.page_source,
            encoding="utf-8",
            errors="ignore"
        )
    except Exception:
        pass

    try:
        table = driver.find_element(By.ID, "table")
        log.info("Found result table using id='table'")
    except NoSuchElementException:
        try:
            table = driver.find_element(By.CSS_SELECTOR, "table.list_table")
            log.info("Found result table using class='list_table'")
        except NoSuchElementException:
            log.warning("Result table not found. Saved debug/eprocure_current_page.html")
            return rows

    trs = table.find_elements(By.XPATH, ".//tr[td]")
    log.info(f"Candidate result rows found: {len(trs)}")

    for tr in trs:
        try:
            tds = tr.find_elements(By.TAG_NAME, "td")

            # real tender rows have 6 columns
            if len(tds) < 6:
                continue

            serial = safe_text(tds[0]).replace(".", "").strip()
            pub_date = safe_text(tds[1])
            close_date = safe_text(tds[2])
            open_date = safe_text(tds[3])
            title_cell = tds[4]
            org = safe_text(tds[5])

            # skip header/footer rows
            if not serial.isdigit():
                continue

            # detail link + title
            detail_href = ""
            title = ""

            a_tags = title_cell.find_elements(By.TAG_NAME, "a")
            if a_tags:
                a = a_tags[0]
                detail_href = a.get_attribute("href") or ""
                title = safe_text(a)

            # fallback title
            title_full_text = safe_text(title_cell)
            if not title:
                title = title_full_text

            # clean title: [abc] -> abc
            title = title.strip()
            if title.startswith("[") and "]" in title:
                title = title[1:title.index("]")].strip()

            # Extract [ref][tender_id] after title
            bracket_values = re.findall(r"\[([^\]]+)\]", title_full_text)

            tender_ref = ""
            tender_id_text = ""

            if len(bracket_values) >= 2:
                tender_ref = bracket_values[-2].strip()
                tender_id_text = bracket_values[-1].strip()
            elif len(bracket_values) == 1:
                tender_id_text = bracket_values[0].strip()

            # Extract raw sp token from URL. Current eprocure uses sp= not id=
            tender_id_raw = ""

            m = re.search(r"[?&]sp=([^&]+)", detail_href)
            if m:
                tender_id_raw = m.group(1)

            # Absolute URL fallback
            if detail_href.startswith("/"):
                detail_href = "https://eprocure.gov.in" + detail_href

            rows.append({
                "S.No": serial,
                "Published Date": pub_date,
                "Closing Date": close_date,
                "Opening Date": open_date,
                "Organisation": org,
                "Tender Title": title,
                "Tender Ref No": tender_ref,
                "Tender ID (raw)": tender_id_raw or tender_id_text,
                "Tender ID": tender_id_text,
                "Detail Page URL": detail_href,
            })

        except StaleElementReferenceException:
            continue
        except Exception as e:
            log.warning(f"Row parse skipped: {e}")
            continue

    log.info(f"Parsed tender rows: {len(rows)}")
    return rows


# ─────────────────────────────────────────────────────────────────
# Step 3 — Visit each tender detail page and get document links
# ─────────────────────────────────────────────────────────────────
def _extract_real_url_from_anchor(a) -> str:
    """
    Extract real URL from normal href or javascript popup/onClick.
    eprocure sometimes keeps document links inside href or onclick.
    """
    href = a.get_attribute("href") or ""
    onclick = a.get_attribute("onclick") or ""

    candidates = [href, onclick]

    for raw in candidates:
        if not raw:
            continue

        # Direct normal URL
        if raw.startswith("http") or raw.startswith("/"):
            return urljoin("https://eprocure.gov.in", raw)

        # JavaScript popup('/eprocure/app?...') style
        m = re.search(r"['\"]([^'\"]*eprocure/app[^'\"]+)['\"]", raw)
        if m:
            return urljoin("https://eprocure.gov.in", m.group(1))

        # Relative app URL inside JS
        m = re.search(r"['\"](/eprocure/app[^'\"]+)['\"]", raw)
        if m:
            return urljoin("https://eprocure.gov.in", m.group(1))

    return ""


def _is_navigation_link(url: str) -> bool:
    """Reject left-menu/header/footer links."""
    u = (url or "").lower()
    bad_pages = [
        "webawards",
        "frontendadvancedsearch",
        "frontendlatestactivetenders",
        "frontendlisttendersbydate",
        "resultoftenders",
        "frontendcontactus",
        "sitemap",
        "webscreenreaderaccess",
        "frontendtendersbylocation",
        "frontendtendersbyorganisation",
        "frontendtendersbyclassification",
        "frontendtendersinarchive",
        "webtenderstatuslists",
        "webcancelledtenderlists",
        "standardbiddingdocuments",
        "frontenddebarmentlist",
        "webannouncements",
        "sitecomp",
        "home",
    ]
    return any(p in u for p in bad_pages)


def get_document_links(driver, tender: dict) -> dict:
    """
    Open tender detail page and extract NIT/BOQ/work-item document links.

    Important:
    eprocure document links may be session-based.
    They work after captcha is solved in the same browser session.
    """
    result = {
        "NIT Download Link": "",
        "BOQ Download Link": "",
        "Other Doc Links": "",
        "Closing Date (from doc)": "",
    }

    detail_url = tender.get("Detail Page URL", "")
    if not detail_url:
        log.warning(f"No detail URL for tender: {tender.get('Tender Title', '?')}")
        return result

    try:
        log.info(f"  Fetching detail: {detail_url[:100]}...")
        driver.get(detail_url)
        time.sleep(3)

        # If eprocure asks captcha on document/detail page, solve manually once.
        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text
            if "captcha" in body_text.lower() and "Tenders Documents" not in body_text:
                print("\nDocument page captcha detected.")
                print("Solve captcha in Chrome, continue until document table is visible.")
                input("After document table is visible, press ENTER here... ")
                time.sleep(2)
        except Exception:
            pass

        page_text = driver.find_element(By.TAG_NAME, "body").text

        nit_links = []
        boq_links = []
        other_links = []
        zip_links = []

        # Parse all rows from detail page document tables
        all_rows = driver.find_elements(By.XPATH, "//tr[td]")

        current_section = ""

        for tr in all_rows:
            row_text = safe_text(tr)
            row_text_l = row_text.lower()

            if not row_text.strip():
                continue

            if "nit document" in row_text_l:
                current_section = "NIT"

            if "work item documents" in row_text_l:
                current_section = "WORK"

            anchors = tr.find_elements(By.TAG_NAME, "a")
            row_urls = []

            for a in anchors:
                url = _extract_real_url_from_anchor(a)
                text = safe_text(a).lower()

                if not url:
                    continue

                if _is_navigation_link(url):
                    continue

                # Keep only possible document/download URLs
                url_l = url.lower()
                if (
                    "download" in url_l
                    or "download" in text
                    or "document" in url_l
                    or ".pdf" in text
                    or ".xls" in text
                    or ".xlsx" in text
                    or ".zip" in text
                    or "frontendretrievedocument" in url_l
                    or "frontenddownload" in url_l
                ):
                    row_urls.append(url)

            if not row_urls:
                continue

            # De-duplicate row URLs
            row_urls = list(dict.fromkeys(row_urls))
            first_url = row_urls[0]

            # Classify by section and row text
            if current_section == "NIT" or "tendernotice" in row_text_l or "nit document" in row_text_l:
                nit_links.append(first_url)

            elif "boq" in row_text_l:
                boq_links.append(first_url)

            elif "download as zip" in row_text_l or "zip" in row_text_l:
                zip_links.append(first_url)

            else:
                other_links.extend(row_urls)

        # fallback: scan all anchors if table logic misses something
        if not nit_links and not boq_links:
            for a in driver.find_elements(By.TAG_NAME, "a"):
                url = _extract_real_url_from_anchor(a)
                text = safe_text(a).lower()

                if not url or _is_navigation_link(url):
                    continue

                if "tendernotice" in text or re.search(r"\bnit\b", text):
                    nit_links.append(url)
                elif "boq" in text:
                    boq_links.append(url)
                elif "download" in url.lower() or "document" in url.lower():
                    other_links.append(url)

        nit_links = list(dict.fromkeys(nit_links))
        boq_links = list(dict.fromkeys(boq_links))
        other_links = list(dict.fromkeys(other_links))
        zip_links = list(dict.fromkeys(zip_links))

        result["NIT Download Link"] = nit_links[0] if nit_links else ""
        result["BOQ Download Link"] = boq_links[0] if boq_links else ""

        combined_other = []
        combined_other.extend(zip_links)
        combined_other.extend(other_links)

        result["Other Doc Links"] = " | ".join(list(dict.fromkeys(combined_other))[:10])

        # Extract closing date from detail page text, not PDF
        m = re.search(
            r"(?:Bid Submission Closing Date|Closing Date)[^\d]*(\d{2}[-/][A-Za-z0-9]{2,3}[-/]\d{4}(?:\s+\d{1,2}:\d{2}\s*(?:AM|PM)?)?)",
            page_text,
            re.IGNORECASE
        )
        if m:
            result["Closing Date (from doc)"] = m.group(1)

        log.info(f"    NIT found: {'YES' if result['NIT Download Link'] else 'NO'}")
        log.info(f"    BOQ found: {'YES' if result['BOQ Download Link'] else 'NO'}")
        log.info(f"    Other links: {len(combined_other)}")

    except Exception as e:
        log.error(f"  Error fetching/parsing detail page: {e}")

    return result


# ─────────────────────────────────────────────────────────────────
# Step 4 — Construct direct download links (URL-pattern approach)
# ─────────────────────────────────────────────────────────────────
def build_direct_link(tender_id: str, doc_type: str = "NIT") -> str:
    """
    Build a direct document download link from the tender ID.
    
    eprocure URL pattern (confirmed from live site inspection):
    
    NIT:   https://eprocure.gov.in/eprocure/app
           ?component=%24DirectLink&page=FrontEndDownloadNIT&service=page&id=<TENDER_ID>
    
    BOQ:   https://eprocure.gov.in/eprocure/app
           ?component=%24DirectLink&page=FrontEndDownloadBoq&service=page&id=<TENDER_ID>
    
    Note: The TENDER_ID here is the same id= parameter from the detail page URL.
    In some tenders the NIT document has its own separate ID; in that case
    this function generates the correct URL once you have extracted the NIT ID
    from the detail page via get_document_links().
    """
    if doc_type.upper() == "NIT":
        return NIT_DOWNLOAD_URL.format(nit_id=tender_id)
    elif doc_type.upper() == "BOQ":
        return BOQ_DOWNLOAD_URL.format(boq_id=tender_id)
    else:
        return PREBID_DOWNLOAD_URL.format(prebid_id=tender_id)


# ─────────────────────────────────────────────────────────────────
# Step 5 — Combine everything and export to Excel
# ─────────────────────────────────────────────────────────────────
def parse_date(date_str: str):
    """Parse DD-MM-YYYY or DD/MM/YYYY into datetime for sorting."""
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return datetime.max  # push unparseable dates to bottom


def run(from_date: str, to_date: str, headless: bool = False, output: str = "tenders_output.xlsx"):
    driver = make_driver(headless=headless)

    try:
        # ── Phase 1: Collect tender list ─────────────────────────
        tenders = search_open_tenders(driver, from_date, to_date)

        if not tenders:
            log.warning("No tenders found. Check date range or site structure.")
            return

        # ── Phase 2: Get document links for each tender ──────────
        log.info(f"\nFetching document links for {len(tenders)} tenders...")
        for i, t in enumerate(tenders):
            log.info(f"[{i+1}/{len(tenders)}] {t.get('Tender Title','')[:60]}")
            doc_info = get_document_links(driver, t)
            t.update(doc_info)
            time.sleep(1)  # polite delay

        # ── Phase 3: Build final dataframe ───────────────────────
        df = pd.DataFrame(tenders)

        # Generate direct links for tenders where we have an ID but no NIT link
        # for idx, row in df.iterrows():
        #     if not row.get("NIT Download Link") and row.get("Tender ID (raw)"):
        #         df.at[idx, "NIT Download Link"] = build_direct_link(
        #             row["Tender ID (raw)"], "NIT"
        #         )

        # Sort by closing date
        df["_close_sort"] = df["Closing Date"].apply(parse_date)
        df = df.sort_values("_close_sort").drop(columns=["_close_sort"])

        # Reorder columns for readability
        col_order = [
            "Closing Date",
            "Published Date",
            "Organisation",
            "Tender Title",
            "Tender Ref No",
            "NIT Download Link",
            "BOQ Download Link",
            "Other Doc Links",
            "Closing Date (from doc)",
            "Opening Date",
            "Detail Page URL",
            "Tender ID (raw)",
            "S.No",
        ]
        existing = [c for c in col_order if c in df.columns]
        extra    = [c for c in df.columns if c not in col_order]
        df = df[existing + extra]

        # ── Phase 4: Export ──────────────────────────────────────
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Open Tenders")

            ws = writer.sheets["Open Tenders"]
            # Auto-width columns
            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 60)

            # Make link columns clickable (NIT + BOQ)
            for col_name in ["NIT Download Link", "BOQ Download Link", "Detail Page URL"]:
                if col_name in df.columns:
                    col_idx = df.columns.get_loc(col_name) + 1
                    for row_idx, url in enumerate(df[col_name], start=2):
                        if url:
                            cell = ws.cell(row=row_idx, column=col_idx)
                            cell.hyperlink = url
                            cell.style = "Hyperlink"

        log.info(f"\n✓ Done! Saved {len(df)} tenders to: {output}")
        return df

    finally:
        driver.quit()


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape open tenders from eprocure.gov.in with document download links"
    )
    parser.add_argument("--from_date", default="01/01/2024", help="Start date DD/MM/YYYY")
    parser.add_argument("--to_date",   default="31/12/2024", help="End date DD/MM/YYYY")
    parser.add_argument("--headless",  action="store_true",   help="Run browser in headless mode")
    parser.add_argument("--output",    default="tenders_output.xlsx", help="Output Excel file path")
    args = parser.parse_args()

    run(
        from_date=args.from_date,
        to_date=args.to_date,
        headless=args.headless,
        output=args.output,
    )
