import asyncio
import httpx
import pandas as pd
import os
import json
import math
import time
import argparse
import sys
from datetime import datetime, timedelta

# --- ARGUMENT PARSER ---
parser = argparse.ArgumentParser(description="Ultra-Fast GeM Scraper (Pro Edition)")
parser.add_argument("--username", type=str, required=True, help="Username for logs")
parser.add_argument("--start_index", type=int, required=True, help="Start state index (1-36)")
parser.add_argument("--end_index", type=int, required=True, help="End state index (1-36)")
parser.add_argument("--days_interval", type=int, default=1, help="Number of days to scrape")
parser.add_argument("--run_id", type=str, required=True, help="Unique Run ID")
args = parser.parse_args()

# --- DIRECTORY SETUP ---
# Output lives under backend/outputs/gem/<run_id>/
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_BASE  = os.path.join(BACKEND_DIR, "outputs", "gem", args.run_id)

# Legacy-compatible sub-directories (mirrors the standalone script layout)
SCRAPE_DIR    = os.path.join(OUTPUT_BASE, "gemscrape")
CSV_OUTPUT_DIR = os.path.join(OUTPUT_BASE, "Gem_CSVs")
REPORT_DIR    = os.path.join(OUTPUT_BASE, "Scraping_Reports")
DUPS_DIR      = os.path.join(OUTPUT_BASE, "Gem_Duplicates")

for folder in [OUTPUT_BASE, SCRAPE_DIR, CSV_OUTPUT_DIR, REPORT_DIR, DUPS_DIR]:
    os.makedirs(folder, exist_ok=True)

