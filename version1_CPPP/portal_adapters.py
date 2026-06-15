"""
Multi-Portal Tender Scraper — State Procurement Portals
=========================================================
Base class + adapters for the 32 procurement portals.

Each portal adapter defines:
  - how to search for open tenders by date
  - how to extract the direct document download URL (THE CRITICAL PART)

For most state portals, the document URL pattern is consistent and
can be derived WITHOUT downloading or solving captchas.

Adapters included:
  1.  eprocure.gov.in         (Central)
  2.  gem.gov.in / bidplus    (GeM)
  3.  mahatenders.gov.in      (Maharashtra)
  4.  etenders.kerala.gov.in  (Kerala)
  5.  tender.apeprocurement.gov.in (Andhra Pradesh)
  6.  tenderwizard.com/UPSIC  (Uttar Pradesh UPSIC)
  7.  etender.up.nic.in       (UP NIC)
  8.  hptenders.gov.in        (Himachal Pradesh)
  9.  tenderstn.gov.in        (Tamil Nadu)
  10. etenders.rajasthan.gov.in (Rajasthan)
  ... (extend by subclassing PortalAdapter)

Usage:
  from portal_adapters import GeM, Eprocure, MahaTenders
  
  # Get direct document link from a tender ID
  link = GeM.doc_link("9032455")
  # → https://bidplus.gem.gov.in/showbidDocument/9032455

  link = Eprocure.doc_link("AbCdEfGh1234==")
  # → https://eprocure.gov.in/eprocure/app?...&id=AbCdEfGh1234==
"""

from __future__ import annotations
import time
import re
import logging
from urllib.parse import urlencode, quote
from dataclasses import dataclass, field
from typing import Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────
@dataclass
class Tender:
    title: str = ""
    org: str = ""
    ref_no: str = ""
    published_date: str = ""
    closing_date: str = ""        # from the listing page
    closing_date_doc: str = ""    # from inside the document (more accurate)
    opening_date: str = ""
    tender_id: str = ""
    detail_url: str = ""
    nit_link: str = ""            # ← DIRECT DOWNLOAD LINK (no captcha needed)
    boq_link: str = ""
    other_links: list[str] = field(default_factory=list)
    portal: str = ""
    state: str = ""

    def to_dict(self) -> dict:
        return {
            "Portal": self.portal,
            "State": self.state,
            "Closing Date": self.closing_date,
            "Closing Date (from doc)": self.closing_date_doc,
            "Published Date": self.published_date,
            "Opening Date": self.opening_date,
            "Organisation": self.org,
            "Tender Title": self.title,
            "Tender Ref No": self.ref_no,
            "NIT Download Link": self.nit_link,
            "BOQ Download Link": self.boq_link,
            "Other Doc Links": " | ".join(self.other_links),
            "Detail Page URL": self.detail_url,
            "Tender ID": self.tender_id,
        }


# ─────────────────────────────────────────────────────────────────
# Base adapter
# ─────────────────────────────────────────────────────────────────
class PortalAdapter:
    """
    Base class for a procurement portal.
    Subclass and implement:
      - search_tenders(driver, from_date, to_date) → list[Tender]
      - doc_link(tender_id) → str   (static/class method)
    """
    name: str = "Unknown Portal"
    base_url: str = ""
    state: str = "Central"

    @classmethod
    def doc_link(cls, tender_id: str, doc_type: str = "NIT") -> str:
        """Return direct document download URL for a given tender ID."""
        raise NotImplementedError

    def search_tenders(
        self,
        driver: webdriver.Chrome,
        from_date: str,
        to_date: str,
    ) -> list[Tender]:
        """Scrape open tenders in date range. 
        Returns list of Tender objects."""
        raise NotImplementedError

    def _safe_text(self, el) -> str:
        try:
            return el.text.strip()
        except Exception:
            return ""

    def _extract_all_doc_links(self, driver) -> tuple[str, str, list[str]]:
        """
        Generic helper: scan current page for all download links.
        Returns (nit_url, boq_url, other_urls[])
        """
        nit_links, boq_links, other_links = [], [], []
        for a in driver.find_elements(By.TAG_NAME, "a"):
            href = (a.get_attribute("href") or "").strip()
            text = (a.text or "").lower()
            if not href or href == "#":
                continue
            if not href.startswith("http"):
                href = self.base_url.rstrip("/") + "/" + href.lstrip("/")

            is_nit  = "nit" in text or "downloadnit" in href.lower() or "nit" in href.lower()
            is_boq  = "boq" in text or "downloadboq" in href.lower() or "boq" in href.lower()
            is_doc  = any(k in href.lower() for k in ["download", "document", "corrigendum", "tender_doc"])

            if is_nit:
                nit_links.append(href)
            elif is_boq:
                boq_links.append(href)
            elif is_doc:
                other_links.append(href)

        return (
            nit_links[0] if nit_links else "",
            boq_links[0] if boq_links else "",
            list(dict.fromkeys(other_links))[:5],
        )


