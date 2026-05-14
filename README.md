# Google Maps Property Scraper

Scrapes Google Maps listings for property contacts in Orange County CA (or anywhere).
Extracts: **name, address, phone, website, email**.

---

## Setup

### 1. Install dependencies

```bash
pip install playwright httpx
playwright install chromium
```

### 2. Run a single query

```bash
python scraper.py --query "apartments Orange County CA" --max 50
```

### 3. Run all property types at once (batch)

```bash
python batch_scrape.py --max 30 --output orange_county_leads.xlsx
```

---

## CLI Options — scraper.py

| Flag              | Description                                | Default               |
| ----------------- | ------------------------------------------ | --------------------- |
| `--query` / `-q`  | Search query (required)                    | —                     |
| `--max` / `-m`    | Max listings to collect                    | 50                    |
| `--output` / `-o` | Output filename (.xlsx or .csv)            | auto-named from query |
| `--no-email`      | Skip website email extraction (faster)     | off                   |
| `--visible`       | Show browser window (useful for debugging) | off                   |
| `--json`          | Also save a `.json` file                   | off                   |

---

## Examples

```bash
# Apartments — collect 100, save to file
python scraper.py -q "apartments Orange County CA" -m 100 -o apartments.xlsx

# Gyms — fast mode, no email fetching
python scraper.py -q "gyms Orange County CA" --no-email

# Warehouses — visible browser for debugging
python scraper.py -q "warehouses Orange County CA" --visible

# Full batch across all property types
python batch_scrape.py --max 50 --output all_leads.xlsx
```

---

## Output columns (CSV / Excel)

| Column   | Example                                |
| -------- | -------------------------------------- |
| name     | Irvine Company Apartments              |
| address  | 100 Innovation, Irvine, CA 92617       |
| phone    | (949) 555-0123                         |
| website  | https://irvinecompany.com              |
| email    | leasing@irvinecompany.com              |
| maps_url | https://maps.google.com/maps/place/... |
| category | Apartment complex                      |

---

## Tips

- **Rate limiting**: The scraper has built-in delays. Don't set `--max` above 100 per run to avoid blocks.
- **Email accuracy**: Emails are found by scraping the property's website — not all sites publish one.
- **Anti-detection**: Uses realistic user-agent and viewport. If blocked, add `--visible` and increase delays in `scraper.py`.
- **Proxies**: For large-scale scraping, route through a rotating proxy by setting `proxy` in Playwright's `browser.launch()`.

## Migrating existing CSV data to Excel

If you already have output in CSV files, convert them to Excel and continue using `.xlsx` files with this helper:

```bash
python convert_csv_to_excel.py -i apartments_Orange_County_CA.csv
```

To convert every CSV in the current folder:

```bash
python convert_csv_to_excel.py
```

To place converted Excel files in a separate folder:

```bash
python convert_csv_to_excel.py -i . -o excel_outputs
```

After conversion, run `python scraper.py ... -o output.xlsx` or `python batch_scrape.py --output my_leads.xlsx`.
