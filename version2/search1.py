import os
import cv2
import pytesseract
import numpy as np
from PIL import Image
from io import BytesIO
import base64
import re
from time import sleep
from datetime import date, timedelta

from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager as CM
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from os import path, makedirs
import auto_merge

# ==================== CAPTCHA SOLVER CONFIGURATION ====================
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
CAPTCHA_IMAGE_XPATH = '//*[@id="captchaImage"]'
CAPTCHA_INPUT_XPATH = '//*[@id="captchaText"]'
CAPTCHA_MAX_ATTEMPTS = 5

# ==================== SCRAPER CONFIGURATION ====================
BASE_DIR = path.dirname(path.abspath(__file__))
OUTPUT_DIR = path.join(BASE_DIR, "OUTPUT")
TIMEOUT = 6
MAX_WORKERS = 20

today = date.today()

# ==================== CAPTCHA SOLVER FUNCTIONS ====================

def load_image_from_base64(base64_string):
    """Load image from base64 string with robust error handling"""
    try:
        if 'base64,' in base64_string:
            base64_string = base64_string.split('base64,')[1]
        
        # Remove ALL whitespace
        base64_string = ''.join(base64_string.split())
        base64_string = re.sub(r'[^A-Za-z0-9+/=]', '', base64_string)
        
        # Fix padding
        base64_string = base64_string.rstrip('=')
        missing_padding = len(base64_string) % 4
        if missing_padding:
            base64_string += '=' * (4 - missing_padding)
        
        image_bytes = base64.b64decode(base64_string, validate=True)
        img = Image.open(BytesIO(image_bytes))
        
        return np.array(img)
    
    except Exception as e:
        print(f"[ERROR] Failed to load image from base64: {e}")
        return None

