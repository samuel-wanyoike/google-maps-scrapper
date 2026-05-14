"""
Batch Scraper — runs multiple queries and merges results into one Excel workbook.

Usage:
    python batch_scrape.py
    python batch_scrape.py --max 30 --output orange_county_leads.xlsx
"""

import asyncio
import argparse
from dataclasses import asdict
from scraper import GoogleMapsScraper, Property, save_results, print_table

QUERIES = [
    "apartments Orange County CA",
    "warehouses Orange County CA",
    "gyms fitness centers Orange County CA",
    "commercial office buildings Orange County CA",
    "storage facilities Orange County CA",
    "shopping centers Orange County CA",
    "coworking spaces Orange County CA",
]


async def batch_scrape(max_per_query: int = 30, output: str = "orange_county_leads.xlsx", fetch_emails: bool = True):
    scraper = GoogleMapsScraper(headless=True)
    all_results: list[Property] = []
    seen_names = set()

    for query in QUERIES:
        print(f"\n{'='*60}")
        results = await scraper.scrape(query, max_results=max_per_query, fetch_emails=fetch_emails)

        # Deduplicate by name
        for r in results:
            key = r.name.lower().strip()
            if key and key not in seen_names:
                seen_names.add(key)
                all_results.append(r)

        print(f"  → Added {len(results)} | Total unique: {len(all_results)}")

    print_table(all_results)
    save_results(all_results, output)
    print(f"\n🎉 Done! {len(all_results)} unique properties saved to {output}")


async def main():
    parser = argparse.ArgumentParser(description="Batch Google Maps scraper for Orange County properties")
    parser.add_argument("--max", type=int, default=30, help="Max results per query (default: 30)")
    parser.add_argument("--output", default="orange_county_leads.xlsx", help="Output filename (.xlsx or .csv)")
    parser.add_argument("--no-email", action="store_true", help="Skip email fetching")
    args = parser.parse_args()

    await batch_scrape(
        max_per_query=args.max,
        output=args.output,
        fetch_emails=not args.no_email,
    )


if __name__ == "__main__":
    asyncio.run(main())
