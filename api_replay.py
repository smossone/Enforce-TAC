#!/usr/bin/env python3
"""
EnforceTac API Replay Script
==============================
After running the main scraper in --recon mode, you will find an
api_calls_log.json file containing the intercepted Sitecore Search API
requests. This script replays those requests with modified pagination
to pull all exhibitors in bulk, without needing a browser at all.

Usage:
    1. Run recon first:
       python enforcetac_scraper.py --recon --headed

    2. Edit the constants below with the discovered API endpoint and headers.

    3. Run this script:
       python api_replay.py

If step 1 produces an api_calls_log.json, this script will attempt to
auto-detect the endpoint and headers from that file.
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path

import requests  # pip install requests

# ---------------------------------------------------------------------------
# Configuration -- fill these in from recon output or api_calls_log.json
# ---------------------------------------------------------------------------

# Sitecore Discover endpoint (discovered during recon)
# Typical pattern: https://discover-euc1.sitecorecloud.io/discover/v2/<customer_key>
API_ENDPOINT = ""

# Headers observed on the API call (especially Authorization / rfk-domain-id)
API_HEADERS = {
    "Content-Type": "application/json",
    # "Authorization": "<api-key>",
    # "rfk-domain-id": "<domain-id>",
}

# The rfk_id of the exhibitor search widget (often rfkid_7 or similar)
WIDGET_RFK_ID = "rfkid_7"

# Entity type for exhibitors (could be "content", "product", "exhibitor", etc.)
ENTITY_TYPE = "content"

# Page size for bulk retrieval
PAGE_SIZE = 100

OUTPUT_FILE = "enforcetac_2026_exhibitors_api.xlsx"


# ---------------------------------------------------------------------------
# Auto-detect from recon log
# ---------------------------------------------------------------------------
def auto_detect_config():
    global API_ENDPOINT, API_HEADERS, WIDGET_RFK_ID, ENTITY_TYPE

    log_path = Path("api_calls_log.json")
    if not log_path.exists():
        return False

    calls = json.loads(log_path.read_text(encoding="utf-8"))
    if not calls:
        return False

    # Use the first POST call that looks like a Sitecore Search API call
    for call in calls:
        url = call.get("url", "")
        if any(kw in url.lower() for kw in ["discover", "search-rec", "rfksrv"]):
            API_ENDPOINT = url
            break

    if not API_ENDPOINT:
        return False

    # Try to extract rfk_id and entity from the POST body
    for call in calls:
        post = call.get("post_data", "")
        if post:
            try:
                body = json.loads(post) if isinstance(post, str) else post
                widgets = body.get("widget", {}).get("items", [])
                for w in widgets:
                    if w.get("rfk_id"):
                        WIDGET_RFK_ID = w["rfk_id"]
                    if w.get("entity"):
                        ENTITY_TYPE = w["entity"]
            except (json.JSONDecodeError, AttributeError):
                pass

    print(f"[AUTO] Detected endpoint: {API_ENDPOINT}")
    print(f"[AUTO] Widget rfk_id: {WIDGET_RFK_ID}")
    print(f"[AUTO] Entity type: {ENTITY_TYPE}")
    return True


# ---------------------------------------------------------------------------
# API query functions
# ---------------------------------------------------------------------------
def build_search_request(
    page_number: int = 1,
    page_size: int = PAGE_SIZE,
    facet_filter: dict = None,
) -> dict:
    """Build a Sitecore Search API request body."""

    request_body = {
        "context": {
            "locale": {"country": "de", "language": "en"},
            "user": {"uuid": "scraper-enforcetac-2026"},
        },
        "widget": {
            "items": [
                {
                    "rfk_id": WIDGET_RFK_ID,
                    "entity": ENTITY_TYPE,
                    "search": {
                        "content": {},
                        "limit": page_size,
                        "offset": (page_number - 1) * page_size,
                        "facet": {"all": True, "max": 100},
                    },
                }
            ]
        },
    }

    if facet_filter:
        request_body["widget"]["items"][0]["search"]["filter"] = facet_filter

    return request_body


def fetch_page(page_number: int, facet_filter: dict = None) -> dict:
    """Make a single API request and return the parsed response."""

    body = build_search_request(page_number=page_number, facet_filter=facet_filter)
    resp = requests.post(API_ENDPOINT, headers=API_HEADERS, json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def extract_exhibitors_from_response(response: dict) -> list[dict]:
    """Parse exhibitor data from a Sitecore Search API response."""

    exhibitors = []
    widgets = response.get("widgets", [])

    for widget in widgets:
        content = widget.get("content", [])
        if not content:
            # Alternative structure: widget -> entity -> content
            for entity_list in widget.get("entity", {}).values():
                if isinstance(entity_list, list):
                    content.extend(entity_list)

        for item in content:
            entry = {
                "company": item.get("name", item.get("title", "")),
                "url": item.get("url", item.get("uri", "")),
                "country": item.get("country", ""),
                "hall": item.get("hall", item.get("location", "")),
                "booth": item.get("booth", item.get("stand", "")),
                "product_category": item.get("category", item.get("type", "")),
            }

            # Also check nested 'attributes' dict (common in Sitecore Search)
            attrs = item.get("attributes", {})
            if attrs:
                entry["company"] = entry["company"] or attrs.get("name", "")
                entry["country"] = entry["country"] or attrs.get("country", "")
                entry["hall"] = entry["hall"] or attrs.get("hall", "")
                entry["booth"] = entry["booth"] or attrs.get("booth", "")

            if entry["company"]:
                exhibitors.append(entry)

    return exhibitors


def get_total_count(response: dict) -> int:
    """Extract total item count from response."""
    widgets = response.get("widgets", [])
    for w in widgets:
        for key in ["total_item", "total", "total_items", "total_count"]:
            if key in w:
                return int(w[key])
    return 0


def get_facets(response: dict) -> dict:
    """Extract available facets (categories, countries, etc.) from response."""
    facets = {}
    widgets = response.get("widgets", [])
    for w in widgets:
        for f in w.get("facet", []):
            name = f.get("name", "")
            label = f.get("label", name)
            values = []
            for v in f.get("value", []):
                values.append({
                    "id": v.get("id", ""),
                    "text": v.get("text", ""),
                    "count": v.get("count", 0),
                })
            if values:
                facets[name] = {"label": label, "values": values}
    return facets


# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("EnforceTac 2026 -- API Replay Exhibitor Extraction")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 70)

    if not API_ENDPOINT:
        detected = auto_detect_config()
        if not detected:
            print(
                "\n[ERROR] No API endpoint configured and no api_calls_log.json found."
                "\n        Run the main scraper in recon mode first:"
                "\n          python enforcetac_scraper.py --recon --headed"
                "\n        Then either run this script again (auto-detection) or"
                "\n        manually set API_ENDPOINT at the top of this file."
            )
            return

    # Step 1: Initial query to discover total count and facets
    print("\n[1/3] Initial API query to discover total exhibitor count...")
    try:
        first_response = fetch_page(1)
    except Exception as e:
        print(f"[ERROR] API request failed: {e}")
        print("[HINT] The API endpoint or headers may need adjustment.")
        print(f"       Current endpoint: {API_ENDPOINT}")
        return

    total = get_total_count(first_response)
    facets = get_facets(first_response)

    print(f"[INFO] Total exhibitors: {total}")
    print(f"[INFO] Available facets: {list(facets.keys())}")
    for fname, fdata in facets.items():
        print(f"       {fdata['label']}: {len(fdata['values'])} options")
        for v in fdata["values"][:5]:
            print(f"         - {v['text']} ({v['count']})")

    if total == 0:
        print("[WARN] No exhibitors returned. Check API configuration.")
        # Save response for debugging
        Path("api_debug_response.json").write_text(
            json.dumps(first_response, indent=2), encoding="utf-8"
        )
        print("[DEBUG] Response saved to api_debug_response.json")
        return

    # Step 2: Paginate through all results
    print(f"\n[2/3] Fetching all {total} exhibitors ({PAGE_SIZE} per page)...")
    all_exhibitors = {}
    pages_needed = (total + PAGE_SIZE - 1) // PAGE_SIZE

    for page_num in range(1, pages_needed + 1):
        if page_num == 1:
            resp = first_response
        else:
            time.sleep(0.3)  # polite delay
            try:
                resp = fetch_page(page_num)
            except Exception as e:
                print(f"[WARN] Page {page_num} failed: {e}")
                continue

        batch = extract_exhibitors_from_response(resp)
        for ex in batch:
            name = ex.get("company", "").strip()
            if name and name not in all_exhibitors:
                all_exhibitors[name] = ex

        print(
            f"[FETCH] Page {page_num}/{pages_needed}: "
            f"{len(batch)} items (cumulative: {len(all_exhibitors)})"
        )

    # Step 3: Export
    print(f"\n[3/3] Exporting {len(all_exhibitors)} exhibitors to {OUTPUT_FILE}...")

    # Reuse the Excel export from the main scraper
    from enforcetac_scraper import export_to_excel

    export_to_excel(list(all_exhibitors.values()), OUTPUT_FILE)
    print(f"[DONE] Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
