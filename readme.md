# Tender Scraper

A Python-based tender scraping project for Indian government procurement portals.

This repository contains two working versions of the scraper:

* `version1/` - multi-portal scraper with adapter-based architecture
* `version2/` - alternate scraper with OCR/manual CAPTCHA support
* `gem_ultra1.py` - standalone GeM-related script, if required

---

## Folder Structure

```text
scraper/
│
├── samples/
│   └── .gitkeep
│
├── version1/
│   ├── eprocure_scraper.py
│   ├── portal_adapters.py
│   ├── run_scraper.py
│   
├── version2/
│   ├── search1.py
│   └── auto_merge.py
│
├── requirements.txt
├── README.md
└── .gitignore
```

---

## Version 1: Multi-Portal Scraper

`version1` contains a modular scraper design.

### Main files

```text
eprocure_scraper.py   - eprocure.gov.in scraper
portal_adapters.py    - portal adapter classes
run_scraper.py        - main runner and Excel exporter
```

### Features

* Scrapes eprocure-style tender listings
* Supports adapter-based portal expansion
* Extracts tender metadata
* Exports results to Excel
* Supports manual CAPTCHA flow where required
* Keeps tender detail page URLs for verification

### Run Version 1

From the root folder:

```powershell
python version1/run_scraper.py --list_portals
```

Scrape eprocure for a small test date range:

```powershell
python version1/run_scraper.py --portals eprocure --from 13/06/2026 --to 13/06/2026 --output tenders_test.xlsx
```

Generate a GeM document link:

```powershell
python version1/run_scraper.py --make_link --portal gem --id 9032455
```

---

## Version 2: OCR-Assisted Scraper

`version2` contains an alternate scraper with OCR-assisted CAPTCHA handling.

### Main files

```text
search1.py      - main scraper
auto_merge.py   - placeholder merge function
```

### Features

* Opens procurement portal using Selenium
* Uses manual CAPTCHA input with OCR suggestion
* Extracts tender details
* Saves page-wise Excel files
* Can use Tesseract OCR for CAPTCHA assistance

### Run Version 2

```powershell
python version2/search1.py
```

Example inputs:

```text
PASTE YOUR URL HERE: https://eprocure.gov.in/eprocure/app
ENTER STATE NAME: Central
ENTER BID USER NAME: YourName
TENDER TYPE (O=Open / L=Limited): o
How many days back to scrape? 1
ENTER STARTING PAGE NUMBER: 1
```

---

## Setup Instructions

### 1. Create virtual environment

```powershell
py -3 -m venv .venv
```

### 2. Activate virtual environment

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

---

## Requirements

The project uses:

```text
selenium
webdriver-manager
pandas
openpyxl
xlsxwriter
requests
beautifulsoup4
lxml
pillow
numpy
opencv-python
pytesseract
```

These are listed in `requirements.txt`.

---

## Tesseract OCR Setup

Version 2 uses Tesseract OCR for CAPTCHA assistance.

Install Tesseract on Windows:

```powershell
winget install -e --id UB-Mannheim.TesseractOCR
```

After installation, check:

```powershell
Test-Path "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

Expected output:

```text
True
```

If Tesseract is installed somewhere else, update this line inside `version2/search1.py`:

```python
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
```

---

## Output

Generated files may include:

```text
tenders.xlsx
tenders_test.xlsx
OUTPUT/
debug/
downloads/
```

These files are ignored by Git using `.gitignore`.

---

## Files Ignored from Git

The following should not be pushed:

```text
.venv/
__pycache__/
task1/
debug/
downloads/
OUTPUT/
*.xlsx
*.xls
*.csv
*.html
.env
```

