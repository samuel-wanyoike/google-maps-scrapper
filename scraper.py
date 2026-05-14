"""
Google Maps Property Scraper
=============================
Scrapes business listings from Google Maps using Playwright.
Extracts: name, address, phone, website, email (from website if found).

Usage:
    python scraper.py --query "apartments Orange County CA" --max 50
    python scraper.py --query "gyms Orange County CA" --max 30 --output gyms.csv
"""

import asyncio
import argparse
import csv
import json
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import pandas as pd

import httpx
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout


# ─────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────

@dataclass
class Property:
    name: str = ""
    address: str = ""
    phone: str = ""
    website: str = ""
    email: str = ""
    maps_url: str = ""
    category: str = ""


# ─────────────────────────────────────────────
# Email extraction from websites
# ─────────────────────────────────────────────

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
SKIP_EMAIL_DOMAINS = {"sentry.io", "wix.com", "example.com", "placeholder"}


async def extract_email_from_website(url: str, timeout: int = 10) -> str:
    """Fetch homepage + /contact page and extract first valid email."""
    if not url:
        return ""

    pages_to_try = [url, url.rstrip("/") + "/contact", url.rstrip("/") + "/about"]
    found_emails = set()

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for page_url in pages_to_try:
            try:
                resp = await client.get(page_url, headers={"User-Agent": "Mozilla/5.0"})
                text = resp.text
                emails = EMAIL_RE.findall(text)
                for email in emails:
                    domain = email.split("@")[-1].lower()
                    if not any(skip in domain for skip in SKIP_EMAIL_DOMAINS):
                        found_emails.add(email.lower())
                if found_emails:
                    break
            except Exception:
                continue

    # Prefer non-image/file emails
    for email in sorted(found_emails):
        if not any(email.endswith(ext) for ext in [".png", ".jpg", ".gif", ".svg"]):
            return email
    return ""


# ─────────────────────────────────────────────
# Google Maps scraper
# ─────────────────────────────────────────────