# --- STATE → CITY/DISTRICT MAP ---
CITIES_STATES_MAP = {
    "ANDAMAN & NICOBAR": ["NICOBAR", "NORTH AND MIDDLE ANDAMAN", "SOUTH ANDAMAN"],
    "ANDHRA PRADESH": ["ANANTHAPUR", "CHITTOOR", "CUDDAPAH", "EAST GODAVARI", "GUNTUR", "KRISHNA", "KURNOOL", "NELLORE", "PRAKASAM", "SRIKAKULAM", "VISAKHAPATNAM", "VIZIANAGARAM", "WEST GODAVARI"],
    "ARUNACHAL PRADESH": ["CHANGLANG", "DIBANG VALLEY", "EAST KAMENG", "EAST SIANG", "KURUNG KUMEY", "LOHIT", "LOWER SUBANSIRI", "PAPUM PARE", "TAWANG", "TIRAP", "UPPER SIANG", "UPPER SUBANSIRI", "WEST KAMENG", "WEST SIANG"],
    "ASSAM": ["BARPETA", "BONGAIGAON", "CACHAR", "DARRANG", "DHEMAJI", "DHUBRI", "DIBRUGARH", "GOALPARA", "GOLAGHAT", "HAILAKANDI", "JORHAT", "KAMRUP", "KARBI ANGLONG", "KARIMGANJ", "KOKRAJHAR", "LAKHIMPUR", "MARIGAON", "NAGAON", "NALBARI", "NORTH CACHAR HILLS", "SIVASAGAR", "SONITPUR", "TINSUKIA"],
    "BIHAR": ["ARARIA", "ARWAL", "AURANGABAD", "BANKA", "BEGUSARAI", "BHAGALPUR", "BHOJPUR", "BUXAR", "DARBHANGA", "EAST CHAMPARAN", "GAYA", "GOPALGANJ", "JAMUI", "JEHANABAD", "KAIMUR (BHABUA)", "KATIHAR", "KHAGARIA", "KISHANGANJ", "LAKHISARAI", "MADHEPURA", "MADHUBANI", "MUNGER", "MUZAFFARPUR", "NALANDA", "NAWADA", "PATNA", "PURNIA", "ROHTAS", "SAHARSA", "SAMASTIPUR", "SARAN", "SHEIKHPURA", "SHEOHAR", "SITAMARHI", "SIWAN", "SUPAUL", "VAISHALI", "WEST CHAMPARAN"],
    "CHANDIGARH": ["CHANDIGARH"],
    "CHHATTISGARH": ["BASTAR", "BIJAPUR", "BILASPUR", "DANTEWADA", "DHAMTARI", "DURG", "JANJGIR-CHAMPA", "JASHPUR", "KANKER", "KAWARDHA", "KORBA", "KORIYA", "MAHASAMUND", "RAIGARH", "RAIPUR", "RAJNANDGAON", "SURGUJA"],
    "DADRA & NAGAR HAVELI": ["DADRA & NAGAR HAVELI"],
    "DAMAN & DIU": ["DAMAN", "DIU"],
    "DELHI": ["CENTRAL DELHI", "EAST DELHI", "NEW DELHI", "NORTH DELHI", "NORTH EAST DELHI", "NORTH WEST DELHI", "SHAHDARA", "SOUTH DELHI", "SOUTH EAST DELHI", "SOUTH WEST DELHI", "WEST DELHI"],
    "GOA": ["NORTH GOA", "SOUTH GOA"],
    "GUJARAT": ["AHMEDABAD", "AMRELI", "ANAND", "BANASKANTHA", "BHARUCH", "BHAVNAGAR", "DAHOD", "GANDHI NAGAR", "JAMNAGAR", "JUNAGADH", "KACHCHH", "KHEDA", "MAHESANA", "NARMADA", "NAVSARI", "PANCH MAHALS", "PATAN", "PORBANDAR", "RAJKOT", "SABARKANTHA", "SURAT", "SURENDRA NAGAR", "THE DANGS", "VADODARA", "VALSAD"],
    "HARYANA": ["AMBALA", "BHIWANI", "FARIDABAD", "FATEHABAD", "GURGAON", "HISAR", "JHAJJAR", "JIND", "KAITHAL", "KARNAL", "KURUKSHETRA", "MAHENDRAGARH", "PANCHKULA", "PANIPAT", "REWARI", "ROHTAK", "SIRSA", "SONIPAT", "YAMUNA NAGAR"],
    "HIMACHAL PRADESH": ["BILASPUR", "CHAMBA", "HAMIRPUR", "KANGRA", "KINNAUR", "KULLU", "LAHUL & SPITI", "MANDI", "SHIMLA", "SIRMAUR", "SOLAN", "UNA"],
    "JAMMU & KASHMIR": ["ANANTHNAG", "BANDIPUR", "BARAMULLA", "BUDGAM", "DODA", "JAMMU", "KARGIL", "KATHUA", "KUPWARA", "LEH", "POONCH", "PULWAMA", "RAJAURI", "SAMBA", "SRINAGAR", "UDHAMPUR"],
    "JHARKHAND": ["BOKARO", "CHATRA", "DEOGHAR", "DHANBAD", "DUMKA", "EAST SINGHBHUM", "GARHWA", "GIRIDH", "GODDA", "GUMLA", "HAZARIBAG", "JAMTARA", "KHUNTI", "KODERMA", "LATEHAR", "LOHARDAGA", "PAKUR", "PALAMAU", "RAMGARH", "RANCHI", "SAHIBGANJ", "SARAIKELA KHARSAWAN", "SIMDEGA", "WEST SINGHBHUM"],
    "KARNATAKA": ["BAGALKOT", "BANGALORE", "BANGALORE RURAL", "BELGAUM", "BELLARY", "BIDAR", "BIJAPUR", "CHAMRAJNAGAR", "CHICKMAGALUR", "CHIKKABALLAPUR", "CHITRADURGA", "DAKSHINA KANNADA", "DAVANGARE", "DHARWARD", "GADAG", "GULBARGA", "HASSAN", "HAVERI", "KODAGU", "KOLAR", "KOPPAL", "MANDYA", "MYSURU", "RAICHUR", "RAMANAGAR", "SHIMOGA", "TUMKUR", "UDUPI", "UTTARA KANNADA"],
    "KERALA": ["ALAPPUZHA", "ERNAKULAM", "IDUKKI", "KANNUR", "KASARGOD", "KOLLAM", "KOTTAYAM", "KOZHIKODE", "MALAPPURAM", "PALAKKAD", "PATHANAMTHITTA", "THIRUVANANTHAPURAM", "THRISSUR", "WAYANAD"],
    "LAKSHADWEEP": ["LAKSHADWEEP"],
    "MADHYA PRADESH": ["ANUPPUR", "ASHOKNAGAR", "BALAGHAT", "BARWANI", "BETUL", "BHIND", "BHOPAL", "CHHATARPUR", "CHHINDWARA", "DAMOH", "DATIA", "DEWAS", "DHAR", "DINDORI", "EAST NIMAR", "GUNA", "GWALIOR", "HARDA", "HOSHANGABAD", "INDORE", "JABALPUR", "JHABUA", "KATNI", "KHARGONE", "MANDLA", "MANDSAUR", "MORENA", "NARSINGHPUR", "NEEMUCH", "PANNA", "RAISEN", "RAJGARH", "RATLAM", "REWA", "SAGAR", "SATNA", "SEHORE", "SHAHDOL", "SHAJAPUR", "SHEOPUR", "SHIVPURI", "SIDHI", "TIKAMGARH", "UJJAIN", "UMARIA", "VIDISHA"],
    "MAHARASHTRA": ["AHMEDNAGAR", "AKOLA", "AMRAVATI", "AURANGABAD", "BEED", "BHANDARA", "BULDHANA", "CHANDRAPUR", "DHULE", "GADCHIROLI", "GONDIA", "HINGOLI", "JALGAON", "JALNA", "KOLHAPUR", "LATUR", "MUMBAI", "NAGPUR", "NANDED", "NANDURBAR", "NASHIK", "OSMANABAD", "PARBHANI", "PUNE", "RAIGAD", "RATNAGIRI", "SANGLI", "SATARA", "SINDHUDURG", "SOLAPUR", "THANE", "WARDHA", "WASHIM", "YAVATMAL"],
    "MANIPUR": ["BISHNUPUR", "CHANDEL", "CHURACHANDPUR", "IMPHAL EAST", "IMPHAL WEST", "SENAPATI", "TAMENGLONG", "THOUBAL", "UKHRUL"],
    "MEGHALAYA": ["EAST GARO HILLS", "EAST KHASI HILLS", "JAINTIA HILLS", "RI BHOI", "SOUTH GARO HILLS", "WEST GARO HILLS", "WEST KHASI HILLS"],
    "MIZORAM": ["AIZAWL", "CHAMPHAI", "KOLASIB", "LAWNGTLAI", "LUNGLEI", "MAMMIT", "SAIHA", "SERCHHIP"],
    "NAGALAND": ["DIMAPUR", "KIPHIRE", "KOHIMA", "LONGLENG", "MOKOKCHUNG", "MON", "PEREN", "PHEK", "TUENSANG", "WOKHA", "ZUNHEBOTTO"],
    "ODISHA": ["ANGUL", "BALANGIR", "BALESWAR", "BARGARH", "BHADRAK", "BOUDH", "CUTTACK", "DEBAGARH", "DHENKANAL", "GAJAPATI", "GANJAM", "JAGATSINGHAPUR", "JAJAPUR", "JHARSUGUDA", "KALAHANDI", "KANDHAMAL", "KENDRAPARA", "KENDUJHAR", "KHORDHA", "KORAPUT", "MALKANGIRI", "MAYURBHANJ", "NABARANGAPUR", "NAYAGARH", "NUAPADA", "PURI", "RAYAGADA", "SAMBALPUR", "SONAPUR", "SUNDERGARH"],
    "PUDUCHERRY": ["KARAIKAL", "MAHE", "PONDICHERRY"],
    "PUNJAB": ["AMRITSAR", "BARNALA", "BATHINDA", "FARIDKOT", "FATEHGARH SAHIB", "FAZILKA", "FIROZPUR", "GURDASPUR", "HOSHIARPUR", "JALANDHAR", "KAPURTHALA", "LUDHIANA", "MANSA", "MOGA", "MOHALI", "MUKTSAR", "NAWANSHAHR", "PATHANKOT", "PATIALA", "RUPNAGAR", "SANGRUR", "TARN TARAN"],
    "RAJASTHAN": ["AJMER", "ALWAR", "BANSWARA", "BARAN", "BARMER", "BHARATPUR", "BHILWARA", "BIKANER", "BUNDI", "CHITTORGARH", "CHURU", "DAUSA", "DHOLPUR", "DUNGARPUR", "GANGANAGAR", "HANUMANGARH", "JAIPUR", "JAISALMER", "JALOR", "JHALAWAR", "JHUNJHUNU", "JODHPUR", "KARAULI", "KOTA", "NAGAUR", "PALI", "RAJSAMAND", "SAWAI MADHOPUR", "SIKAR", "SIROHI", "SRI GANGANAGAR", "TONK", "UDAIPUR"],
    "SIKKIM": ["EAST SIKKIM", "NORTH SIKKIM", "SOUTH SIKKIM", "WEST SIKKIM"],
    "TAMIL NADU": ["ARIYALUR", "CHENNAI", "COIMBATORE", "CUDDALORE", "DHARMAPURI", "DINDIGUL", "ERODE", "KANCHIPURAM", "KANYAKUMARI", "KARUR", "KRISHNAGIRI", "MADURAI", "NAGAPATTINAM", "NAMAKKAL", "NILGIRIS", "PERAMBALUR", "PUDUKKOTTAI", "RAMANATHAPURAM", "SALEM", "SIVAGANGA", "THANJAVUR", "THENI", "TIRUCHIRAPPALLI", "TIRUNELVELI", "TIRUPPUR", "TIRUVALLUR", "TIRUVANNAMALAI", "TIRUVARUR", "TUTICORIN", "VELLORE", "VILLUPURAM", "VIRUDHUNAGAR"],
    "TELANGANA": ["ADILABAD", "HYDERABAD", "K.V.RANGAREDDY", "KARIM NAGAR", "KHAMMAM", "MAHABUB NAGAR", "MEDAK", "NALGONDA", "NIZAMABAD", "RANGAREDDI", "WARANGAL"],
    "TRIPURA": ["DHALAI", "NORTH TRIPURA", "SOUTH TRIPURA", "WEST TRIPURA"],
    "UTTAR PRADESH": ["AGRA", "ALIGARH", "ALLAHABAD", "AMBEDKAR NAGAR", "AURAIYA", "AZAMGARH", "BAGPAT", "BAHRAICH", "BALLIA", "BALRAMPUR", "BANDA", "BARABANKI", "BAREILLY", "BASTI", "BIJNOR", "BUDAUN", "BULANDSHAHR", "CHANDAULI", "CHITRAKOOT", "DEORIA", "ETAH", "ETAWAH", "FAIZABAD", "FARRUKHABAD", "FATEHPUR", "FIROZABAD", "GAUTAM BUDDHA NAGAR", "GHAZIABAD", "GHAZIPUR", "GONDA", "GORAKHPUR", "HAMIRPUR", "HARDOI", "HATHRAS", "JALAUN", "JAUNPUR", "JHANSI", "JYOTIBA PHULE NAGAR", "KANNAUJ", "KANPUR DEHAT", "KANPUR NAGAR", "KAUSHAMBI", "KHERI", "KUSHINAGAR", "LALITPUR", "LUCKNOW", "MAHARAJGANJ", "MAHOBA", "MAINPURI", "MATHURA", "MAU", "MEERUT", "MIRZAPUR", "MORADABAD", "MUZAFFARNAGAR", "PILIBHIT", "PRATAPGARH", "RAEBARELI", "RAMPUR", "SAHARANPUR", "SANT KABIR NAGAR", "SANT RAVIDAS NAGAR", "SHAHJAHANPUR", "SHRAWASTI", "SIDDHARTHNAGAR", "SITAPUR", "SONBHADRA", "SULTANPUR", "UNNAO", "VARANASI"],
    "UTTARAKHAND": ["ALMORA", "BAGESHWAR", "CHAMOLI", "CHAMPAWAT", "DEHRADUN", "HARIDWAR", "NAINITAL", "PAURI GARHWAL", "PITHORAGARH", "RUDRAPRAYAG", "TEHRI GARHWAL", "UDHAM SINGH NAGAR", "UTTARKASHI"],
    "WEST BENGAL": ["BANKURA", "BARDHAMAN", "BIRBHUM", "COOCH BEHAR", "DARJEELING", "DINAJPUR DAKSHIN", "DINAJPUR UTTAR", "HOOGHLY", "HOWRAH", "JALPAIGURI", "KOLKATA", "MALDA", "MEDINIPUR EAST", "MEDINIPUR WEST", "MURSHIDABAD", "NADIA", "NORTH 24 PARGANAS", "PRESIDENCY", "PURULIA", "SOUTH 24 PARGANAS"],
}