def solve_captcha_image(image_data):
    """Solve CAPTCHA using multiple OCR methods - CAPTCHA is exactly 6 alphanumeric characters"""
    print("[CAPTCHA] Analyzing image...")
    
    img = load_image_from_base64(image_data)
    if img is None:
        return None
    
    print(f"[CAPTCHA] Image shape: {img.shape}")
    
    # Convert to grayscale
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    else:
        gray = img
    
    methods = []
    
    # Method 1: Aggressive noise removal + very high upscaling
    try:
        height, width = gray.shape
        # Upscale 5x for better character recognition
        resized = cv2.resize(gray, (width * 5, height * 5), interpolation=cv2.INTER_CUBIC)
        
        # Strong denoising to remove salt-and-pepper
        denoised = cv2.fastNlMeansDenoising(resized, None, h=40, templateWindowSize=7, searchWindowSize=21)
        
        # Bilateral filter to preserve edges
        bilateral = cv2.bilateralFilter(denoised, 9, 100, 100)
        
        # Adaptive threshold
        thresh = cv2.adaptiveThreshold(bilateral, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                       cv2.THRESH_BINARY, 15, 8)
        
        # Invert if needed
        if np.mean(thresh) < 127:
            thresh = cv2.bitwise_not(thresh)
        
        # Remove small noise components
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(thresh, connectivity=8)
        cleaned = np.zeros_like(thresh)
        for i in range(1, num_labels):
            if stats[i, cv2.CC_STAT_AREA] >= 40:  # Increased threshold
                cleaned[labels == i] = 255
        
        # Dilate slightly to connect broken characters
        kernel_dilate = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        dilated = cv2.dilate(cleaned, kernel_dilate, iterations=1)
        
        methods.append(("Aggressive Denoise 5x", dilated))
    except Exception as e:
        print(f"[WARNING] Method 1 failed: {e}")
    
    # Method 2: Black pixel isolation (for removing colored interference)
    try:
        if len(img.shape) == 3:
            # Convert to HSV
            hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
            
            # Isolate very dark pixels (black text)
            lower = np.array([0, 0, 0])
            upper = np.array([180, 255, 80])  # Adjusted for black text
            mask = cv2.inRange(hsv, lower, upper)
            
            # Upscale
            mask = cv2.resize(mask, (mask.shape[1] * 5, mask.shape[0] * 5), interpolation=cv2.INTER_CUBIC)
            
            # Clean
            mask = cv2.medianBlur(mask, 5)
            
            # Remove small components
            num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
            cleaned_mask = np.zeros_like(mask)
            for i in range(1, num_labels):
                if stats[i, cv2.CC_STAT_AREA] >= 40:
                    cleaned_mask[labels == i] = 255
            
            methods.append(("Black Isolation", cleaned_mask))
    except Exception as e:
        print(f"[WARNING] Method 2 failed: {e}")
    
    # Method 3: Extreme upscale + strong threshold
    try:
        # 6x upscale
        resized = cv2.resize(gray, (gray.shape[1] * 6, gray.shape[0] * 6), interpolation=cv2.INTER_CUBIC)
        
        # Strong Gaussian blur
        blurred = cv2.GaussianBlur(resized, (7, 7), 0)
        
        # Otsu threshold
        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Invert if needed
        if np.mean(thresh) < 127:
            thresh = cv2.bitwise_not(thresh)
        
        # Morphological opening to remove thin lines
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        opened = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)
        
        # Remove small noise
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
        cleaned = np.zeros_like(opened)
        for i in range(1, num_labels):
            if stats[i, cv2.CC_STAT_AREA] >= 50:
                cleaned[labels == i] = 255
        
        methods.append(("Extreme 6x + Otsu", cleaned))
    except Exception as e:
        print(f"[WARNING] Method 3 failed: {e}")
    
    # Method 4: Simple but effective - high contrast
    try:
        # Upscale 4x
        resized = cv2.resize(gray, (gray.shape[1] * 4, gray.shape[0] * 4), interpolation=cv2.INTER_CUBIC)
        
        # Enhance contrast
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        enhanced = clahe.apply(resized)
        
        # Threshold
        _, thresh = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        if np.mean(thresh) < 127:
            thresh = cv2.bitwise_not(thresh)
        
        methods.append(("Contrast Enhanced", thresh))
    except Exception as e:
        print(f"[WARNING] Method 4 failed: {e}")
    
    if not methods:
        print("[ERROR] All preprocessing methods failed")
        return None
    
    print(f"[CAPTCHA] Generated {len(methods)} preprocessed versions")
    
    # Try OCR with configurations optimized for exactly 6 characters
    configs = [
        r'--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
        r'--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
        r'--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
        r'--oem 1 --psm 8 -c tessedit_char_whitelist=0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
        r'--oem 3 --psm 13 -c tessedit_char_whitelist=0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
    ]
    
    results = []
    results_dict = {}  # To count occurrences
    
    for method_name, processed_img in methods:
        for config_idx, config in enumerate(configs):
            try:
                text = pytesseract.image_to_string(processed_img, config=config).strip()
                # Remove ALL non-alphanumeric characters
                text = re.sub(r'[^a-zA-Z0-9]', '', text)
                
                # MUST be exactly 6 characters
                if len(text) == 6:
                    results.append((method_name, text))
                    print(f"[CAPTCHA] {method_name} | Config {config_idx+1} → '{text}' ✓")
                    
                    # Count occurrences for voting
                    if text in results_dict:
                        results_dict[text] += 1
                    else:
                        results_dict[text] = 1
                elif len(text) > 0:
                    print(f"[CAPTCHA] {method_name} | Config {config_idx+1} → '{text}' (wrong length: {len(text)})")
                    
            except Exception as e:
                continue
    
    if results:
        # Use voting - pick the most common result
        if len(results_dict) > 1:
            best_result = max(results_dict, key=results_dict.get)
            print(f"[CAPTCHA] Voting results: {results_dict}")
            print(f"[SUCCESS] CAPTCHA SOLVED (by voting): '{best_result}' ({results_dict[best_result]} votes)")
        else:
            best_result = results[0][1]
            print(f"[SUCCESS] CAPTCHA SOLVED: '{best_result}'")
        
        return best_result
    else:
        print("[ERROR] No valid 6-character results found")
        return None

def get_captcha_base64(bot):
    """Get CAPTCHA image as base64 using screenshot method"""
    try:
        captcha_img = WebDriverWait(bot, 10).until(
            EC.presence_of_element_located((By.XPATH, CAPTCHA_IMAGE_XPATH))
        )
        
        print("[CAPTCHA] Taking screenshot...")
        captcha_base64 = captcha_img.screenshot_as_base64
        return captcha_base64
        
    except Exception as e:
        print(f"[ERROR] Failed to get CAPTCHA image: {e}")
        return None