class GoogleMapsScraper:
    MAPS_URL = "https://www.google.com/maps/search/{query}?hl=en&gl=us"

    def __init__(self, headless: bool = True, slow_mo: int = 0):
        self.headless = headless
        self.slow_mo = slow_mo

    @staticmethod
    def _strip_label_prefix(value: str) -> str:
        if not value:
            return ""
        return re.sub(r"^[^:]+:\s*", "", value).strip()

    @staticmethod
    def _translate_category(category: str) -> str:
        """Translate common Swahili category terms to English."""
        translations = {
            "Ghorofa yenye Vyumba": "Apartments",
            "Mafundi": "Contractors",
            "Maduka": "Shops",
            "Hoteli": "Hotels",
            "Migahawa": "Restaurants",
            "Hospitali": "Hospitals",
            "Shule": "Schools",
            "Benki": "Banks",
            "Kituo cha posta": "Post Office",
            "Kituo cha polisi": "Police Station",
            "Jumba la biashara": "Commercial Building",
            "Ofisi": "Office",
            "Maktaba": "Library",
            "Kituo cha afya": "Health Center",
            "Kituo cha michezo": "Sports Center",
            "Duka la vifaa": "Hardware Store",
            "Duka la chakula": "Grocery Store",
            "Kituo cha mafuta": "Gas Station",
            "Kituo cha usafiri": "Transportation Hub",
            "Kituo cha burudani": "Entertainment Center",
        }
        return translations.get(category.strip(), category.strip())

    async def _scroll_results(self, page: Page, max_results: int):
        """Scroll the results panel to load more listings."""
        scrollable = page.locator('div[role="feed"]')
        prev_count = 0
        stall_count = 0

        while True:
            items = await page.locator('a[href*="/maps/place/"]').count()
            print(f"  ↳ Loaded {items} listings...", end="\r")

            if items >= max_results:
                break

            if items == prev_count:
                stall_count += 1
                if stall_count >= 3:
                    break  # No more results loading
            else:
                stall_count = 0

            prev_count = items
            await scrollable.evaluate("el => el.scrollBy(0, 1500)")
            await asyncio.sleep(1.5)

    async def _parse_listing(self, page: Page) -> dict:
        """Extract details from an open listing panel."""
        data = {}

        # Name
        try:
            data["name"] = await page.locator('h1[class*="DUwDvf"]').first.inner_text(timeout=3000)
        except PlaywrightTimeout:
            data["name"] = ""

        # Category
        try:
            data["category"] = await page.locator('button[jsaction*="category"]').first.inner_text(timeout=2000)
            data["category"] = self._translate_category(data["category"])
        except PlaywrightTimeout:
            data["category"] = ""

        # Address
        try:
            addr_el = page.locator('[data-item-id="address"]')
            data["address"] = await addr_el.get_attribute("aria-label", timeout=2000) or ""
            data["address"] = self._strip_label_prefix(data["address"])
        except PlaywrightTimeout:
            data["address"] = ""

        # Phone
        try:
            phone_el = page.locator('[data-item-id^="phone:tel:"]')
            data["phone"] = await phone_el.get_attribute("aria-label", timeout=2000) or ""
            data["phone"] = self._strip_label_prefix(data["phone"])
        except PlaywrightTimeout:
            data["phone"] = ""

        # Website
        try:
            web_el = page.locator('a[data-item-id="authority"]')
            data["website"] = await web_el.get_attribute("href", timeout=2000) or ""
        except PlaywrightTimeout:
            data["website"] = ""

        # Maps URL
        data["maps_url"] = page.url

        return data

    async def scrape(self, query: str, max_results: int = 50, fetch_emails: bool = True) -> list[Property]:
        results: list[Property] = []
        url = self.MAPS_URL.format(query=query.replace(" ", "+"))

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless, slow_mo=self.slow_mo)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                locale="en-US",
            )
            page = await context.new_page()

            print(f"\n🗺  Searching Google Maps: '{query}'")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except PlaywrightTimeout:
                print("⚠  Page load timed out after 60s; continuing with partially loaded content.")
            await asyncio.sleep(3)

            # Handle consent popup if present
            try:
                consent_btn = page.locator('button:has-text("Accept all"), button:has-text("Agree")')
                if await consent_btn.count() > 0:
                    await consent_btn.first.click()
                    await asyncio.sleep(1)
            except Exception:
                pass

            print(f"📜 Scrolling to collect up to {max_results} listings...")
            await self._scroll_results(page, max_results)

            # Collect all listing links
            listing_links = await page.locator('a[href*="/maps/place/"]').all()
            listing_links = listing_links[:max_results]
            print(f"\n✅ Found {len(listing_links)} listings. Extracting details...\n")

            for i, link in enumerate(listing_links, 1):
                try:
                    await link.click()
                    await asyncio.sleep(2)  # Wait for panel to load

                    raw = await self._parse_listing(page)
                    prop = Property(**{k: raw.get(k, "") for k in Property.__dataclass_fields__})

                    # Fetch email from website
                    if fetch_emails and prop.website:
                        print(f"  [{i}/{len(listing_links)}] {prop.name[:40]:<40} → fetching email...")
                        prop.email = await extract_email_from_website(prop.website)
                    else:
                        print(f"  [{i}/{len(listing_links)}] {prop.name[:40]:<40} → no website")

                    results.append(prop)

                except Exception as e:
                    print(f"  [{i}] Error: {e}")
                    continue

            await browser.close()

        return results


# ─────────────────────────────────────────────
# Output helpers
# ─────────────────────────────────────────────