VALID_STATES = list(CITIES_STATES_MAP.keys())

HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": "https://bidplus.gem.gov.in",
    "Referer": "https://bidplus.gem.gov.in/advance-search",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
}

COOKIES = {
    "csrf_gem_cookie": "88bd48d4f34489018bbc590b787ff22f",
    "ci_session": "87b0534b6667a4dc0e976e8bc1e8ba2590475b8f",
}
CSRF_TOKEN = "88bd48d4f34489018bbc590b787ff22f"

# --- SPEED LIMITS ---
MAX_CONCURRENT_STATES = 5   # Process 5 states at once
MAX_CONCURRENT_PAGES  = 10  # Each state can fetch 10 pages at once


class UltraGeMScraper:
    def __init__(self, username, start_idx, end_idx, run_id=None, log_callback=None):
        self.username = username
        self.target_states = VALID_STATES[start_idx - 1: end_idx]
        self.cities_map = CITIES_STATES_MAP
        self.run_id = run_id or args.run_id
        self.log_callback = log_callback

        # httpx.Timeout(total, connect=x) is only supported in newer httpx.
        # Use a simple scalar for full compatibility with the embedded version.
        try:
            _timeout = httpx.Timeout(45.0, connect=15.0)
        except TypeError:
            _timeout = httpx.Timeout(45.0)

        self.client = httpx.AsyncClient(
            headers=HEADERS,
            cookies=COOKIES,
            verify=False,
            timeout=_timeout,
            limits=httpx.Limits(max_keepalive_connections=50, max_connections=100),
        )
        self.stats = {}
        self.start_time = None

    def _log(self, message):
        """Helper to print and call log_callback if provided."""
        print(message, flush=True)
        if self.log_callback:
            try:
                self.log_callback(message)
            except Exception as e:
                print(f"Error in log_callback: {e}", flush=True)

    async def fetch_with_retry(self, url, data, retry_count=5):
        """Robust fetching with exponential backoff."""
        for i in range(retry_count):
            try:
                response = await self.client.post(url, data=data)
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    self._log(f" [!] Rate limited (429) on attempt {i+1}. Cooling down...")
                    await asyncio.sleep(5 * (i + 1))
                else:
                    self._log(f" [!] Server Error {response.status_code} on attempt {i+1}.")
                    if i == retry_count - 1:
                        self._log(f" [!] Final attempt failed.")
                    await asyncio.sleep(2)
            except httpx.TimeoutException:
                self._log(f" [!] Timeout on attempt {i+1}.")
                if i == retry_count - 1:
                    self._log(" [!] Final timeout.")
                await asyncio.sleep(2)
            except Exception as e:
                self._log(f" [!] Network Error on attempt {i+1}: {e}")
                if i == retry_count - 1:
                    self._log(f" [!] Final network error.")
                await asyncio.sleep(2)
        return None

    async def scrape_state(self, state, today, tomorrow, semaphore, index):
        async with semaphore:
            # Staggered start to prevent simultaneous session hits
            await asyncio.sleep(index * 0.5)
            self._log(f"[*] Scraping: {state}... (Run ID: {self.run_id})")
            state_dir = os.path.join(SCRAPE_DIR, state)
            os.makedirs(state_dir, exist_ok=True)

            url = "https://bidplus.gem.gov.in/search-bids"

            cities = self.cities_map.get(state, [])
            if not cities:
                cities = [""]

            self._log(f" [+] {state}: Starting scrape across {len(cities)} cities/locations.")

            state_bids = []
            pages_successful = 0

            city_semaphore = asyncio.Semaphore(15)
            page_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PAGES)

            async def process_city(city):
                async with city_semaphore:
                    # 1. Get Metadata & Page Count
                    initial_payload = {
                        "payload": json.dumps({
                            "searchType": "con",
                            "state_name_con": state,
                            "city_name_con": city,
                            "bidEndFromCon": today,
                            "bidEndToCon": tomorrow,
                        }),
                        "csrf_bd_gem_nk": CSRF_TOKEN,
                    }

                    meta = await self.fetch_with_retry(url, initial_payload)
                    if not meta or "response" not in meta:
                        self._log(f" [!] {state} | {city}: Failed to get metadata or empty response.")
                        return [], 0

                    num_found = meta["response"]["response"].get("numFound", 0)
                    total_pages = math.ceil(num_found / 10)
                    self._log(f" [+] {state} | {city}: Found {num_found} bids ({total_pages} pages)")

                    if total_pages == 0:
                        return [], 0

                    # 2. Parallel Page Extraction
                    async def fast_fetch(p):
                        async with page_semaphore:
                            p_load = {
                                "payload": json.dumps({
                                    "searchType": "con",
                                    "state_name_con": state,
                                    "city_name_con": city,
                                    "bidEndFromCon": today,
                                    "bidEndToCon": tomorrow,
                                    "page": p,
                                }),
                                "csrf_bd_gem_nk": CSRF_TOKEN,
                            }
                            res = await self.fetch_with_retry(url, p_load)
                            docs = (
                                res.get("response", {}).get("response", {}).get("docs", [])
                                if res
                                else []
                            )
                            return docs, p

                    page_tasks = [fast_fetch(p) for p in range(1, total_pages + 1)]
                    all_results = await asyncio.gather(*page_tasks)

                    self._log(f" [+] {state} | {city}: Finished gathering {len(all_results)} page tasks.")

                    city_bids = []
                    successful_city_pages = 0

                    for docs, p_no in all_results:
                        if docs:
                            extracted = []
                            for item in docs:
                                bid_id = item.get("id", "")
                                doc_link = f"https://bidplus.gem.gov.in/showbidDocument/{bid_id}"
                                extracted.append({
                                    "user name": self.username,
                                    "Bid No": item.get("b_bid_number", [""])[0],
                                    "Name of Work": item.get("b_category_name", [""])[0],
                                    "category": "N/A",
                                    "Ministry and Department": (
                                        f"{item.get('ba_official_details_minName', [''])[0]} - "
                                        f"{item.get('ba_official_details_deptName', [''])[0]}"
                                    ),
                                    "Quantity": item.get("b_total_quantity", [""])[0],
                                    "EMD": item.get("b_emd_amount", [""])[0],
                                    "Exemption": "N/A",
                                    "Estimation Value": item.get("b_total_value", [""])[0],
                                    "state": state,
                                    "location": city if city else (
                                        item.get("ba_official_details_officeName", [""])[0] or "Unknown Location"
                                    ),
                                    "Apply Mode": "Online",
                                    "Website Link": "https://bidplus.gem.gov.in/",
                                    "Document link": doc_link,
                                    "Attachment link": doc_link,
                                    "End Date": item.get("final_end_date_sort", [""])[0],
                                })

                            if extracted:
                                city_bids.extend(extracted)
                                successful_city_pages += 1

                    return city_bids, successful_city_pages

            city_tasks = [process_city(city) for city in cities]
            city_results = await asyncio.gather(*city_tasks)

            for c_bids, p_count in city_results:
                state_bids.extend(c_bids)
                pages_successful += p_count

            # 3. Final Processing for State
            total_scraped = len(state_bids)
            unique_bids = 0
            dups_removed = 0
            cnt_bid_dups = 0
            cnt_content_dups = 0

            if state_bids:
                df = pd.DataFrame(state_bids)

                # --- Robust Duplicate Detection ---
                df["Bid No"] = df["Bid No"].astype(str).str.strip()
                placeholders = ["", "N/A", "nan", "Nan", "None", "NONE", "null", "undefined"]
                is_valid_bid = (
                    ~df["Bid No"].str.lower().isin([p.lower() for p in placeholders])
                    & df["Bid No"].notna()
                )

                mask_bid_no = df.duplicated(subset=["Bid No"], keep="first") & is_valid_bid
                mask_content = (
                    df.duplicated(
                        subset=["Name of Work", "Ministry and Department", "End Date", "Quantity"],
                        keep="first",
                    )
                    & (~is_valid_bid)
                )

                mask = mask_bid_no | mask_content
                df_duplicates = df[mask].copy()

                if not df_duplicates.empty:
                    df_duplicates["Duplicate Reason"] = "Duplicate Bid Number"
                    df_duplicates.loc[
                        df_duplicates.index.isin(df[mask_content].index),
                        "Duplicate Reason",
                    ] = "Identical Content (Missing Bid No)"

                    dups_path = os.path.join(DUPS_DIR, f"{state}_duplicates.csv")
                    df_duplicates.to_csv(dups_path, index=False)
                    dups_removed = len(df_duplicates)
                    cnt_bid_dups = int(mask_bid_no.sum())
                    cnt_content_dups = int(mask_content.sum())

                # Keep only unique ones
                df = df[~mask].copy()
                unique_bids = len(df)

                # Sort by End Date
                if "End Date" in df.columns:
                    df["End Date"] = pd.to_datetime(df["End Date"], errors="coerce")
                    df = df.sort_values(by="End Date", ascending=True)
                    df["End Date"] = df["End Date"].dt.strftime("%d-%m-%Y %H:%M:%S")

                # Save CSV (no header, legacy-compatible)
                csv_path = os.path.join(CSV_OUTPUT_DIR, f"{state}.csv")
                df.to_csv(csv_path, index=False, header=False)

                # Save per-state Excel
                excel_path = os.path.join(
                    state_dir,
                    f"gem_output_of_{state.replace(' ', '_').replace('&', 'and')}.xlsx",
                )
                df.to_excel(excel_path, index=False)
                self._log(f"File written: {excel_path}")

            self.stats[state] = {
                "pages": pages_successful,
                "total": total_scraped,
                "unique": unique_bids,
                "dups": dups_removed,
            }

            if dups_removed > 0:
                detail = []
                if cnt_bid_dups > 0:
                    detail.append(f"{cnt_bid_dups} by Bid No")
                if cnt_content_dups > 0:
                    detail.append(f"{cnt_content_dups} by Content")
                self._log(
                    f" [OK] {state} Done: {unique_bids} Unique Bids. "
                    f"Removed {dups_removed} dups ({', '.join(detail)})."
                )
            else:
                self._log(f" [OK] {state} Done: {unique_bids} Bids.")

    async def run(self, days_interval):
        self.start_time = time.time()
        self._log("\n" + "=" * 60)
        self._log("       ULTRA-FAST GeM SCRAPER (PRO EDITION)")
        self._log("=" * 60 + "\n")

        today_dt = datetime.now()
        today    = today_dt.strftime("%y-%m-%d")
        tomorrow = (today_dt + timedelta(days=days_interval)).strftime("%y-%m-%d")

        self._log(
            f"Scraping {len(self.target_states)} state(s): "
            f"{', '.join(self.target_states)}"
        )
        self._log(f"Date range: {today} -> {tomorrow}\n")

        state_semaphore = asyncio.Semaphore(MAX_CONCURRENT_STATES)
        tasks = [
            self.scrape_state(s, today, tomorrow, state_semaphore, idx)
            for idx, s in enumerate(self.target_states)
        ]

        await asyncio.gather(*tasks)
        await self.client.aclose()

        duration = time.time() - self.start_time
        self.generate_report(duration)

        # Final merged Excel (all states combined)
        self._write_master_excel()

    def _write_master_excel(self):
        """Merge all per-state Excel files into a single master CSV + Excel with proper headers."""
        all_dfs = []
        for state in self.target_states:
            # Read from the per-state Excel (which has headers), not the headerless CSV
            state_safe = state.replace(" ", "_").replace("&", "and")
            excel_path = os.path.join(
                SCRAPE_DIR, state, f"gem_output_of_{state_safe}.xlsx"
            )
            if os.path.exists(excel_path):
                try:
                    df = pd.read_excel(excel_path, engine="openpyxl")
                    all_dfs.append(df)
                except Exception as e:
                    print(f" [!] Could not read {excel_path}: {e}", flush=True)

        if all_dfs:
            master_df = pd.concat(all_dfs, ignore_index=True)

            # --- Write merged Excel (with headers) ---
            excel_out = os.path.join(OUTPUT_BASE, f"gem_output_of_merged_{args.run_id}.xlsx")
            master_df.to_excel(excel_out, index=False)
            print(f"File written: {excel_out}", flush=True)

            # --- Write merged CSV (with headers) - this is what merge-download will serve ---
            csv_out = os.path.join(OUTPUT_BASE, f"gem_merged_data_{args.run_id}.csv")
            master_df.to_csv(csv_out, index=False)
            print(f"File written: {csv_out}", flush=True)
        else:
            print(" [!] No per-state Excel files found to merge.", flush=True)


    def generate_report(self, duration):
        date_str = datetime.now().strftime("%Y-%m-%d")
        report_path = os.path.join(REPORT_DIR, f"ultra_report_{date_str}.txt")

        with open(report_path, "w") as f:
            f.write("=" * 85 + "\n")
            f.write("             GeM ULTRA-FAST SCRAPING SUMMARY (DEDUPLICATED)\n")
            f.write(f"             Time Taken: {duration:.2f} seconds\n")
            f.write(
                f"             Average Speed: "
                f"{len(self.target_states) / max(duration, 1):.2f} states/sec\n"
            )
            f.write("=" * 85 + "\n\n")
            f.write(
                f"{'STATE':<25} | {'PAGES':<6} | {'SCRAPED':<8} | "
                f"{'UNIQUE':<8} | {'DUPLICATES':<10}\n"
            )
            f.write("-" * 80 + "\n")

            total_p = total_s = total_u = total_d = 0
            for state, data in self.stats.items():
                f.write(
                    f"{state:<25} | {data['pages']:<6} | {data['total']:<8} | "
                    f"{data['unique']:<8} | {data['dups']:<10}\n"
                )
                total_p += data["pages"]
                total_s += data["total"]
                total_u += data["unique"]
                total_d += data["dups"]

            f.write("-" * 80 + "\n")
            f.write(
                f"{'GRAND TOTALS':<25} | {total_p:<6} | {total_s:<8} | "
                f"{total_u:<8} | {total_d:<10}\n"
            )
            f.write("=" * 85 + "\n")

        self._log(f"\nALL STATES SCRAPED IN {duration:.1f} SECONDS!")
        self._log(f"Total Bids: {total_u}")
        self._log(f"Output directory: {OUTPUT_BASE}")
        self._log("SCRAPING COMPLETED")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--start_index", type=int, required=True)
    parser.add_argument("--end_index", type=int, required=True)
    parser.add_argument("--days_interval", type=int, default=1)
    parser.add_argument("--run_id", required=True)
    args = parser.parse_args()

    scraper = UltraGeMScraper(args.username, args.start_index, args.end_index, run_id=args.run_id)
    try:
        asyncio.run(scraper.run(args.days_interval))
    except KeyboardInterrupt:
        scraper._log("\n[!] Scraper stopped by user.")
    except Exception as e:
        scraper._log(f"\n[FATAL ERROR] Scraper crashed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        asyncio.run(scraper.client.aclose())