# ─────────────────────────────────────────────────────────────────
# PORTAL 1 — GeM (Government e-Marketplace)
# ─────────────────────────────────────────────────────────────────
class GeM(PortalAdapter):
    """
    GeM Bid Portal — bidplus.gem.gov.in
    
    Document link pattern (from your docx example):
      https://bidplus.gem.gov.in/showbidDocument/<BID_NUMBER>
    
    This is the cleanest portal — no captcha, direct link works.
    """
    name = "GeM (Government e-Marketplace)"
    base_url = "https://bidplus.gem.gov.in"
    state = "Central"

    @classmethod
    def doc_link(cls, bid_number: str, doc_type: str = "NIT") -> str:
        """
        Direct link to bid documents.
        bid_number: numeric string e.g. "9032455"
        """
        return f"https://bidplus.gem.gov.in/showbidDocument/{bid_number}"

    @classmethod
    def bid_detail_url(cls, bid_number: str) -> str:
        return f"https://bidplus.gem.gov.in/showbid/{bid_number}"

    def search_tenders(self, driver, from_date, to_date) -> list[Tender]:
        """
        GeM has a structured search at bidplus.gem.gov.in/all-bids
        Filters: date range, Open bids.
        """
        log.info("GeM: Starting search...")
        driver.get("https://bidplus.gem.gov.in/all-bids")
        time.sleep(3)

        tenders = []
        # GeM search by published date
        try:
            # Set date filters if available
            start_el = driver.find_element(By.ID, "startDate")
            start_el.clear()
            start_el.send_keys(from_date)

            end_el = driver.find_element(By.ID, "endDate")
            end_el.clear()
            end_el.send_keys(to_date)

            # Select "Open" status
            try:
                status = Select(driver.find_element(By.ID, "bidStatus"))
                status.select_by_visible_text("Open")
            except Exception:
                pass

            # Search
            driver.find_element(By.XPATH, "//button[@type='submit']").click()
            time.sleep(3)
        except NoSuchElementException:
            log.warning("GeM: Date filter fields not found; scraping all visible bids")

        # Parse results
        rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr, .bid-item, .bid-row")
        for row in rows:
            t = self._parse_gem_row(row)
            if t:
                tenders.append(t)

        return tenders

    def _parse_gem_row(self, row) -> Optional[Tender]:
        try:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) < 4:
                return None

            # Extract bid number from link
            bid_no = ""
            detail_url = ""
            for a in row.find_elements(By.TAG_NAME, "a"):
                href = a.get_attribute("href") or ""
                m = re.search(r"/showbid(?:Document)?/(\d+)", href)
                if m:
                    bid_no = m.group(1)
                    detail_url = href
                    break

            t = Tender(portal=self.name, state=self.state)
            t.tender_id = bid_no
            t.detail_url = detail_url
            t.nit_link = self.doc_link(bid_no) if bid_no else ""

            # Text cells
            texts = [self._safe_text(c) for c in cells]
            t.title        = texts[1] if len(texts) > 1 else ""
            t.org          = texts[2] if len(texts) > 2 else ""
            t.closing_date = texts[3] if len(texts) > 3 else ""
            t.published_date = texts[0] if texts else ""

            return t if bid_no else None
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────
# PORTAL 2 — eprocure.gov.in (Central NIC portal)
# ─────────────────────────────────────────────────────────────────
class Eprocure(PortalAdapter):
    """
    Central Public Procurement Portal — eprocure.gov.in
    (Uses Tapestry framework)
    
    Document download URL patterns:
      NIT: https://eprocure.gov.in/eprocure/app
            ?component=%24DirectLink&page=FrontEndDownloadNIT&service=page&id=<NIT_ID>
    
      BOQ: ...&page=FrontEndDownloadBoq...&id=<BOQ_ID>
    
    The NIT_ID is the base64-encoded document ID extracted from the detail page.
    """
    name = "eprocure.gov.in (Central)"
    base_url = "https://eprocure.gov.in"
    state = "Central"

    NIT_PAGE = "FrontEndDownloadNIT"
    BOQ_PAGE = "FrontEndDownloadBoq"

    @classmethod
    def doc_link(cls, doc_id: str, doc_type: str = "NIT") -> str:
        page = cls.NIT_PAGE if doc_type.upper() == "NIT" else cls.BOQ_PAGE
        return (
            f"https://eprocure.gov.in/eprocure/app"
            f"?component=%24DirectLink&page={page}&service=page&id={quote(doc_id)}"
        )

    @classmethod
    def detail_url(cls, tender_id: str) -> str:
        return (
            f"https://eprocure.gov.in/eprocure/app"
            f"?component=%24DirectLink_0&page=FrontEndTenderCorrigendum&service=page&id={quote(tender_id)}"
        )

    def search_tenders(self, driver, from_date, to_date) -> list[Tender]:
        from eprocure_scraper import search_open_tenders, get_document_links
        raw = search_open_tenders(driver, from_date, to_date)
        tenders = []
        for r in raw:
            docs = get_document_links(driver, r)
            r.update(docs)
            t = Tender(
                portal=self.name,
                state=self.state,
                title=r.get("Tender Title", ""),
                org=r.get("Organisation", ""),
                ref_no=r.get("Tender Ref No", ""),
                published_date=r.get("Published Date", ""),
                closing_date=r.get("Closing Date", ""),
                closing_date_doc=r.get("Closing Date (from doc)", ""),
                tender_id=r.get("Tender ID", "") or r.get("Tender ID (raw)", ""),
                detail_url=r.get("Detail Page URL", ""),
                nit_link=r.get("NIT Download Link", ""),
                boq_link=r.get("BOQ Download Link", ""),
            )
            # if not t.nit_link and t.tender_id:
            #     t.nit_link = self.doc_link(t.tender_id)
            tenders.append(t)
        return tenders