def save_csv(results: list[Property], path: str, append_if_exists: bool = True):
    if not results:
        print("⚠  No results to save.")
        return

    output_path = Path(path)
    existing_urls = set()
    write_header = not output_path.exists()
    mode = "w"

    if append_if_exists and output_path.exists():
        mode = "a"
        with output_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            existing_urls = {row.get("maps_url", "").strip() for row in reader if row.get("maps_url", "").strip()}

    rows_to_write = []
    seen_urls = set(existing_urls)
    for result in results:
        url = result.maps_url.strip()
        if not url or url in seen_urls:
            continue
        rows_to_write.append(asdict(result))
        seen_urls.add(url)

    if not rows_to_write:
        print("⚠  No new records to save; existing file already contains these listings.")
        return

    with output_path.open(mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(Property.__dataclass_fields__.keys()))
        if write_header:
            writer.writeheader()
        writer.writerows(rows_to_write)

    print(f"\n💾 Saved {len(rows_to_write)} new records → {path}")


def save_excel(results: list[Property], path: str, append_if_exists: bool = True):
    if not results:
        print("⚠  No results to save.")
        return

    output_path = Path(path)
    rows = [asdict(result) for result in results]
    df = pd.DataFrame(rows)

    existing_urls = set()
    if append_if_exists and output_path.exists():
        existing_df = pd.read_excel(output_path, engine="openpyxl")
        existing_urls = {
            str(value).strip()
            for value in existing_df.get("maps_url", pd.Series(dtype="string")).fillna("")
            if str(value).strip()
        }

    rows_to_write = []
    seen_urls = set(existing_urls)
    for row in rows:
        url = str(row.get("maps_url", "")).strip()
        if not url or url in seen_urls:
            continue
        rows_to_write.append(row)
        seen_urls.add(url)

    if not rows_to_write:
        print("⚠  No new records to save; existing file already contains these listings.")
        return

    if output_path.exists() and append_if_exists:
        existing_df = pd.read_excel(output_path, engine="openpyxl")
        new_df = pd.concat([existing_df, pd.DataFrame(rows_to_write)], ignore_index=True)
        new_df.drop_duplicates(subset=["maps_url"], inplace=True)
        new_df.to_excel(output_path, index=False, engine="openpyxl")
    else:
        pd.DataFrame(rows_to_write).to_excel(output_path, index=False, engine="openpyxl")

    print(f"\n💾 Saved {len(rows_to_write)} new records → {path}")


def save_results(results: list[Property], path: str, append_if_exists: bool = True):
    if str(path).lower().endswith(".xlsx"):
        save_excel(results, path, append_if_exists=append_if_exists)
    else:
        save_csv(results, path, append_if_exists=append_if_exists)


def save_json(results: list[Property], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    print(f"💾 Saved JSON → {path}")


def print_table(results: list[Property]):
    if not results:
        return
    print("\n" + "─" * 100)
    print(f"{'NAME':<30} {'PHONE':<15} {'EMAIL':<30} {'ADDRESS':<25}")
    print("─" * 100)
    for r in results:
        print(f"{r.name[:29]:<30} {r.phone[:14]:<15} {r.email[:29]:<30} {r.address[:24]:<25}")
    print("─" * 100)


# ─────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Google Maps Property Scraper")
    parser.add_argument("--query", "-q", required=True, help='Search query e.g. "apartments Orange County CA"')
    parser.add_argument("--max", "-m", type=int, default=50, help="Max listings to scrape (default: 50)")
    parser.add_argument("--output", "-o", default="", help="Output filename (.xlsx or .csv) (default: auto-named)")
    parser.add_argument("--no-email", action="store_true", help="Skip email fetching (faster)")
    parser.add_argument("--visible", action="store_true", help="Run browser in visible mode (non-headless)")
    parser.add_argument("--json", action="store_true", help="Also save a JSON file")
    args = parser.parse_args()

    scraper = GoogleMapsScraper(headless=not args.visible)
    results = await scraper.scrape(
        query=args.query,
        max_results=args.max,
        fetch_emails=not args.no_email,
    )

    print_table(results)

    # Auto-name output file from query
    output_file = args.output or args.query.replace(" ", "_").replace('"', "") + ".xlsx"
    save_results(results, output_file)

    if args.json:
        json_path = output_file
        if json_path.lower().endswith(".xlsx"):
            json_path = json_path[:-5] + ".json"
        save_json(results, json_path)


if __name__ == "__main__":
    asyncio.run(main())