def solve_captcha_manual(bot):
    """Manual CAPTCHA solving with OCR assistance"""
    
    for attempt in range(1, CAPTCHA_MAX_ATTEMPTS + 1):
        print(f"\n[CAPTCHA] Attempt {attempt}/{CAPTCHA_MAX_ATTEMPTS}")
        
        try:
            # Get CAPTCHA image
            captcha_base64 = get_captcha_base64(bot)
            
            if captcha_base64:
                # Try to solve automatically first (as a suggestion)
                captcha_text = solve_captcha_image(captcha_base64)
                
                if captcha_text:
                    print(f"\n[CAPTCHA SUGGESTION] OCR detected: '{captcha_text}'")
                else:
                    print("\n[CAPTCHA] OCR could not solve automatically")
            else:
                print("\n[CAPTCHA] Could not capture image")
            
            # Always ask user for manual input
            user_input = input("\n[INPUT] Enter CAPTCHA (or press Enter to use suggestion): ").strip()
            
            # Use user input if provided, otherwise use OCR result
            if user_input:
                captcha_final = user_input
                print(f"[INFO] Using manual input: '{captcha_final}'")
            elif captcha_text:
                captcha_final = captcha_text
                print(f"[INFO] Using OCR suggestion: '{captcha_final}'")
            else:
                print("[ERROR] No CAPTCHA text available")
                continue
            
            # Enter CAPTCHA
            try:
                captcha_input = WebDriverWait(bot, 5).until(
                    EC.presence_of_element_located((By.XPATH, CAPTCHA_INPUT_XPATH))
                )
                
                captcha_input.clear()
                sleep(0.5)
                captcha_input.send_keys(captcha_final)
                print(f"[SUCCESS] Entered CAPTCHA: '{captcha_final}'")
                sleep(1)
                
                # Click submit
                try:
                    bot.find_element(By.ID, "submit").click()
                except:
                    bot.find_element(By.XPATH, "//input[@type='submit']").click()
                
                # Check if successful
                try:
                    WebDriverWait(bot, 5).until(EC.presence_of_element_located((By.CLASS_NAME, "list_footer")))
                    print("[SUCCESS] CAPTCHA ACCEPTED! ✓")
                    return True
                except:
                    print("[WARNING] CAPTCHA was incorrect")
                    
                    # Ask if user wants to refresh or retry
                    retry_choice = input("[INPUT] Retry? (y/n): ").strip().lower()
                    if retry_choice != 'y':
                        continue
                    
                    # Try to refresh CAPTCHA
                    try:
                        refresh_selectors = [
                            "//img[contains(@onclick, 'refreshCaptcha')]",
                            "//a[contains(@onclick, 'refreshCaptcha')]",
                            "//button[contains(@onclick, 'refreshCaptcha')]",
                            "//*[@id='refreshCaptcha']"
                        ]
                        
                        for selector in refresh_selectors:
                            try:
                                refresh_btn = bot.find_element(By.XPATH, selector)
                                print("[CAPTCHA] Refreshing...")
                                refresh_btn.click()
                                sleep(2)
                                break
                            except:
                                continue
                    except Exception as e:
                        pass
                    
                    continue
                    
            except Exception as e:
                print(f"[ERROR] Could not enter CAPTCHA: {e}")
                continue
                
        except Exception as e:
            print(f"[ERROR] Attempt {attempt} failed: {e}")
            continue
    
    print("[ERROR] All CAPTCHA attempts failed")
    return False

# ==================== SCRAPER HELPER FUNCTIONS ====================

def get_session_cookies(bot):
    """Transfer cookies from Selenium to Requests Session"""
    session = requests.Session()
    for cookie in bot.get_cookies():
        session.cookies.set(cookie['name'], cookie['value'])
    session.headers.update({
        "User-Agent": bot.execute_script("return navigator.userAgent")
    })
    return session

