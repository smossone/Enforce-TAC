# EnforceTac 2026 Exhibitor Scraper

A Python agent that extracts the full exhibitor list (~1,450 exhibitors) from
enforcetac.com by automating a headless Chromium browser.

## How It Works

The EnforceTac website loads exhibitor data dynamically via JavaScript (Sitecore
Search/Discover platform). Static HTTP requests return an empty shell. This
scraper uses Playwright to render the page, interact with category filters, and
click "Show more" to paginate through results.

**Two-phase strategy:**

| Phase | Script | Purpose |
|-------|--------|---------|
| 1. Recon | `enforcetac_scraper.py --recon` | Inspects DOM structure, captures API calls |
| 2a. Browser scrape | `enforcetac_scraper.py` | Cycles categories, clicks "Show more", reads DOM |
| 2b. API replay | `api_replay.py` | Uses discovered API endpoint for fast bulk extraction |

## Prerequisites

```bash
pip install playwright openpyxl requests
playwright install chromium
```

Tested on Python 3.10+.

## Quick Start

### Step 1: Reconnaissance (recommended first)

```bash
python enforcetac_scraper.py --recon --headed
```

This inspects the page structure and captures API endpoints. Review the output
before proceeding.

### Step 2a: Full Browser Scrape

```bash
python enforcetac_scraper.py          # headless
python enforcetac_scraper.py --headed  # visible browser
```

Expected runtime: 15-30 minutes for ~1,450 exhibitors.

### Step 2b: API Replay (faster)

If recon captured a Sitecore Discover API endpoint:

```bash
python api_replay.py
```

Expected runtime: ~2 minutes.

## Output

Excel file with columns: Company, Product Category, Country/Region, Hall,
Booth, URL, Raw Text.

## Troubleshooting

Run `--recon --headed` first. Inspect `recon_body.html` and
`api_calls_log.json` to adapt selectors if the DOM has changed.
