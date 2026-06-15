import argparse
import asyncio
import hashlib
import re
from pathlib import Path
from datetime import datetime

import fitz  # PyMuPDF
import httpx
import pandas as pd
from tqdm import tqdm


DATE_TIME_RE = re.compile(
    r"Bid\s*End\s*Date\s*/\s*Time\s*"
    r"([0-3]?\d[-/][01]?\d[-/]\d{4})"
    r"(?:\s+([0-2]?\d:[0-5]\d(?::[0-5]\d)?))?",
    re.IGNORECASE | re.DOTALL,
)


def parse_bid_end_date_from_pdf(pdf_path: Path):
    doc = None
    try:
        doc = fitz.open(pdf_path)

        max_pages = min(2, len(doc))
        text = "\n".join(doc[i].get_text("text") for i in range(max_pages))

        match = DATE_TIME_RE.search(text)

        if not match:
            return "", "", "", "not_found"

        date_part = match.group(1).replace("/", "-")
        time_part = match.group(2) or ""

        raw = f"{date_part} {time_part}".strip()

        parsed_date = ""
        for fmt in ("%d-%m-%Y", "%d-%m-%y"):
            try:
                parsed_date = datetime.strptime(date_part, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                pass

        return raw, parsed_date, time_part, "ok"

    except Exception as e:
        return "", "", "", f"parse_error: {e}"

    finally:
        if doc is not None:
            doc.close()


def safe_pdf_name(url: str):
    last = url.rstrip("/").split("/")[-1]

    if last:
        return f"{last}.pdf"

    hashed = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return f"{hashed}.pdf"


async def download_pdf(client, url: str, pdf_path: Path):
    if pdf_path.exists() and pdf_path.stat().st_size > 1000:
        return "cached"

    try:
        response = await client.get(url, follow_redirects=True, timeout=60)

        if response.status_code != 200:
            return f"http_{response.status_code}"

        content_type = response.headers.get("content-type", "").lower()

        if "pdf" not in content_type and not response.content.startswith(b"%PDF"):
            return f"not_pdf: {content_type}"

        pdf_path.write_bytes(response.content)
        return "downloaded"

    except Exception as e:
        return f"download_error: {e}"


async def main():
    parser = argparse.ArgumentParser(description="Extract Bid End Date/Time from GeM PDFs")
    parser.add_argument("--input_excel", required=True, help="Input merged GeM Excel file")
    parser.add_argument("--output_excel", required=True, help="Output Excel file")
    parser.add_argument("--pdf_dir", required=True, help="Folder to save temporary downloaded PDFs")
    parser.add_argument("--concurrency", type=int, default=8, help="Number of parallel PDF downloads")

    args = parser.parse_args()

    input_excel = Path(args.input_excel)
    output_excel = Path(args.output_excel)
    pdf_dir = Path(args.pdf_dir)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    if not input_excel.exists():
        raise FileNotFoundError(f"Input Excel not found: {input_excel}")

    df = pd.read_excel(input_excel)

    if "Document link" not in df.columns:
        raise ValueError("Column 'Document link' not found in Excel file.")

    urls = df["Document link"].fillna("").astype(str).tolist()

    pdf_raw_dates = [""] * len(df)
    pdf_dates = [""] * len(df)
    pdf_times = [""] * len(df)
    statuses = [""] * len(df)

    queue = asyncio.Queue()

    for i, url in enumerate(urls):
        await queue.put((i, url))

    limits = httpx.Limits(
        max_connections=args.concurrency,
        max_keepalive_connections=args.concurrency,
    )

    progress = tqdm(total=len(urls))

    async with httpx.AsyncClient(limits=limits, verify=False, follow_redirects=True, timeout=60) as client:

        async def worker():
            while True:
                try:
                    i, url = await queue.get()

                    if not url or not url.startswith("http"):
                        statuses[i] = "missing_url"
                        queue.task_done()
                        progress.update(1)
                        continue

                    # Unique temporary filename to avoid clashes in parallel mode
                    pdf_path = pdf_dir / f"{i}_{safe_pdf_name(url)}"

                    try:
                        download_status = await download_pdf(client, url, pdf_path)

                        if download_status not in ("downloaded", "cached"):
                            statuses[i] = download_status
                        else:
                            raw, date_only, time_only, parse_status = parse_bid_end_date_from_pdf(pdf_path)

                            pdf_raw_dates[i] = raw
                            pdf_dates[i] = date_only
                            pdf_times[i] = time_only
                            statuses[i] = parse_status

                    finally:
                        # Delete PDF immediately after parse/download attempt
                        try:
                            if pdf_path.exists():
                                pdf_path.unlink()
                        except Exception as e:
                            statuses[i] = f"{statuses[i]} | delete_error: {e}"

                    queue.task_done()
                    progress.update(1)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    # Prevent one worker crash from killing everything
                    try:
                        statuses[i] = f"worker_error: {e}"
                    except Exception:
                        pass

                    queue.task_done()
                    progress.update(1)

        workers = [
            asyncio.create_task(worker())
            for _ in range(args.concurrency)
        ]

        await queue.join()

        for w in workers:
            w.cancel()

        await asyncio.gather(*workers, return_exceptions=True)

    progress.close()

    df["PDF Bid End Date/Time"] = pdf_raw_dates
    df["PDF Bid End Date"] = pdf_dates
    df["PDF Bid End Time"] = pdf_times
    df["PDF Parse Status"] = statuses

    output_excel.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output_excel, index=False)

    print(f"Done. Output written to: {output_excel}")


if __name__ == "__main__":
    asyncio.run(main())