def parse_html_details(html_content, tender_url):
    """Fast HTML parsing using BeautifulSoup"""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    data = {
        "tender_id": "", "work_desc": "", "category": "", "org_chain": "",
        "emd_amount": "", "emd_exemption": "", "tender_value": "", 
        "location": "", "published_date": "", "closing_date": "",
        "website": BASE_URL, "url": tender_url
    }

    def clean(text):
        return text.strip().replace('\xa0', ' ')

    rows = soup.find_all('tr')
    for row in rows:
        cells = row.find_all('td')
        
        for i in range(len(cells) - 1):
            txt = clean(cells[i].text)
            val = clean(cells[i+1].text)
            
            if "Tender ID" in txt: data["tender_id"] = val
            elif "Work Description" in txt: data["work_desc"] = val
            elif "Tender Category" in txt: data["category"] = val
            elif "Organisation Chain" in txt: data["org_chain"] = val
            elif "EMD Amount in ₹" in txt: data["emd_amount"] = val
            elif "EMD Exemption Allowed" in txt: data["emd_exemption"] = val
            elif "Tender Value in ₹" in txt: data["tender_value"] = val
            elif "Location" in txt: data["location"] = val
            elif "Bid Submission End Date" in txt: data["closing_date"] = val
            elif "Published Date" in txt: data["published_date"] = val

    return [
        '', data["tender_id"], data["work_desc"], data["category"],
        data["org_chain"], '', data["emd_amount"], data["emd_exemption"],
        data["tender_value"], STATE_NAME, data["location"], 'Online',
        data["website"], data["url"], '', data["closing_date"]
    ]

def fetch_and_parse(url, session):
    """Worker function for threading"""
    try:
        if not url.startswith("http"):
            url = BASE_URL + "/" + url.lstrip("/")
            
        response = session.get(url, timeout=10)
        if response.status_code == 200:
            return parse_html_details(response.content, url)
    except Exception as e:
        print(f"[ERROR] Failed to fetch {url}: {e}")
    return None

def save_to_excel(data_list, idx):
    headers = (["Bid User", "Tender ID", "Name of Work", "Category", "Department", "Quantity", "EMD", "Exemption", 
                "ECV", "State Name", "Location", "Apply Mode", "Website", "Document Link", "Attachments", "Closing Date"])

    state_prefix = f"{STATE_NAME}_"
    file_path = path.join(OUTPUT_DIR_STATE, state_prefix + FILE_NAME.format(idx))
    
    df = pd.DataFrame(data_list, columns=headers)
    
    if 'Closing Date' in df.columns:
        df['Closing Date'] = df['Closing Date'].astype(str).str.strip()
        df['Closing Date'] = pd.to_datetime(df['Closing Date'], format='%d-%b-%Y %I:%M %p', errors='coerce')

    writer = pd.ExcelWriter(file_path, engine='xlsxwriter', date_format="dd-mm-yyyy", datetime_format="dd-mm-yyyy hh:mm:ss")
    df.to_excel(writer, index=False)
    
    worksheet = writer.sheets['Sheet1']
    worksheet.set_column(0, len(headers)-1, 20)
    
    writer.close()
    return file_path

def select_options(bot):
    """Configure search options"""
    WebDriverWait(bot, TIMEOUT).until(EC.element_to_be_clickable((By.ID, "captchaImage")))
    
    # Select Date Criteria
    date_dropdown = bot.find_element(By.ID, "dateCriteria")
    date_dropdown.send_keys("Published Date")
    
    global FILE_NAME
    tendr_type = input("[INFO] TENDER TYPE (O=Open / L=Limited): ").strip().lower()
    if tendr_type == 'o':
        bot.find_element(By.ID, "TenderType").send_keys("Open Tender")
        FILE_NAME = "open-tenders_output_page-{}.xlsx"
    elif tendr_type == 'l':
        bot.find_element(By.ID, "TenderType").send_keys("Limited Tender")
        FILE_NAME = "limited-tenders_output_page-{}.xlsx"
    
    # Enable date fields
    bot.execute_script('document.getElementById("fromDate").removeAttribute("readonly")')
    bot.execute_script('document.getElementById("toDate").removeAttribute("readonly")')
    
    days_interval = int(input("[INFO] How many days back to scrape? "))
    
    from_date_obj = today - timedelta(days=days_interval)
    to_date_obj = today - timedelta(days=1)
    
    if days_interval == 1:
        to_date_obj = from_date_obj 

    bot.find_element(By.ID, "fromDate").clear()
    bot.find_element(By.ID, "fromDate").send_keys(from_date_obj.strftime("%d/%m/%Y"))    
    bot.find_element(By.ID, "toDate").clear()
    bot.find_element(By.ID, "toDate").send_keys(to_date_obj.strftime("%d/%m/%Y"))