# ─────────────────────────────────────────────────────────────────
# PORTAL 3 — mahatenders.gov.in (Maharashtra)
# ─────────────────────────────────────────────────────────────────
class MahaTenders(PortalAdapter):
    """
    Maharashtra Government Tenders Portal
    
    Document URL pattern:
      https://mahatenders.gov.in/nicgep/app
        ?component=%24DirectLink&page=FrontEndDownloadNIT&service=page&id=<NIT_ID>
    
    (Same Tapestry NIC framework as eprocure — nearly identical URL structure)
    """
    name = "mahatenders.gov.in (Maharashtra)"
    base_url = "https://mahatenders.gov.in"
    state = "Maharashtra"

    @classmethod
    def doc_link(cls, doc_id: str, doc_type: str = "NIT") -> str:
        page = "FrontEndDownloadNIT" if doc_type.upper() == "NIT" else "FrontEndDownloadBoq"
        return (
            f"https://mahatenders.gov.in/nicgep/app"
            f"?component=%24DirectLink&page={page}&service=page&id={quote(doc_id)}"
        )

    def search_tenders(self, driver, from_date, to_date) -> list[Tender]:
        return self._nic_tapestry_search(driver, from_date, to_date)

    def _nic_tapestry_search(self, driver, from_date, to_date) -> list[Tender]:
        """Generic search for all NIC Tapestry-based portals (same UI)."""
        driver.get(f"{self.base_url}/nicgep/app?page=FrontEndAdvancedSearch&service=page")
        time.sleep(3)
        tenders = []

        try:
            Select(driver.find_element(By.NAME, "dateCriteria")).select_by_visible_text("Published Date")
            driver.find_element(By.NAME, "publishedDate").send_keys(from_date)
            driver.find_element(By.NAME, "publishedDateTo").send_keys(to_date)
            Select(driver.find_element(By.NAME, "tenderStatus")).select_by_visible_text("Active")
            driver.find_element(By.XPATH, "//input[@type='submit']").click()
            time.sleep(4)
        except Exception as e:
            log.warning(f"{self.name}: Search form issue: {e}")

        # Paginate
        page = 1
        while True:
            rows = self._parse_nic_table(driver)
            tenders.extend(rows)
            try:
                nxt = driver.find_element(By.XPATH, "//a[contains(text(),'Next') or contains(text(),'>')]")
                nxt.click()
                time.sleep(3)
                page += 1
            except NoSuchElementException:
                break

        return tenders

    def _parse_nic_table(self, driver) -> list[Tender]:
        tenders = []
        try:
            table = driver.find_element(By.CLASS_NAME, "table_list_border")
            for tr in table.find_elements(By.TAG_NAME, "tr")[1:]:
                tds = tr.find_elements(By.TAG_NAME, "td")
                if len(tds) < 5:
                    continue
                texts = [self._safe_text(td) for td in tds]
                # Extract ID from link
                doc_id = ""
                detail = ""
                for td in tds:
                    for a in td.find_elements(By.TAG_NAME, "a"):
                        href = a.get_attribute("href") or ""
                        m = re.search(r"id=([A-Za-z0-9+/=%]+)", href)
                        if m:
                            doc_id = m.group(1)
                            detail = href
                            break

                t = Tender(
                    portal=self.name, state=self.state,
                    published_date=texts[1] if len(texts) > 1 else "",
                    closing_date=texts[2] if len(texts) > 2 else "",
                    org=texts[4] if len(texts) > 4 else "",
                    title=texts[5] if len(texts) > 5 else "",
                    tender_id=doc_id,
                    detail_url=detail,
                    nit_link=self.doc_link(doc_id) if doc_id else "",
                )
                tenders.append(t)
        except NoSuchElementException:
            pass
        return tenders


# ─────────────────────────────────────────────────────────────────
# PORTAL 4 — etenders.kerala.gov.in (Kerala)
# ─────────────────────────────────────────────────────────────────
class KeralaTenders(MahaTenders):
    """Kerala — same NIC Tapestry framework."""
    name = "etenders.kerala.gov.in (Kerala)"
    base_url = "https://etenders.kerala.gov.in"
    state = "Kerala"

    @classmethod
    def doc_link(cls, doc_id: str, doc_type: str = "NIT") -> str:
        page = "FrontEndDownloadNIT" if doc_type.upper() == "NIT" else "FrontEndDownloadBoq"
        return (
            f"https://etenders.kerala.gov.in/nicgep/app"
            f"?component=%24DirectLink&page={page}&service=page&id={quote(doc_id)}"
        )


# ─────────────────────────────────────────────────────────────────
# PORTAL 5 — Andhra Pradesh
# ─────────────────────────────────────────────────────────────────
class APTenders(MahaTenders):
    """Andhra Pradesh — NIC Tapestry framework."""
    name = "tender.apeprocurement.gov.in (Andhra Pradesh)"
    base_url = "https://tender.apeprocurement.gov.in"
    state = "Andhra Pradesh"

    @classmethod
    def doc_link(cls, doc_id: str, doc_type: str = "NIT") -> str:
        page = "FrontEndDownloadNIT" if doc_type.upper() == "NIT" else "FrontEndDownloadBoq"
        return (
            f"https://tender.apeprocurement.gov.in/nicgep/app"
            f"?component=%24DirectLink&page={page}&service=page&id={quote(doc_id)}"
        )