# ==================== MAIN SCRAPER FUNCTION ====================

def start():
    global BASE_URL, STATE_NAME, URL, NEXT_PAGE_URL, OUTPUT_DIR_STATE
    
    BASE_URL = input("PASTE YOUR URL HERE: ").strip()
    STATE_NAME = input("ENTER STATE NAME: ").strip().replace(" ", "_") or "state"
    BID_USER = input("ENTER BID USER NAME: ").strip()
    URL = f"{BASE_URL}?page=FrontEndAdvancedSearch&service=page"
    NEXT_PAGE_URL = f"{BASE_URL}?component=%24TablePages.linkPage&page=FrontEndAdvancedSearchResult&service=direct&session=T&sp=AFrontEndAdvancedSearchResult%2Ctable&sp="
    
    OUTPUT_DIR_STATE = path.join(OUTPUT_DIR, STATE_NAME)
    if not path.exists(OUTPUT_DIR_STATE):
        makedirs(OUTPUT_DIR_STATE)
    
    options = Options()
    options.add_experimental_option("prefs", {"download_restrictions": 3})
    
    print("[INFO] Launching Chrome Driver...")
    
    service = Service(CM().install())
    bot = webdriver.Chrome(service=service, options=options)
    
    bot.maximize_window()
    bot.get(URL)
    
    # Close Popup
    try:
        WebDriverWait(bot, 3).until(EC.element_to_be_clickable((By.CLASS_NAME, "alertbutclose"))).click()
        print("[INFO] Popup closed.")
    except:
        pass
    
    select_options(bot)
    
    # Manual CAPTCHA solving with OCR assistance
    print("\n" + "="*70)
    print("CAPTCHA SOLVING (Manual with OCR Assistance)")
    print("="*70)
    
    if not solve_captcha_manual(bot):
        print("[ERROR] Failed to solve CAPTCHA. Exiting...")
        bot.quit()
        return
    
    # Get Total Pages
    try:
        list_footer = bot.find_element(By.CLASS_NAME, "list_footer")
        total_pages = list_footer.find_element(By.ID, "linkLast").get_attribute("href").split("sp=")[-1].strip()
        total_pages = int(total_pages)
    except:
        total_pages = 1
        
    print(f"\n[INFO] FOUND {total_pages} PAGES TO SCRAPE")
    start_page = int(input("[INFO] ENTER STARTING PAGE NUMBER: "))
    
    # Prepare session for fast scraping
    session = get_session_cookies(bot)
    
    for idx in range(start_page, total_pages + 1):
        print(f"\n{'='*70}")
        print(f"PROCESSING PAGE [{idx}/{total_pages}]")
        print(f"{'='*70}")
        
        # Grab all tender links
        list_table = bot.find_element(By.ID, "table")
        rows = list_table.find_elements(By.TAG_NAME, "tr")
        
        tender_links = []
        for row in rows:
            try:
                a_tags = row.find_elements(By.TAG_NAME, "a")
                for tag in a_tags:
                    href = tag.get_attribute("href")
                    if href and "DirectLink" in href:
                        tender_links.append(href)
                        break
            except:
                continue
        
        print(f"[INFO] Found {len(tender_links)} tenders. Fetching details...")
        
        # Fetch details concurrently
        page_data = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            results = executor.map(lambda url: fetch_and_parse(url, session), tender_links)
            
            for res in results:
                if res:
                    page_data.append(res)
        
        # Save data
        if page_data:
            excel_path = save_to_excel(page_data, idx)
            print(f"[SUCCESS] Saved {len(page_data)} records to {excel_path}")
        
        # Navigate to next page
        if idx < total_pages:
            try:
                next_url = NEXT_PAGE_URL + str(idx + 1)
                bot.get(next_url)
                WebDriverWait(bot, 10).until(EC.presence_of_element_located((By.ID, "table")))
            except Exception as e:
                print(f"[ERROR] Could not navigate to page {idx+1}: {e}")
                break
    
    print(f"[BIDALERT INFO] STARTING AUTO MERGE AND REPORT GENERATION...")
    auto_merge.run_merge(STATE_NAME, BID_USER)

    print("\n" + "="*70)
    print("SCRAPING AND MERGING COMPLETE!")
    print("="*70)
    bot.quit()
    input("Press Enter to Exit...")

if __name__ == "__main__":
    start()