# ─────────────────────────────────────────────────────────────────
# PORTAL 6 — Himachal Pradesh
# ─────────────────────────────────────────────────────────────────
class HPTenders(MahaTenders):
    """Himachal Pradesh — NIC framework."""
    name = "hptenders.gov.in (Himachal Pradesh)"
    base_url = "https://hptenders.gov.in"
    state = "Himachal Pradesh"

    @classmethod
    def doc_link(cls, doc_id: str, doc_type: str = "NIT") -> str:
        page = "FrontEndDownloadNIT" if doc_type.upper() == "NIT" else "FrontEndDownloadBoq"
        return (
            f"https://hptenders.gov.in/nicgep/app"
            f"?component=%24DirectLink&page={page}&service=page&id={quote(doc_id)}"
        )


# ─────────────────────────────────────────────────────────────────
# PORTAL 7 — Tamil Nadu (tenderstn.gov.in)
# ─────────────────────────────────────────────────────────────────
class TNTenders(MahaTenders):
    """Tamil Nadu — NIC framework."""
    name = "tenderstn.gov.in (Tamil Nadu)"
    base_url = "https://tenderstn.gov.in"
    state = "Tamil Nadu"

    @classmethod
    def doc_link(cls, doc_id: str, doc_type: str = "NIT") -> str:
        page = "FrontEndDownloadNIT" if doc_type.upper() == "NIT" else "FrontEndDownloadBoq"
        return (
            f"https://tenderstn.gov.in/nicgep/app"
            f"?component=%24DirectLink&page={page}&service=page&id={quote(doc_id)}"
        )


# ─────────────────────────────────────────────────────────────────
# PORTAL 8 — Rajasthan
# ─────────────────────────────────────────────────────────────────
class RajasthanTenders(MahaTenders):
    """Rajasthan — NIC framework."""
    name = "etenders.rajasthan.gov.in (Rajasthan)"
    base_url = "https://etenders.rajasthan.gov.in"
    state = "Rajasthan"

    @classmethod
    def doc_link(cls, doc_id: str, doc_type: str = "NIT") -> str:
        page = "FrontEndDownloadNIT" if doc_type.upper() == "NIT" else "FrontEndDownloadBoq"
        return (
            f"https://etenders.rajasthan.gov.in/nicgep/app"
            f"?component=%24DirectLink&page={page}&service=page&id={quote(doc_id)}"
        )


# ─────────────────────────────────────────────────────────────────
# PORTAL 9 — Uttar Pradesh (etender.up.nic.in)
# ─────────────────────────────────────────────────────────────────
class UPTenders(PortalAdapter):
    """
    Uttar Pradesh — etender.up.nic.in
    Different framework from standard NIC Tapestry.
    
    Document URL pattern:
      https://etender.up.nic.in/nicgepportal/app
        ?component=%24DirectLink&page=FrontEndDownloadNIT&service=page&id=<DOC_ID>
    """
    name = "etender.up.nic.in (Uttar Pradesh)"
    base_url = "https://etender.up.nic.in"
    state = "Uttar Pradesh"

    @classmethod
    def doc_link(cls, doc_id: str, doc_type: str = "NIT") -> str:
        page = "FrontEndDownloadNIT" if doc_type.upper() == "NIT" else "FrontEndDownloadBoq"
        return (
            f"https://etender.up.nic.in/nicgepportal/app"
            f"?component=%24DirectLink&page={page}&service=page&id={quote(doc_id)}"
        )

    def search_tenders(self, driver, from_date, to_date) -> list[Tender]:
        driver.get("https://etender.up.nic.in/nicgepportal/app?page=FrontEndAdvancedSearch&service=page")
        time.sleep(3)
        # Same Tapestry UI — reuse MahaTenders logic
        adapter = MahaTenders()
        adapter.base_url = self.base_url
        adapter.name = self.name
        adapter.state = self.state
        # Override doc_link in returned tenders
        tenders = adapter._nic_tapestry_search(driver, from_date, to_date)
        for t in tenders:
            t.nit_link = self.doc_link(t.tender_id) if t.tender_id else ""
            t.portal = self.name
            t.state = self.state
        return tenders


# ─────────────────────────────────────────────────────────────────
# PORTAL 10 — MSTC (Metal Scrap Trade Corporation e-auction portal)
# ─────────────────────────────────────────────────────────────────
class MSTC(PortalAdapter):
    """
    MSTC Limited e-commerce / e-procurement portal.
    
    Document URL pattern (after login):
      https://www.mstcecommerce.com/eproc/TENDDOC/viewtend.jsp?bno=<BID_NO>&tid=<TENDER_ID>
    """
    name = "mstcecommerce.com (MSTC)"
    base_url = "https://www.mstcecommerce.com"
    state = "Central"

    @classmethod
    def doc_link(cls, bid_no: str, tender_id: str = "") -> str:
        return (
            f"https://www.mstcecommerce.com/eproc/TENDDOC/viewtend.jsp"
            f"?bno={bid_no}&tid={tender_id}"
        )

    def search_tenders(self, driver, from_date, to_date) -> list[Tender]:
        driver.get("https://www.mstcecommerce.com/eproc/index.jsp")
        time.sleep(3)
        # MSTC has a different UI; implement per their specific search page
        log.warning("MSTC: Manual search implementation needed for this portal.")
        return []


# ─────────────────────────────────────────────────────────────────
# Registry — all available portals
# ─────────────────────────────────────────────────────────────────
ALL_PORTALS: dict[str, PortalAdapter] = {
    "gem":           GeM(),
    "eprocure":      Eprocure(),
    "maharashtra":   MahaTenders(),
    "kerala":        KeralaTenders(),
    "andhra":        APTenders(),
    "himachal":      HPTenders(),
    "tamilnadu":     TNTenders(),
    "rajasthan":     RajasthanTenders(),
    "up":            UPTenders(),
    "mstc":          MSTC(),
    # Add more here as you onboard them from Basha's list
}

PORTAL_ALIASES = {
    "mh": "maharashtra",
    "tn": "tamilnadu",
    "rj": "rajasthan",
    "kl": "kerala",
    "ap": "andhra",
    "hp": "himachal",
}


def get_portal(name: str) -> Optional[PortalAdapter]:
    key = PORTAL_ALIASES.get(name.lower(), name.lower())
    return ALL_PORTALS.get(key)


# ─────────────────────────────────────────────────────────────────
# Quick doc-link utility — use this WITHOUT running a full scraper
# ─────────────────────────────────────────────────────────────────
def make_doc_link(portal_name: str, doc_id: str, doc_type: str = "NIT") -> str:
    """
    Instantly generate a direct document download link given portal + doc ID.
    No browser needed.
    
    Examples:
      make_doc_link("gem", "9032455")
      → https://bidplus.gem.gov.in/showbidDocument/9032455

      make_doc_link("eprocure", "AbCd1234==")
      → https://eprocure.gov.in/eprocure/app?...&id=AbCd1234%3D%3D

      make_doc_link("maharashtra", "XyZ789==")
      → https://mahatenders.gov.in/nicgep/app?...&id=XyZ789%3D%3D
    """
    portal = get_portal(portal_name)
    if not portal:
        raise ValueError(f"Unknown portal: {portal_name}. Available: {list(ALL_PORTALS.keys())}")
    return portal.__class__.doc_link(doc_id, doc_type)


if __name__ == "__main__":
    # Demo: generate links without scraping
    examples = [
        ("gem",         "9032455"),
        ("eprocure",    "AbCdEfGh1234=="),
        ("maharashtra", "MhXyz7890AB=="),
        ("kerala",      "KlDocId999=="),
        ("rajasthan",   "RjDoc1234=="),
        ("up",          "UpDoc5678=="),
    ]
    print("Example direct document download links:\n")
    for portal, doc_id in examples:
        link = make_doc_link(portal, doc_id)
        print(f"  Portal: {portal:<15} ID: {doc_id:<20}")
        print(f"  Link:   {link}\n")
